<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api, clearToken, login, saveToken, token, visualBlob } from './api'
import type { Decision, ImageCandidate, Progress, Project, ProjectMember, RecentDecision, ReviewTask, Role, User } from './api'

const currentUser = ref<User | null>(null)
const projects = ref<Project[]>([])
const selectedProject = ref<Project | null>(null)
const progress = ref<Progress | null>(null)
const task = ref<ReviewTask | null>(null)
const imageCandidates = ref<ImageCandidate[]>([])
const visualUrl = ref('')
const imageStage = ref<HTMLElement | null>(null)
const imageViewMode = ref<'fit' | 'actual' | 'zoom'>('actual')
const imageZoom = ref(100)
const comment = ref('')
const showShortcuts = ref(false)
const showRecent = ref(false)
const recentDecisions = ref<RecentDecision[]>([])
const busy = ref(false)
const error = ref('')
const notice = ref('')
const loginForm = ref({ username: '', password: '' })
const userForm = ref({ username: '', password: '', displayName: '', role: 'REVIEWER' as Role, projectIds: [] as number[] })
const adminUsers = ref<User[]>([])
const membersByProject = ref<Record<number, ProjectMember[]>>({})
const memberUsername = ref('')
const showAdmin = ref(false)
const heartbeatStatus = ref<'idle' | 'renewing' | 'ok' | 'error'>('idle')
const now = ref(Date.now())
const online = ref(navigator.onLine)
let heartbeatTimer: number | undefined
let clockTimer: number | undefined

const percent = computed(() => Math.round((progress.value?.completionRate ?? 0) * 100))
const leaseText = computed(() => task.value?.leaseUntil ? new Date(task.value.leaseUntil).toLocaleTimeString('zh-CN') : '--')
const taskIsActive = computed(() => task.value?.state === 'CLAIMED')
const leaseRemainingSeconds = computed(() => task.value?.leaseUntil
  ? Math.max(0, Math.floor((new Date(task.value.leaseUntil).getTime() - now.value) / 1000))
  : 0)
const leaseCountdown = computed(() => {
  const minutes = Math.floor(leaseRemainingSeconds.value / 60)
  const seconds = leaseRemainingSeconds.value % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
})
const leaseIsWarning = computed(() => taskIsActive.value && leaseRemainingSeconds.value <= 45)
const taskIsCompleted = computed(() => task.value?.state === 'COMPLETED' || task.value?.state === 'ESCALATED')
const currentImageCandidate = computed(() => imageCandidates.value.find(candidate => candidate.id === task.value?.id) ?? null)
const canReviseCurrent = computed(() => taskIsCompleted.value
  && (currentUser.value?.role === 'ADMIN' || currentImageCandidate.value?.decisionBy === currentUser.value?.username))
const currentCandidateIndex = computed(() => imageCandidates.value.findIndex(candidate => candidate.id === task.value?.id))
const pendingInImage = computed(() => imageCandidates.value.filter(candidate => candidate.state === 'PENDING').length)
const imageViewportStyle = computed(() => imageViewMode.value === 'zoom'
  ? { width: `${imageZoom.value}%`, height: `${imageZoom.value}%` }
  : {})
const assignableUsers = computed(() => {
  if (!selectedProject.value) return []
  const assignedIds = new Set((membersByProject.value[selectedProject.value.id] ?? []).map(member => member.userId))
  return adminUsers.value.filter(user => user.enabled && user.role !== 'ADMIN' && !assignedIds.has(user.id))
})

const decisionOptions = computed<{ value: Decision; label: string; tone: string; shortcut: string }[]>(() => {
  const recommended = task.value?.recommendedAction ?? ''
  const positive = recommended.includes('replace')
    ? { value: 'ACCEPT_REPLACE_GT' as Decision, label: '替换原框', tone: 'primary', shortcut: '1' }
    : recommended.includes('eval')
      ? { value: 'ACCEPT_EVAL_LABEL' as Decision, label: '确认评估标签', tone: 'primary', shortcut: '1' }
      : { value: 'ACCEPT_ADD' as Decision, label: '补入标签', tone: 'primary', shortcut: '1' }
  return [
    positive,
    { value: 'REJECT', label: '拒绝候选', tone: 'danger', shortcut: '2' },
    { value: 'UNCERTAIN', label: '标记疑难', tone: 'muted', shortcut: '3' },
  ]
})

