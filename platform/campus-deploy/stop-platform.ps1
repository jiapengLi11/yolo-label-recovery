$ErrorActionPreference = "Stop"

$pidFile = Join-Path $PSScriptRoot "platform.pid"
if (-not (Test-Path -LiteralPath $pidFile)) {
    Write-Output "平台当前未运行。"
    exit 0
}

$platformPid = [int](Get-Content -LiteralPath $pidFile -Raw)
$process = Get-Process -Id $platformPid -ErrorAction SilentlyContinue
if ($process) {
    $descendants = Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $platformPid }
    foreach ($child in $descendants) {
        Stop-Process -Id $child.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Stop-Process -Id $platformPid -Force
    $process.WaitForExit(30000)
}
Remove-Item -LiteralPath $pidFile -Force
Write-Output "平台已停止。"
