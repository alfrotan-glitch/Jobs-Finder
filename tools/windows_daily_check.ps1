# Jobs-Finder: opt-in daily check using the CURRENT signed-in Windows user.
# It never runs as SYSTEM and never sends an application to an employer.
param([Parameter(Mandatory=$true)][ValidateSet("enable", "disable", "status")][string]$Action)
$ErrorActionPreference = "Stop"
$taskName = "Jobs-Finder Daily Match Check"
if ($Action -eq "status") {
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($null -eq $existing) { Write-Output "DISABLED"; exit 0 }
    if ($existing.Settings.Enabled -eq $false) { Write-Output "DISABLED"; exit 0 }
    Write-Output "ENABLED"
    exit 0
}
if ($Action -eq "disable") {
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($null -ne $existing) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }
    Write-Output "DISABLED"
    exit 0
}

$project = Split-Path -Parent $PSScriptRoot
$python = Join-Path $project ".venv\Scripts\python.exe"
$entry = Join-Path $project "main.py"
if (!(Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "The project Python environment is missing. Start run_jobs_finder.bat once before enabling the daily check."
}
if (!(Test-Path -LiteralPath $entry -PathType Leaf)) {
    throw "The Jobs-Finder program is missing. Please restore the project folder."
}

$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$jobAction = New-ScheduledTaskAction -Execute $python -Argument ('"' + $entry + '" monitor-once') -WorkingDirectory $project
$trigger = New-ScheduledTaskTrigger -Daily -At 9:00AM
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $jobAction -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Write-Output "ENABLED"
