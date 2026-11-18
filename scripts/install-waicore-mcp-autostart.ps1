$ErrorActionPreference='Stop'
$projectRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$runner=Join-Path $PSScriptRoot 'run-waicore-mcp.py'
$pythonw=(Get-Command pythonw.exe -ErrorAction Stop).Source
$action=New-ScheduledTaskAction -Execute $pythonw -Argument ('"'+$runner+'"') -WorkingDirectory $projectRoot
$user=[Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal=New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$trigger=New-ScheduledTaskTrigger -AtLogOn -User $user
$options=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
$null=Register-ScheduledTask -TaskName 'Personal Island - Waicore MCP' -Action $action -Principal $principal -Trigger $trigger -Settings $options -Force
Start-ScheduledTask -TaskName 'Personal Island - Waicore MCP'
Write-Output 'Private Waicore MCP bridge is registered for Windows login and started.'