async function bootstrap() {
  if (!token()) return
  try {
    currentUser.value = await api.me()
    projects.value = await api.projects()
    if (projects.value.length) await selectProject(projects.value[0])
  } catch (reason) {
    logout()
    error.value = message(reason)
  }
}

async function submitLogin() {
  busy.value = true
  error.value = ''
  try {
    const response = await login(loginForm.value.username, loginForm.value.password)
    saveToken(response.accessToken)
    currentUser.value = response.user
    projects.value = await api.projects()
    if (projects.value.length) await selectProject(projects.value[0])
  } catch (reason) {
    error.value = message(reason)
  } finally {
    busy.value = false
  }
}

async function selectProject(project: Project) {
  if (task.value && selectedProject.value?.id !== project.id) {
    error.value = '请先释放或完成当前任务，再切换项目。'
    return
  }
  selectedProject.value = project
  await Promise.all([refreshProgress(), refreshRecentDecisions()])
}

async function refreshProgress() {
  if (!selectedProject.value) return
  progress.value = await api.progress(selectedProject.value.id)
}

async function refreshRecentDecisions() {
  if (!selectedProject.value || currentUser.value?.role === 'AUDITOR') return
  recentDecisions.value = await api.recentDecisions(selectedProject.value.id)
}

async function claimNext() {
  if (!selectedProject.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    const claimed = await api.claim(selectedProject.value.id)
    if (!claimed) {
      notice.value = '当前没有可领取任务。'
      return
    }
    await activateTask(claimed)
  } catch (reason) {
    error.value = message(reason)
  } finally {
    busy.value = false
  }
}

async function activateTask(nextTask: ReviewTask, candidate?: ImageCandidate) {
  task.value = nextTask
  const stored = candidate ?? imageCandidates.value.find(item => item.id === nextTask.id)
  comment.value = stored?.decisionComment ?? ''
  await Promise.all([loadVisual(nextTask), loadImageCandidates(nextTask.id)])
  if (nextTask.state === 'CLAIMED') startHeartbeat()
  else stopHeartbeat()
}

async function loadImageCandidates(taskId: number) {
  imageCandidates.value = await api.imageCandidates(taskId)
  const current = imageCandidates.value.find(candidate => candidate.id === taskId)
  comment.value = current?.decisionComment ?? ''
}

async function submitDecision(decision: Decision) {
  if (!task.value || busy.value || (!taskIsActive.value && !canReviseCurrent.value)) return
  const wasActive = taskIsActive.value
  busy.value = true
  error.value = ''
  try {
    const saved = wasActive
      ? await api.decide(task.value, decision, comment.value)
      : await api.reviseDecision(task.value, decision, comment.value)
    task.value = saved
    stopHeartbeat()
    await loadImageCandidates(saved.id)
    await Promise.all([refreshProgress(), refreshRecentDecisions()])
    if (wasActive) {
      await advanceAfterDecision(saved.id)
    } else {
      notice.value = '历史决定已修改并写入审计记录。'
    }
  } catch (reason) {
    error.value = message(reason)
  } finally {
    busy.value = false
  }
}

async function advanceAfterDecision(completedTaskId: number) {
  const completedIndex = imageCandidates.value.findIndex(candidate => candidate.id === completedTaskId)
  const ordered = [
    ...imageCandidates.value.slice(completedIndex + 1),
    ...imageCandidates.value.slice(0, Math.max(completedIndex, 0)),
  ]
  const nextInImage = ordered.find(candidate =>
    candidate.state === 'PENDING'
      || (candidate.state === 'CLAIMED' && candidate.claimedBy === currentUser.value?.username),
  )
  if (nextInImage) {
    const nextTask = nextInImage.state === 'CLAIMED'
      ? await api.task(nextInImage.id)
      : await api.claimTask(nextInImage.id)
    await activateTask(nextTask, nextInImage)
    notice.value = '决定已保存，已自动进入本图下一框。'
    return
  }
  clearTask()
  if (!selectedProject.value) return
  const nextTask = await api.claim(selectedProject.value.id)
  if (nextTask) {
    await activateTask(nextTask)
    notice.value = '本图审核完成，已自动进入下一图。'
  } else {
    notice.value = '决定已保存，当前项目没有更多待审核任务。'
  }
}

