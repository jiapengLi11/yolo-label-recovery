#!/usr/bin/env node

import { spawn } from 'node:child_process'
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises'
import net from 'node:net'
import os from 'node:os'
import path from 'node:path'

const baseUrl = process.env.LABEL_REVIEW_CAPTURE_URL || 'http://127.0.0.1:8088'
const username = process.env.LABEL_REVIEW_CAPTURE_USERNAME
const password = process.env.LABEL_REVIEW_CAPTURE_PASSWORD
const outputDir = path.resolve(process.argv[2] || 'docs/assets')
const chromePath = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const viewportWidth = Number.parseInt(process.env.LABEL_REVIEW_CAPTURE_WIDTH || '1600', 10)
const viewportHeight = Number.parseInt(process.env.LABEL_REVIEW_CAPTURE_HEIGHT || '1200', 10)

if (!username || !password) {
  throw new Error('Set LABEL_REVIEW_CAPTURE_USERNAME and LABEL_REVIEW_CAPTURE_PASSWORD.')
}
if (!Number.isInteger(viewportWidth) || viewportWidth <= 0 || !Number.isInteger(viewportHeight) || viewportHeight <= 0) {
  throw new Error('LABEL_REVIEW_CAPTURE_WIDTH and LABEL_REVIEW_CAPTURE_HEIGHT must be positive integers.')
}

class CdpClient {
  constructor(url) {
    this.url = url
    this.nextId = 1
    this.pending = new Map()
  }

  async connect() {
    this.socket = new WebSocket(this.url)
    await new Promise((resolve, reject) => {
      this.socket.addEventListener('open', resolve, { once: true })
      this.socket.addEventListener('error', reject, { once: true })
    })
    this.socket.addEventListener('message', (event) => {
      const message = JSON.parse(event.data)
      if (!message.id) return
      const pending = this.pending.get(message.id)
      if (!pending) return
      this.pending.delete(message.id)
      if (message.error) pending.reject(new Error(message.error.message))
      else pending.resolve(message.result)
    })
  }

  send(method, params = {}) {
    const id = this.nextId++
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject })
      this.socket.send(JSON.stringify({ id, method, params }))
    })
  }

  close() {
    this.socket?.close()
  }
}

async function freePort() {
  const server = net.createServer()
  await new Promise((resolve, reject) => server.listen(0, '127.0.0.1', resolve).once('error', reject))
  const port = server.address().port
  await new Promise((resolve) => server.close(resolve))
  return port
}

async function retry(action, timeoutMs = 15_000) {
  const deadline = Date.now() + timeoutMs
  let error
  while (Date.now() < deadline) {
    try {
      return await action()
    } catch (reason) {
      error = reason
      await new Promise((resolve) => setTimeout(resolve, 200))
    }
  }
  throw error || new Error('Timed out')
}

async function evaluate(client, expression) {
  const result = await client.send('Runtime.evaluate', {
    expression,
    awaitPromise: true,
    returnByValue: true,
  })
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text)
  return result.result.value
}

async function waitFor(client, expression, timeoutMs = 15_000) {
  return retry(async () => {
    const ready = await evaluate(client, `Boolean(${expression})`)
    if (!ready) throw new Error(`Waiting for ${expression}`)
    return true
  }, timeoutMs)
}

async function settle(milliseconds = 900) {
  await new Promise((resolve) => setTimeout(resolve, milliseconds))
}

async function screenshot(client, fileName) {
  const result = await client.send('Page.captureScreenshot', {
    format: 'png',
    fromSurface: true,
    captureBeyondViewport: false,
  })
  await writeFile(path.join(outputDir, fileName), Buffer.from(result.data, 'base64'))
  console.log(`captured ${fileName}`)
}

