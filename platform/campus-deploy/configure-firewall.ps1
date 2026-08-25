param(
    [string]$RemoteAddress = "LocalSubnet"
)

$ErrorActionPreference = "Stop"

$ruleName = "LabelReview-Campus-8088"
$existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if ($existing) {
    $existing | Remove-NetFirewallRule
}

New-NetFirewallRule `
    -DisplayName $ruleName `
    -Direction Inbound `
    -Action Allow `
    -Protocol TCP `
    -LocalPort 8088 `
    -RemoteAddress $RemoteAddress `
    -Profile Any | Out-Null

Write-Output "Firewall rule $ruleName is ready for $RemoteAddress."