async function openCandidate(candidate: ImageCandidate) {
  if (busy.value || candidate.id === task.value?.id) return
  const ownedSibling = candidate.state === 'CLAIMED' && candidate.claimedBy === currentUser.value?.username
  if (taskIsActive.value && !ownedSibling) {
    const shouldSwitch = window.confirm('当前图片尚未审核完成。切换会释放本图剩余任务，确定继续吗？')
    if (!shouldSwitch || !task.value) return
    await api.release(task.value.id)
    stopHeartbeat()
    task.value = null
    revokeVisual()
  }
  busy.value = true
  error.value = ''
  try {
    if (ownedSibling) {
      await activateTask(await api.task(candidate.id), candidate)
      notice.value = '已切换到本图中由你领取的审核框。'
      return
    }
    if (candidate.state === 'PENDING') {
      await activateTask(await api.claimTask(candidate.id), candidate)
      notice.value = '已切换到本图中的待审核框。'
      return
    }
    if (candidate.state === 'CLAIMED' && candidate.claimedBy !== currentUser.value?.username) {
      notice.value = `该框正在由 ${candidate.claimedBy ?? '其他审核员'} 审核。`
      return
    }
    const selected = await api.task(candidate.id)
    await activateTask(selected, candidate)
    notice.value = candidate.decisionBy === currentUser.value?.username || currentUser.value?.role === 'ADMIN'
      ? '已打开历史决定，可以修改后重新保存。'
      : `该框由 ${candidate.decisionBy ?? '其他审核员'} 完成，当前为只读查看。`
  } catch (reason) {
    error.value = message(reason)
    if (task.value) await loadImageCandidates(task.value.id)
  } finally {
    busy.value = false
  }
}

async function openRecentDecision(recent: RecentDecision) {
  if (busy.value || recent.taskId === task.value?.id) return
  if (taskIsActive.value) {
    const shouldSwitch = window.confirm('当前图片尚未审核完成。打开历史记录会释放本图剩余任务，确定继续吗？')
    if (!shouldSwitch || !task.value) return
    await api.release(task.value.id)
    clearTask()
  }
  busy.value = true
  error.value = ''
  try {
    const historicalTask = await api.task(recent.taskId)
    await activateTask(historicalTask)
    showRecent.value = false
    notice.value = '已回到最近审核记录。修改后再次保存会完整记录审计轨迹。'
  } catch (reason) {
    error.value = message(reason)
  } finally {
    busy.value = false
  }
}

async function nextCandidate() {
  if (busy.value) return
  if (taskIsActive.value) {
    error.value = '请先确认保存或释放当前框，再进入下一框。'
    return
  }
  const start = Math.max(currentCandidateIndex.value + 1, 0)
  const ordered = [...imageCandidates.value.slice(start), ...imageCandidates.value.slice(0, start)]
  const next = ordered.find(candidate =>
    candidate.state === 'PENDING'
      || (candidate.state === 'CLAIMED' && candidate.claimedBy === currentUser.value?.username),
  )
  if (next) {
    await openCandidate(next)
    return
  }
  clearTask()
  await claimNext()
}

async function nextImage() {
  if (taskIsActive.value) {
    error.value = '当前框尚未提交，不能跳到下一图。'
    return
  }
  clearTask()
  await claimNext()
}

async function releaseTask() {
  if (!task.value) return
  busy.value = true
  try {
    await api.release(task.value.id)
    clearTask()
    await refreshProgress()
    notice.value = '任务已释放，其他审核员可以继续领取。'
  } catch (reason) {
    error.value = message(reason)
  } finally {
    busy.value = false
  }
}

async function createUser() {
  if (userForm.value.role !== 'ADMIN' && !userForm.value.projectIds.length) {
    error.value = '审核员或审计员至少需要分配一个项目。'
    return
  }
  busy.value = true
  error.value = ''
  try {
    await api.createUser(userForm.value)
    const assignedNames = projects.value
      .filter(project => userForm.value.projectIds.includes(project.id))
      .map(project => project.name)
    notice.value = userForm.value.role === 'ADMIN'
      ? '管理员账号已创建，可访问全部项目。'
      : `协作账号已创建并授权：${assignedNames.join('、')}。`
    userForm.value = {
      username: '',
      password: '',
      displayName: '',
      role: 'REVIEWER',
      projectIds: selectedProject.value ? [selectedProject.value.id] : [],
    }
    await loadAdminData()
  } catch (reason) {
    error.value = message(reason)
  } finally {
    busy.value = false
  }
}

