param([switch]$DisableAutostart)
$ErrorActionPreference='Stop'
$taskName='Personal Island - Waicore MCP'
$task=Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task) {
  if ($DisableAutostart) {$null=Disable-ScheduledTask -TaskName $taskName}
  Stop-ScheduledTask -TaskName $taskName
}
$stateFile=Join-Path $env:LOCALAPPDATA 'PersonalIsland/waicore-mcp/process.json'
if (Test-Path -LiteralPath $stateFile) {
  $state=Get-Content -LiteralPath $stateFile -Raw -Encoding UTF8 | ConvertFrom-Json
  $process=Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$state.pid)" -ErrorAction SilentlyContinue
  if ($process -and $process.ExecutablePath -eq $state.executable) {
    $started=(Get-Process -Id $process.ProcessId).StartTime.ToUniversalTime()
    if ([Math]::Abs(($started-[DateTime]::Parse($state.started_utc).ToUniversalTime()).TotalSeconds) -lt 2) {Stop-Process -Id $process.ProcessId}
  }
  Remove-Item -LiteralPath $stateFile
}
& (Join-Path $PSScriptRoot 'stop-mcp-http.ps1')
Write-Output 'Waicore MCP bridge stopped.'
