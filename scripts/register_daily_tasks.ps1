# Registers two Windows scheduled tasks for the job search agent (run once in PowerShell):
#   JobAgent-Morning    07:30 daily  python -m src.daily          (search, tailor, sync, auto-apply)
#   JobAgent-Afternoon  13:30 daily  python -m src.daily --apply  (apply to Claude's morning shortlist)
#   JobAgent-ResumeUpload 08:30 Mon-Fri  python -m src.apply.linkedin_resume  (re-upload resume to LinkedIn)
# Usage:  powershell -ExecutionPolicy Bypass -File E:\job_search_agent\scripts\register_daily_tasks.ps1
# Remove: Unregister-ScheduledTask -TaskName JobAgent-Morning,JobAgent-Afternoon,JobAgent-ResumeUpload -Confirm:$false
param(
    [string]$Python = (Get-Command python -ErrorAction Stop).Source,
    [string]$Root = (Split-Path -Parent $PSScriptRoot)
)

# Runs only while you are logged in, so the visible browser and saved sign-ins work.
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

$tasks = @(
    @{ Name = "JobAgent-Morning";   At = "07:30"; Args = "-m src.daily" },
    @{ Name = "JobAgent-Afternoon"; At = "13:30"; Args = "-m src.daily --apply" },
    @{ Name = "JobAgent-ResumeUpload"; At = "08:30"; Args = "-m src.apply.linkedin_resume"; Weekdays = $true }
)
foreach ($task in $tasks) {
    $action = New-ScheduledTaskAction -Execute $Python -Argument $task.Args -WorkingDirectory $Root
    if ($task.Weekdays) {
        $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $task.At
    } else {
        $trigger = New-ScheduledTaskTrigger -Daily -At $task.At
    }
    Register-ScheduledTask -TaskName $task.Name -Action $action -Trigger $trigger -Principal $principal `
        -Settings $settings -Force | Out-Null
    Write-Host "Registered $($task.Name) at $($task.At) -> $Python $($task.Args)"
}