async function assignMember() {
  if (!selectedProject.value || !memberUsername.value.trim()) return
  busy.value = true
  error.value = ''
  try {
    await api.assignMember(selectedProject.value.id, memberUsername.value.trim())
    notice.value = `已将 ${memberUsername.value.trim()} 分配到 ${selectedProject.value.name}。`
    memberUsername.value = ''
    await loadAdminData()
  } catch (reason) {
    error.value = message(reason)
  } finally {
    busy.value = false
  }
}

async function toggleAdmin() {
  showAdmin.value = !showAdmin.value
  if (!showAdmin.value) return
  if (userForm.value.role !== 'ADMIN' && !userForm.value.projectIds.length && selectedProject.value) {
    userForm.value.projectIds = [selectedProject.value.id]
  }
  try {
    await loadAdminData()
  } catch (reason) {
    error.value = message(reason)
  }
}

async function loadAdminData() {
  if (currentUser.value?.role !== 'ADMIN') return
  adminUsers.value = await api.users()
  const memberLists = await Promise.all(projects.value.map(project => api.members(project.id)))
  membersByProject.value = Object.fromEntries(
    projects.value.map((project, index) => [project.id, memberLists[index]]),
  )
}

function projectNamesFor(user: User): string[] {
  if (user.role === 'ADMIN') return ['全部项目']
  return projects.value
    .filter(project => (membersByProject.value[project.id] ?? []).some(member => member.userId === user.id))
    .map(project => project.name)
}

async function loadVisual(nextTask: ReviewTask) {
  revokeVisual()
  showActualSize()
  visualUrl.value = await visualBlob(nextTask)
}

function resetImageView() {
  imageViewMode.value = 'fit'
  imageZoom.value = 100
  imageStage.value?.scrollTo({ top: 0, left: 0 })
}

function showActualSize() {
  imageViewMode.value = 'actual'
  imageZoom.value = 100
  imageStage.value?.scrollTo({ top: 0, left: 0 })
}

function zoomImage(delta: number) {
  if (imageViewMode.value !== 'zoom') imageZoom.value = 100
  imageViewMode.value = 'zoom'
  imageZoom.value = Math.min(400, Math.max(50, imageZoom.value + delta))
}

async function toggleImageFullscreen() {
  if (!imageStage.value) return
  if (document.fullscreenElement) await document.exitFullscreen()
  else await imageStage.value.requestFullscreen()
}

function startHeartbeat() {
  stopHeartbeat()
  heartbeatStatus.value = 'ok'
  heartbeatTimer = window.setInterval(async () => {
    if (!task.value) return
    try {
      heartbeatStatus.value = 'renewing'
      task.value = await api.heartbeat(task.value.id)
      heartbeatStatus.value = 'ok'
    } catch (reason) {
      heartbeatStatus.value = 'error'
      error.value = message(reason)
      clearTask()
    }
  }, 30_000)
}

function stopHeartbeat() {
  if (heartbeatTimer) window.clearInterval(heartbeatTimer)
  heartbeatTimer = undefined
  if (heartbeatStatus.value !== 'error') heartbeatStatus.value = 'idle'
}

function clearTask() {
  task.value = null
  imageCandidates.value = []
  comment.value = ''
  stopHeartbeat()
  revokeVisual()
}

function revokeVisual() {
  if (visualUrl.value) URL.revokeObjectURL(visualUrl.value)
  visualUrl.value = ''
}

function logout() {
  clearTask()
  clearToken()
  currentUser.value = null
  projects.value = []
  selectedProject.value = null
  progress.value = null
  adminUsers.value = []
  membersByProject.value = {}
  showAdmin.value = false
  showRecent.value = false
  recentDecisions.value = []
}

function message(reason: unknown): string {
  return reason instanceof Error ? reason.message : '发生未知错误'
}

function isTypingTarget(target: EventTarget | null): boolean {
  return target instanceof HTMLInputElement
    || target instanceof HTMLTextAreaElement
    || target instanceof HTMLSelectElement
}

function handleOnline() {
  online.value = true
}

function handleOffline() {
  online.value = false
  heartbeatStatus.value = 'error'
}

async function moveCandidate(offset: number) {
  if (!imageCandidates.value.length || taskIsActive.value) return
  const current = currentCandidateIndex.value < 0 ? 0 : currentCandidateIndex.value
  const nextIndex = (current + offset + imageCandidates.value.length) % imageCandidates.value.length
  await openCandidate(imageCandidates.value[nextIndex])
}

