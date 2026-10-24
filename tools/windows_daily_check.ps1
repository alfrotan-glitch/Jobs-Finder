# Jobs-Finder: opt-in daily check using the CURRENT signed-in Windows user.
# It never runs as SYSTEM and never sends an application to an employer.
param([Parameter(Mandatory=$true)][ValidateSet("enable", "disable", "status")][string]$Action)
$ErrorActionPreference = "Stop"
$taskName = "Jobs-Finder Daily Match Check"
$project = Split-Path -Parent $PSScriptRoot
$python = Join-Path $project ".venv\Scripts\python.exe"
$entry = Join-Path $project "main.py"

function Assert-OwnScheduledTask($task) {
    # Prevent one local Jobs-Finder installation from hijacking another.
    if ($null -eq $task) { return }
    if ($null -eq $task.Actions -or $task.Actions.Count -ne 1) {
        throw "The existing daily check belongs to another Jobs-Finder checkout."
    }
    $expectedPython = [System.IO.Path]::GetFullPath($python)
    $actualPython = [System.IO.Path]::GetFullPath($task.Actions[0].Execute.Trim('"'))
    $expectedWorking = [System.IO.Path]::GetFullPath($project)
    $actualWorking = [System.IO.Path]::GetFullPath($task.Actions[0].WorkingDirectory)
    $expectedArguments = '"' + $entry + '" monitor-once'
    if (-not [string]::Equals($expectedPython, $actualPython, [System.StringComparison]::OrdinalIgnoreCase) -or
        -not [string]::Equals($expectedWorking, $actualWorking, [System.StringComparison]::OrdinalIgnoreCase) -or
        -not [string]::Equals($expectedArguments, $task.Actions[0].Arguments, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "The existing daily check belongs to another Jobs-Finder checkout."
    }
}
if ($Action -eq "status") {
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($null -eq $existing) { Write-Output "DISABLED"; exit 0 }
    Assert-OwnScheduledTask $existing
    if ($existing.Settings.Enabled -eq $false) { Write-Output "DISABLED"; exit 0 }
    Write-Output "ENABLED"
    exit 0
}
if ($Action -eq "disable") {
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($null -ne $existing) {
        Assert-OwnScheduledTask $existing
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }
    Write-Output "DISABLED"
    exit 0
}

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
Assert-OwnScheduledTask $existing

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
