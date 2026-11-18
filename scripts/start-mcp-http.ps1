param(
  [ValidateRange(1024,65535)][int]$Port = 18741,
  [string]$Database = '',
  [switch]$Build
)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$binary = Join-Path $projectRoot 'target/debug/task-mcp-http.exe'
if ($Build -or !(Test-Path -LiteralPath $binary)) {
  Push-Location $projectRoot
  try {
    $rustBin = Join-Path $env:USERPROFILE '.cargo/bin'
    $originalPath = $env:Path
    try { $env:Path = "$rustBin;$originalPath"; & cargo build -p task-mcp --features http --bins }
    finally { $env:Path = $originalPath }
    if ($LASTEXITCODE -ne 0) { throw 'MCP build failed' }
  } finally { Pop-Location }
}
$privateDir = Join-Path $env:LOCALAPPDATA 'PersonalIsland'
$null = New-Item -ItemType Directory -Path $privateDir -Force
$tokenFile = Join-Path $privateDir 'mcp-bridge.token'
if (!(Test-Path -LiteralPath $tokenFile)) { $null = New-Item -ItemType File -Path $tokenFile }
$ownerSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$null = & icacls.exe $tokenFile /inheritance:r /grant:r ('*'+$ownerSid+':(F)') '*S-1-5-18:(F)'
if ($LASTEXITCODE -ne 0) { throw 'Could not restrict MCP token permissions' }
if ((Get-Item -LiteralPath $tokenFile).Length -eq 0) {
  $bytes = New-Object byte[] 32
  $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
  try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
  $token = [BitConverter]::ToString($bytes).Replace('-','').ToLowerInvariant()
  [IO.File]::WriteAllText($tokenFile,$token,(New-Object Text.UTF8Encoding($false)))
}
$listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
if ($listeners.Count -gt 0) {
  $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$($listeners[0].OwningProcess)"
  if ($owner.ExecutablePath -eq $binary) {
    if ($Database) { throw 'Stop the existing bridge before selecting a different database' }
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -Headers @{ Authorization = ('Bearer '+[IO.File]::ReadAllText($tokenFile).Trim()) } -TimeoutSec 2
    if ($health.status -ne 'ready') { throw 'Existing MCP bridge is not ready' }
    Write-Output "MCP bridge is already running (PID $($owner.ProcessId))."; return
  }
  throw "Port $Port is used by another application"
}
$names = @('PERSONAL_ISLAND_MCP_TOKEN','PERSONAL_ISLAND_MCP_TOKEN_FILE','PERSONAL_ISLAND_MCP_BIND','PERSONAL_ISLAND_DB')
$previous = @{}
foreach ($name in $names) { $previous[$name] = [Environment]::GetEnvironmentVariable($name,'Process') }
try {
  Remove-Item Env:PERSONAL_ISLAND_MCP_TOKEN -ErrorAction SilentlyContinue
  $env:PERSONAL_ISLAND_MCP_TOKEN_FILE = $tokenFile
  $env:PERSONAL_ISLAND_MCP_BIND = "127.0.0.1:$Port"
  if ($Database) { $env:PERSONAL_ISLAND_DB = [IO.Path]::GetFullPath($Database) }
  $bridgeProcess = Start-Process -FilePath $binary -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $privateDir "mcp-http-$Port.stdout.log") `
    -RedirectStandardError (Join-Path $privateDir "mcp-http-$Port.stderr.log")
} finally {
  foreach ($name in $names) { [Environment]::SetEnvironmentVariable($name,$previous[$name],'Process') }
}
$deadline = [DateTime]::UtcNow.AddSeconds(20)
$health = $null
$token = [IO.File]::ReadAllText($tokenFile).Trim()
while ([DateTime]::UtcNow -lt $deadline) {
  $bridgeProcess.Refresh()
  if ($bridgeProcess.HasExited) { throw "MCP exited. See $privateDir/mcp-http-$Port.stderr.log" }
  try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 1
    if ($health.status -eq 'ready') { break }
  } catch { Start-Sleep -Milliseconds 200 }
}
if (!$health -or $health.status -ne 'ready') { Stop-Process -Id $bridgeProcess.Id; throw 'MCP readiness timed out' }
[IO.File]::WriteAllText((Join-Path $privateDir "mcp-http-$Port.pid"),[string]$bridgeProcess.Id)
Write-Output "Private MCP is ready at http://127.0.0.1:$Port/mcp (PID $($bridgeProcess.Id)). Token is stored in a protected local file."
