# Optional local desktop popup after an opt-in scheduled check.
# The SQLite inbox remains authoritative even if Windows hides this balloon.
param([Parameter(Mandatory=$true)][ValidateRange(1, 999)][int]$Count)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$balloon = New-Object System.Windows.Forms.NotifyIcon
try {
    $balloon.Icon = [System.Drawing.SystemIcons]::Information
    $balloon.Visible = $true
    $balloon.BalloonTipIcon = [System.Windows.Forms.ToolTipIcon]::Info
    $balloon.BalloonTipTitle = "Jobs-Finder"
    $balloon.BalloonTipText = "$Count new job-search notification(s). Open Jobs-Finder to review the alerts inbox."
    $balloon.ShowBalloonTip(10000)
    Start-Sleep -Seconds 10
}
finally {
    $balloon.Visible = $false
    $balloon.Dispose()
}