async function handleShortcut(event: KeyboardEvent) {
  if (!currentUser.value) return
  if (event.key === '?') {
    event.preventDefault()
    showShortcuts.value = !showShortcuts.value
    return
  }
  if (isTypingTarget(event.target)) {
    return
  }
  const option = decisionOptions.value.find(item => item.shortcut === event.key)
  if (option) {
    event.preventDefault()
    await submitDecision(option.value)
    return
  }
  if (event.key.toLowerCase() === 'n') {
    event.preventDefault()
    if (event.shiftKey) await nextImage()
    else await nextCandidate()
  } else if (event.key === 'ArrowDown' || event.key.toLowerCase() === 'j') {
    event.preventDefault()
    await moveCandidate(1)
  } else if (event.key === 'ArrowUp' || event.key.toLowerCase() === 'k') {
    event.preventDefault()
    await moveCandidate(-1)
  } else if ((event.key === '+' || event.key === '=') && task.value) {
    event.preventDefault()
    zoomImage(25)
  } else if (event.key === '-' && task.value) {
    event.preventDefault()
    zoomImage(-25)
  } else if (event.key === '0' && task.value) {
    event.preventDefault()
    resetImageView()
  } else if (event.key.toLowerCase() === 'r' && taskIsActive.value) {
    event.preventDefault()
    if (window.confirm('确定释放当前任务吗？')) await releaseTask()
  }
}

watch(selectedProject, () => {
  error.value = ''
  notice.value = ''
  memberUsername.value = ''
  if (showAdmin.value && userForm.value.role !== 'ADMIN' && !userForm.value.projectIds.length && selectedProject.value) {
    userForm.value.projectIds = [selectedProject.value.id]
  }
})
watch(() => userForm.value.role, role => {
  if (role === 'ADMIN') {
    userForm.value.projectIds = []
  } else if (!userForm.value.projectIds.length && selectedProject.value) {
    userForm.value.projectIds = [selectedProject.value.id]
  }
})
onMounted(() => {
  window.addEventListener('keydown', handleShortcut)
  window.addEventListener('online', handleOnline)
  window.addEventListener('offline', handleOffline)
  clockTimer = window.setInterval(() => {
    now.value = Date.now()
  }, 1_000)
  void bootstrap()
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleShortcut)
  window.removeEventListener('online', handleOnline)
  window.removeEventListener('offline', handleOffline)
  if (clockTimer) window.clearInterval(clockTimer)
  stopHeartbeat()
  revokeVisual()
})
</script>

