param(
    [int]$ProjectId = 1,
    [Parameter(Mandatory = $true)]
    [string]$Workspace,
    [string]$Python = "python",
    [string]$MySqlBin = ""
)

$ErrorActionPreference = "Stop"

$deployRoot = $PSScriptRoot
$platformRoot = Split-Path -Parent $deployRoot
$configFile = Join-Path $deployRoot "campus.local.env"
$pidFile = Join-Path $deployRoot "platform.pid"
$exportTool = Join-Path $platformRoot "tools\export_review_decisions.py"
$workspaceRoot = (Resolve-Path -LiteralPath $Workspace).Path
$template = Join-Path $workspaceRoot "company_decisions_template.csv"
$policy = Join-Path $workspaceRoot "review_policy_used.yaml"
$remapManifest = Join-Path $workspaceRoot "heq_smoking_exact_remap_manifest.csv"
$pythonExe = if (Test-Path -LiteralPath $Python -PathType Leaf) {
    (Resolve-Path -LiteralPath $Python).Path
} else {
    (Get-Command $Python -ErrorAction Stop).Source
}
if ($MySqlBin) {
    $mysql = Join-Path $MySqlBin "mysql.exe"
    $mysqldump = Join-Path $MySqlBin "mysqldump.exe"
} else {
    $mysql = (Get-Command "mysql.exe" -ErrorAction Stop).Source
    $mysqldump = (Get-Command "mysqldump.exe" -ErrorAction Stop).Source
}

if (Test-Path -LiteralPath $pidFile) {
    $platformPid = [int](Get-Content -LiteralPath $pidFile -Raw)
    if (Get-Process -Id $platformPid -ErrorAction SilentlyContinue) {
        throw "Platform is still running. Stop it before final export to freeze review decisions."
    }
}

foreach ($required in @($configFile, $exportTool, $template, $policy, $remapManifest, $pythonExe, $mysql, $mysqldump)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required file was not found: $required"
    }
}

$config = @{}
Get-Content -LiteralPath $configFile -Encoding UTF8 | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith('#')) { return }
    $parts = $line.Split('=', 2)
    if ($parts.Count -ne 2) { throw "Invalid config line: $line" }
    $config[$parts[0]] = $parts[1]
}

foreach ($key in @("LABEL_REVIEW_DB_HOST", "LABEL_REVIEW_DB_PORT", "LABEL_REVIEW_DB_USER", "LABEL_REVIEW_DB_PASSWORD")) {
    if (-not $config[$key]) { throw "Missing required config: $key" }
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$finalRoot = Join-Path $workspaceRoot "final_exports"
$outputDir = Join-Path $finalRoot ("review_final_" + $stamp)
New-Item -ItemType Directory -Path $outputDir -Force | Out-Null

$dumpFile = Join-Path $outputDir "label_review_database.sql"
$dumpError = Join-Path $outputDir "mysqldump.stderr.log"
$previousPassword = $env:MYSQL_PWD
$env:MYSQL_PWD = $config["LABEL_REVIEW_DB_PASSWORD"]
try {
    $dumpProcess = Start-Process -FilePath $mysqldump `
        -ArgumentList @(
            "-h", $config["LABEL_REVIEW_DB_HOST"],
            "-P", $config["LABEL_REVIEW_DB_PORT"],
            "-u", $config["LABEL_REVIEW_DB_USER"],
            "--default-character-set=utf8mb4",
            "--single-transaction",
            "--no-tablespaces",
            "--routines",
            "--triggers",
            "label_review"
        ) `
        -RedirectStandardOutput $dumpFile `
        -RedirectStandardError $dumpError `
        -WindowStyle Hidden `
        -Wait `
        -PassThru
    if ($dumpProcess.ExitCode -ne 0) {
        throw "Database backup failed with exit code $($dumpProcess.ExitCode). Check $dumpError"
    }
    if (-not (Test-Path -LiteralPath $dumpFile -PathType Leaf) -or (Get-Item -LiteralPath $dumpFile).Length -eq 0) {
        throw "Database backup is empty: $dumpFile"
    }
} finally {
    $env:MYSQL_PWD = $previousPassword
}

$decisions = Join-Path $outputDir "company_decisions_final.csv"
& $pythonExe $exportTool `
    --template $template `
    --output $decisions `
    --env-file $configFile `
    --project-id $ProjectId `
    --mysql $mysql
if ($LASTEXITCODE -ne 0) {
    throw "Final decision export failed. The review is incomplete or inconsistent."
}

Copy-Item -LiteralPath $policy -Destination (Join-Path $outputDir "review_policy_used.yaml")
Copy-Item -LiteralPath $remapManifest -Destination (Join-Path $outputDir "heq_smoking_exact_remap_manifest.csv")
foreach ($name in @("summary.json", "summary.txt", "decision_matrix_coverage.csv")) {
    $source = Join-Path $workspaceRoot $name
    if (Test-Path -LiteralPath $source -PathType Leaf) {
        Copy-Item -LiteralPath $source -Destination $outputDir
    }
}

$hashFile = Join-Path $outputDir "SHA256SUMS.txt"
$hashLines = Get-ChildItem -LiteralPath $outputDir -File |
    Where-Object { $_.FullName -ne $hashFile } |
    Sort-Object Name |
    ForEach-Object {
        $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        "$hash *$($_.Name)"
    }
$hashLines | Set-Content -LiteralPath $hashFile -Encoding ASCII

Write-Output "Final review bundle created: $outputDir"
Write-Output "Decisions: $decisions"
Write-Output "Checksums: $hashFile"
