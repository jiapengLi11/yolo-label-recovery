$ErrorActionPreference = "Stop"

$deployRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$platformRoot = Split-Path -Parent $deployRoot
$configFile = Join-Path $deployRoot "campus.local.env"
$pidFile = Join-Path $deployRoot "platform.pid"
$logDir = Join-Path $deployRoot "logs"
$jar = Join-Path $platformRoot "backend\target\label-review-platform-1.1.0.jar"

if (-not (Test-Path -LiteralPath $configFile)) {
    throw "缺少本地配置：$configFile。请按 README.md 创建本机配置。"
}
if (-not (Test-Path -LiteralPath $jar)) {
    throw "缺少后端 JAR：$jar。请先按 README.md 构建 standalone JAR。"
}
if (Test-Path -LiteralPath $pidFile) {
    $existingPid = [int](Get-Content -LiteralPath $pidFile -Raw)
    if (Get-Process -Id $existingPid -ErrorAction SilentlyContinue) {
        Write-Output "平台已经运行，PID=$existingPid"
        exit 0
    }
    Remove-Item -LiteralPath $pidFile -Force
}

Get-Content -LiteralPath $configFile | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith('#')) { return }
    $parts = $line.Split('=', 2)
    if ($parts.Count -ne 2) { throw "无效配置行：$line" }
    [Environment]::SetEnvironmentVariable($parts[0], $parts[1], 'Process')
}

function Test-TcpPort([string]$HostName, [int]$Port, [int]$TimeoutMs = 2000) {
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $result = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $result.AsyncWaitHandle.WaitOne($TimeoutMs)) { return $false }
        $client.EndConnect($result)
        return $true
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

$dbHost = $env:LABEL_REVIEW_DB_HOST
$dbPort = if ($env:LABEL_REVIEW_DB_PORT) { [int]$env:LABEL_REVIEW_DB_PORT } else { 3306 }
if ($dbHost -and -not (Test-TcpPort $dbHost $dbPort)) {
    $vmRun = $env:LABEL_REVIEW_VM_RUN
    $vmx = $env:LABEL_REVIEW_VM_VMX
    if (-not (Test-Path -LiteralPath $vmRun) -or -not (Test-Path -LiteralPath $vmx)) {
        throw "数据库不可达，且未找到 VMware 启动文件。请检查 LABEL_REVIEW_VM_RUN 和 LABEL_REVIEW_VM_VMX。"
    }
    Write-Output "数据库未运行，正在启动 Ubuntu 虚拟机..."
    $vmProcess = Start-Process -FilePath $vmRun `
        -ArgumentList @("-T", "ws", "start", ('"{0}"' -f $vmx), "nogui") `
        -WindowStyle Hidden `
        -Wait `
        -PassThru
    if ($vmProcess.ExitCode -ne 0 -and $vmProcess.ExitCode -ne 1) {
        throw "VMware 启动失败，退出码=$($vmProcess.ExitCode)"
    }
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        if (Test-TcpPort $dbHost $dbPort) { break }
        Start-Sleep -Seconds 2
    }
    if (-not (Test-TcpPort $dbHost $dbPort)) {
        throw "Ubuntu 已启动，但 MySQL 在 120 秒内仍不可达：${dbHost}:$dbPort"
    }
}

New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$stdout = Join-Path $logDir "platform.out.log"
$stderr = Join-Path $logDir "platform.err.log"
$java = if ($env:LABEL_REVIEW_JAVA) { $env:LABEL_REVIEW_JAVA } else { "java" }
if ($java -ne "java" -and -not (Test-Path -LiteralPath $java)) {
    throw "找不到 Java：$java"
}
$process = Start-Process -FilePath $java `
    -ArgumentList @("-XX:MaxRAMPercentage=60.0", "-jar", $jar, "--server.address=0.0.0.0", "--server.port=8088") `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -WindowStyle Hidden `
    -PassThru
$process.Id | Set-Content -LiteralPath $pidFile -Encoding ASCII

for ($attempt = 1; $attempt -le 60; $attempt++) {
    Start-Sleep -Seconds 2
    if (-not (Get-Process -Id $process.Id -ErrorAction SilentlyContinue)) {
        throw "平台进程提前退出，请检查 $stderr 和 $stdout"
    }
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:8088/actuator/health" -TimeoutSec 3
        if ($health.status -eq 'UP') {
            $publicUrl = if ($env:LABEL_REVIEW_PUBLIC_URL) { $env:LABEL_REVIEW_PUBLIC_URL } else { "http://127.0.0.1:8088" }
            Write-Output "平台启动成功：$publicUrl（PID=$($process.Id)）"
            exit 0
        }
    } catch {
        # Spring Boot and Flyway may need a few seconds on first startup.
    }
}

throw "平台未在 120 秒内就绪，请检查 $stderr 和 $stdout"