<template>
  <main v-if="!currentUser" class="login-shell">
    <section class="login-story">
      <div class="eyebrow">LABEL RECOVERY / COLLABORATION</div>
      <h1>让每一个补标决定<br><span>可领取、可追溯、可复现</span></h1>
      <p>面向 Multi-Teacher 漏标恢复的多人审核工作台。任务租约防止重复劳动，角色权限控制操作边界，审计日志记录每一次决定。</p>
      <div class="story-grid">
        <div><strong>6</strong><span>单类别 Teacher</span></div>
        <div><strong>4</strong><span>GT/AUTO 状态空间</span></div>
        <div><strong>100%</strong><span>决策审计留痕</span></div>
      </div>
    </section>
    <form class="login-card" @submit.prevent="submitLogin">
      <div class="brand-mark">矿安标注协作台</div>
      <h2>进入审核任务</h2>
      <label>账号<input v-model="loginForm.username" autocomplete="username" required placeholder="reviewer01"></label>
      <label>密码<input v-model="loginForm.password" autocomplete="current-password" type="password" required placeholder="至少 12 位"></label>
      <p v-if="error" class="message error">{{ error }}</p>
      <button class="button primary wide" :disabled="busy">{{ busy ? '正在验证...' : '登录协作台' }}</button>
      <small>ADMIN 管理项目与账号，REVIEWER 领取任务，AUDITOR 查看审计。</small>
    </form>
  </main>

  <main v-else class="workspace">
    <header class="topbar">
      <div><div class="eyebrow">MULTI-TEACHER QA</div><h1>矿安标注协作台</h1></div>
      <div class="identity">
        <span class="connection-status" :class="{ offline: !online || heartbeatStatus === 'error', renewing: heartbeatStatus === 'renewing' }">
          <i></i>{{ !online ? '网络离线' : heartbeatStatus === 'error' ? '续租异常' : heartbeatStatus === 'renewing' ? '正在续租' : '连接正常' }}
        </span>
        <button v-if="selectedProject && currentUser.role !== 'AUDITOR'" class="recent-toggle" type="button" @click="showRecent = !showRecent">
          最近审核 <span>{{ recentDecisions.length }}</span>
        </button>
        <span class="role">{{ currentUser.role }}</span>
        <div><strong>{{ currentUser.displayName }}</strong><small>@{{ currentUser.username }}</small></div>
        <button class="link-button" @click="logout">退出</button>
      </div>
    </header>

    <section class="project-strip">
      <button v-for="project in projects" :key="project.id" class="project-tab" :class="{ active: selectedProject?.id === project.id }" @click="selectProject(project)">
        <span class="status-dot"></span><strong>{{ project.name }}</strong><small>{{ project.status }}</small>
      </button>
      <p v-if="!projects.length && currentUser.role === 'ADMIN'" class="empty">尚未创建项目，请先创建项目并导入审核队列。</p>
      <p v-else-if="!projects.length" class="message error access-warning">当前账号尚未分配审核项目，请联系管理员完成项目授权后刷新页面。</p>
    </section>

    <section v-if="selectedProject && progress" class="metrics">
      <article><span>总候选</span><strong>{{ progress.total.toLocaleString() }}</strong></article>
      <article><span>待审核</span><strong>{{ progress.pending.toLocaleString() }}</strong></article>
      <article><span>协作占用</span><strong>{{ progress.claimed }}</strong></article>
      <article><span>疑难升级</span><strong>{{ progress.escalated }}</strong></article>
      <article class="completion"><div><span>完成率</span><strong>{{ percent }}%</strong></div><div class="bar"><i :style="{ width: `${percent}%` }"></i></div></article>
    </section>

    <p v-if="error" class="message error banner">{{ error }}</p>
    <p v-if="notice" class="message notice banner">{{ notice }}</p>

    <section v-if="showRecent" class="recent-drawer" aria-label="我的最近审核记录">
      <div class="recent-head">
        <div><strong>我的最近审核</strong><span>显示当前账号在当前项目中的最近决定，可打开并复查</span></div>
        <button class="link-button" type="button" @click="showRecent = false">关闭</button>
      </div>
      <div v-if="recentDecisions.length" class="recent-list">
        <button
          v-for="item in recentDecisions"
          :key="item.taskId"
          class="recent-item"
          type="button"
          :disabled="busy"
          @click="openRecentDecision(item)"
        >
          <span class="recent-class">{{ item.className }}</span>
          <span class="recent-image">{{ item.imageName }}</span>
          <span class="recent-decision">{{ item.decision }}</span>
          <time :datetime="item.decidedAt">{{ new Date(item.decidedAt).toLocaleString('zh-CN') }}</time>
        </button>
      </div>
      <p v-else class="empty">当前项目还没有你的审核记录。</p>
    </section>

    <section class="review-layout" :class="{ 'has-candidates': task }">
      <aside v-if="task" class="candidate-rail">
        <div class="candidate-rail-head">
          <div><strong>本图审核框</strong><span>{{ imageCandidates.length }} 个</span></div>
          <small>待审 {{ pendingInImage }} · 当前 {{ currentCandidateIndex + 1 }}/{{ imageCandidates.length }}</small>
        </div>
        <div class="candidate-list">
          <button
            v-for="(candidate, index) in imageCandidates"
            :key="candidate.id"
            class="candidate-item"
            :class="[
              candidate.state.toLowerCase(),
              { active: candidate.id === task.id, readonly: candidate.decisionBy && candidate.decisionBy !== currentUser.username && currentUser.role !== 'ADMIN' },
            ]"
            :disabled="busy"
            @click="openCandidate(candidate)"
          >
            <span class="candidate-order">{{ String(index + 1).padStart(2, '0') }}</span>
            <span class="candidate-summary">
              <strong>{{ candidate.className }}</strong>
              <small>{{ candidate.caseCode }} · {{ (candidate.confidence * 100).toFixed(1) }}%</small>
            </span>
            <span class="candidate-state">
              {{ candidate.state === 'PENDING' ? '待审核' : candidate.state === 'CLAIMED' ? (candidate.claimedBy === currentUser.username ? '审核中' : '他人占用') : candidate.state === 'ESCALATED' ? '疑难' : '已完成' }}
            </span>
          </button>
        </div>
        <div class="rail-help">↑/↓ 或 J/K 浏览 · N 下一框</div>
      </aside>

      <article class="canvas-panel">
        <div class="panel-head" :class="{ warning: leaseIsWarning }">
          <div><span class="live-dot" :class="{ saved: taskIsCompleted, warning: leaseIsWarning }"></span>{{ task ? (taskIsActive ? '图片级租约生效中' : '已保存，可复查修改') : '等待领取' }}</div>
          <span v-if="taskIsActive" class="lease-countdown" :class="{ warning: leaseIsWarning }">剩余 {{ leaseCountdown }} · 至 {{ leaseText }}</span>
          <span v-else-if="task">本图 {{ imageCandidates.length }} 个候选框</span>
        </div>
        <div v-if="task" ref="imageStage" class="image-stage">
          <div class="image-toolbar">
            <button :class="{ active: imageViewMode === 'fit' }" title="让整张图片适应当前窗口 (0)" @click="resetImageView">适应窗口 <kbd>0</kbd></button>
            <button :class="{ active: imageViewMode === 'actual' }" title="按图片原始像素显示" @click="showActualSize">原始尺寸</button>
            <button title="缩小 (-)" @click="zoomImage(-25)">−</button>
            <span>{{ imageViewMode === 'zoom' ? `${imageZoom}%` : imageViewMode === 'fit' ? '自适应' : '1:1' }}</span>
            <button title="放大 (+)" @click="zoomImage(25)">+</button>
            <button title="进入或退出全屏" @click="toggleImageFullscreen">全屏</button>
          </div>
          <div v-if="visualUrl" class="image-viewport" :class="imageViewMode" :style="imageViewportStyle">
            <img :src="visualUrl" :alt="task.imageName">
          </div>
          <div v-else class="loader">正在加载真实审核图...</div>
        </div>
        <div v-else class="empty-stage">
          <span>R</span><h2>准备好开始审核了吗？</h2><p>系统会原子领取一条候选，其他审核员不会拿到同一任务。</p>
          <button class="button primary" :disabled="busy || !selectedProject || currentUser.role === 'AUDITOR'" @click="claimNext">领取下一条任务</button>
        </div>
      </article>

      <aside class="decision-panel">
        <template v-if="task">
          <div class="decision-status" :class="{ saved: taskIsCompleted, readonly: taskIsCompleted && !canReviseCurrent }">
            <strong>{{ taskIsActive ? '一键审核' : canReviseCurrent ? '已保存，可修改' : '已由其他审核员完成' }}</strong>
            <span>{{ taskIsActive ? '点击决定后立即保存，并自动进入下一框或下一图' : canReviseCurrent ? '点击新决定会立即改判并留下审计记录' : '当前仅供查看，不可改判' }}</span>
          </div>
          <div class="candidate-id">{{ task.candidateId }}</div>
          <h2>{{ task.className }} <span>{{ (task.confidence * 100).toFixed(1) }}%</span></h2>
          <dl>
            <div><dt>状态枚举</dt><dd>{{ task.caseCode }}</dd></div>
            <div><dt>建议动作</dt><dd>{{ task.recommendedAction }}</dd></div>
            <div><dt>数据划分</dt><dd>{{ task.split }}</dd></div>
            <div><dt>图像名称</dt><dd class="wrap">{{ task.imageName }}</dd></div>
          </dl>
          <label class="comment">审核备注<textarea v-model="comment" maxlength="1000" :readonly="taskIsCompleted && !canReviseCurrent" placeholder="可选：记录接受或拒绝依据"></textarea></label>
          <div class="decision-actions">
            <button
              v-for="option in decisionOptions"
              :key="option.value"
              class="button decision-choice"
              :class="option.tone"
              :disabled="busy || (!taskIsActive && !canReviseCurrent)"
              @click="submitDecision(option.value)"
            >
              <kbd>{{ option.shortcut }}</kbd><span>{{ taskIsActive ? `${option.label}并继续` : option.label }}</span>
            </button>
          </div>
          <p class="safe-hint">决定按钮会立即保存；主审核流程保存后自动前进，历史改判则停留当前图。</p>
          <div class="navigation-actions">
            <button class="button muted" :disabled="busy || taskIsActive" @click="nextCandidate">下一框 <kbd>N</kbd></button>
            <button class="button muted" :disabled="busy || taskIsActive" @click="nextImage">下一图 <kbd>Shift+N</kbd></button>
          </div>
          <div class="secondary-actions">
            <button v-if="taskIsActive" class="link-button release" :disabled="busy" @click="releaseTask">暂不处理，释放任务 <kbd>R</kbd></button>
            <button class="link-button" @click="showShortcuts = !showShortcuts">{{ showShortcuts ? '收起快捷键' : '查看全部快捷键' }} <kbd>?</kbd></button>
          </div>
          <div v-if="showShortcuts" class="shortcut-card">
            <div><kbd>1 / 2 / 3</kbd><span>立即保存接受、拒绝、疑难并自动前进</span></div>
            <div><kbd>N / Shift+N</kbd><span>下一框 / 下一图</span></div>
            <div><kbd>↑ ↓ / J K</kbd><span>浏览本图候选框</span></div>
            <div><kbd>R</kbd><span>释放当前图片的未审核任务</span></div>
            <div><kbd>0 / + / -</kbd><span>适应窗口 / 放大 / 缩小图片</span></div>
          </div>
        </template>
        <template v-else>
          <div class="guide-number">01</div><h2>领取后再判断</h2><p>真实图像、GT 框和 AUTO 框会在同一张审核图里显示。按钮由候选建议动作动态约束，降低误操作风险。</p>
          <div class="guide-number">02</div><h2>图片级心跳续租</h2><p>页面每 30 秒为当前图片的全部候选框统一续租；关闭页面后租约到期，整张图片自动回到公共队列。</p>
        </template>
      </aside>
    </section>

    <section v-if="currentUser.role === 'ADMIN'" class="admin-drawer">
      <button class="drawer-toggle" @click="toggleAdmin">{{ showAdmin ? '收起账号与权限管理' : '管理员：账号与项目权限' }}</button>
      <form v-if="showAdmin" class="account-create" @submit.prevent="createUser">
        <div class="account-fields">
          <input v-model="userForm.username" required maxlength="64" placeholder="登录账号">
          <input v-model="userForm.displayName" required maxlength="100" placeholder="显示名称">
          <input v-model="userForm.password" required minlength="12" type="password" placeholder="临时密码（至少 12 位）">
          <select v-model="userForm.role"><option>REVIEWER</option><option>AUDITOR</option><option>ADMIN</option></select>
        </div>
        <fieldset v-if="userForm.role !== 'ADMIN'" class="project-access">
          <legend>创建后可访问的项目（至少选择一个）</legend>
          <label v-for="project in projects" :key="project.id">
            <input v-model="userForm.projectIds" type="checkbox" :value="project.id">
            <span>{{ project.name }}</span><small>{{ project.status }}</small>
          </label>
          <p v-if="!projects.length">当前没有可授权项目，请先创建项目。</p>
        </fieldset>
        <p v-else class="admin-access-note">管理员账号默认访问全部项目，不需要单独授权。</p>
        <button class="button primary create-account" :disabled="busy || (userForm.role !== 'ADMIN' && !userForm.projectIds.length)">创建账号并完成授权</button>
      </form>
      <form v-if="showAdmin" class="member-assign" @submit.prevent="assignMember">
        <select v-model="memberUsername" required>
          <option value="" disabled>选择尚未加入当前项目的账号</option>
          <option v-for="user in assignableUsers" :key="user.id" :value="user.username">{{ user.displayName }} (@{{ user.username }})</option>
        </select>
        <span>补充分配到：{{ selectedProject?.name || '请先选择项目' }}</span>
        <button class="button muted" :disabled="busy || !selectedProject || !memberUsername">补充项目权限</button>
      </form>
      <section v-if="showAdmin" class="account-list">
        <div class="account-list-head"><strong>账号权限状态</strong><span>{{ adminUsers.length }} 个账号</span></div>
        <div v-for="user in adminUsers" :key="user.id" class="account-row">
          <div><strong>{{ user.displayName }}</strong><small>@{{ user.username }} · {{ user.role }}</small></div>
          <div class="access-badges">
            <span v-for="name in projectNamesFor(user)" :key="name" class="access-badge">{{ name }}</span>
            <span v-if="!projectNamesFor(user).length" class="access-badge warning">未分配项目，无法领取任务</span>
          </div>
        </div>
      </section>
    </section>
  </main>
</template>