async function main() {
  const loginResponse = await fetch(`${baseUrl}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (!loginResponse.ok) throw new Error(`Login failed: HTTP ${loginResponse.status}`)
  const { accessToken } = await loginResponse.json()

  await mkdir(outputDir, { recursive: true })
  const profileRoot = await mkdtemp(path.join(os.tmpdir(), 'label-review-capture-'))
  const port = await freePort()
  const browser = spawn(chromePath, [
    '--headless=new',
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profileRoot}`,
    '--no-first-run',
    '--disable-gpu',
    '--hide-scrollbars',
    'about:blank',
  ], { stdio: 'ignore', windowsHide: true })

  let client
  try {
    await retry(async () => {
      const response = await fetch(`http://127.0.0.1:${port}/json/version`)
      if (!response.ok) throw new Error('Chrome DevTools is not ready')
      return response.json()
    })
    const targetResponse = await fetch(
      `http://127.0.0.1:${port}/json/new?${encodeURIComponent(baseUrl)}`,
      { method: 'PUT' },
    )
    const target = await targetResponse.json()
    client = new CdpClient(target.webSocketDebuggerUrl)
    await client.connect()
    await client.send('Page.enable')
    await client.send('Runtime.enable')
    await client.send('Emulation.setDeviceMetricsOverride', {
      width: viewportWidth,
      height: viewportHeight,
      deviceScaleFactor: 1,
      mobile: false,
    })

    await waitFor(client, "document.readyState === 'complete' && document.querySelector('.login-shell')")
    await waitFor(client, "getComputedStyle(document.querySelector('.login-card')).opacity === '1'")
    await settle()
    await screenshot(client, 'platform-login.png')

    await evaluate(client, `localStorage.setItem('label-review-token', ${JSON.stringify(accessToken)}); location.reload()`)
    await waitFor(client, "document.readyState === 'complete' && document.querySelector('.workspace') && document.querySelector('.metrics')")
    await settle()
    await evaluate(client, 'scrollTo(0, 0)')
    await screenshot(client, 'platform-dashboard.png')

    await evaluate(client, `document.querySelector('.drawer-toggle').click()`)
    await waitFor(client, "document.querySelector('.admin-drawer form')")
    await settle(400)
    await evaluate(client, `document.querySelector('.admin-drawer').scrollIntoView({block: 'start'})`)
    await screenshot(client, 'platform-admin.png')

    await evaluate(client, `document.querySelector('.drawer-toggle').click(); scrollTo(0, 0)`)
    const hasActiveTask = await evaluate(client, "Boolean(document.querySelector('.image-stage'))")
    if (!hasActiveTask) {
      await evaluate(client, `document.querySelector('.empty-stage .button.primary').click()`)
    }
    await waitFor(client, "document.querySelector('.image-stage img')?.complete && document.querySelector('.image-stage img')?.naturalWidth > 0", 30_000)
    await settle(400)
    await evaluate(client, 'scrollTo(0, 0)')
    await screenshot(client, 'platform-review.png')

    const canOpenRecent = await evaluate(client, "Boolean(document.querySelector('.recent-toggle'))")
    if (canOpenRecent) {
      await evaluate(client, `document.querySelector('.recent-toggle').click()`)
      await waitFor(client, "document.querySelector('.recent-drawer')")
      await settle(300)
      await screenshot(client, 'platform-review-productivity.png')
      await evaluate(client, `document.querySelector('.recent-toggle').click()`)
    }

    const canRelease = await evaluate(client, "Boolean(document.querySelector('.release'))")
    if (canRelease) {
      await evaluate(client, `document.querySelector('.release').click()`)
      await waitFor(client, "document.querySelector('.empty-stage')")
    }
  } finally {
    try {
      if (client) await client.send('Browser.close')
    } catch {
      browser.kill()
    }
    client?.close()
    await new Promise((resolve) => setTimeout(resolve, 500))
    if (!browser.killed) browser.kill()
    const safePrefix = path.join(os.tmpdir(), 'label-review-capture-')
    if (profileRoot.startsWith(safePrefix)) await rm(profileRoot, { recursive: true, force: true })
  }
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})
