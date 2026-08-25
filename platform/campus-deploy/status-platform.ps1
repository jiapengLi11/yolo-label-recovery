$pidFile = Join-Path $PSScriptRoot "platform.pid"
$configFile = Join-Path $PSScriptRoot "campus.local.env"
$running = $false
$platformPid = $null

if (Test-Path -LiteralPath $configFile) {
    Get-Content -LiteralPath $configFile | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith('#')) { return }
        $parts = $line.Split('=', 2)
        if ($parts.Count -eq 2) {
            [Environment]::SetEnvironmentVariable($parts[0], $parts[1], 'Process')
        }
    }
}

if (Test-Path -LiteralPath $pidFile) {
    $platformPid = [int](Get-Content -LiteralPath $pidFile -Raw)
    $running = $null -ne (Get-Process -Id $platformPid -ErrorAction SilentlyContinue)
}

try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8088/actuator/health" -TimeoutSec 3
    $healthy = $health.status -eq 'UP'
} catch {
    $healthy = $false
}

[pscustomobject]@{
    ProcessRunning = $running
    PID = $platformPid
    Health = if ($healthy) { 'UP' } else { 'DOWN' }
    LocalURL = 'http://127.0.0.1:8088'
    PublicURL = if ($env:LABEL_REVIEW_PUBLIC_URL) { $env:LABEL_REVIEW_PUBLIC_URL } else { 'not configured' }
} | Format-List

if (-not ($running -and $healthy)) { exit 1 }
