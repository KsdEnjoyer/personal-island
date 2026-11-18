param([ValidateRange(1024,65535)][int]$Port = 18741)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$pidFile = Join-Path $env:LOCALAPPDATA "PersonalIsland/mcp-http-$Port.pid"
if (!(Test-Path -LiteralPath $pidFile)) { Write-Output 'No managed MCP process.'; return }
$bridgeProcessId = [int]([IO.File]::ReadAllText($pidFile))
$bridgeProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$bridgeProcessId"
if ($bridgeProcess) {
  if ($bridgeProcess.ExecutablePath -ne (Join-Path $projectRoot 'target/debug/task-mcp-http.exe')) { throw 'PID belongs to another application; nothing was stopped' }
  $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.OwningProcess -eq $bridgeProcessId }
  if (!$listener) { throw 'Managed PID is not listening on the expected MCP port; nothing was stopped' }
  Stop-Process -Id $bridgeProcessId
}
Remove-Item -LiteralPath $pidFile
Write-Output 'Private MCP stopped.'
