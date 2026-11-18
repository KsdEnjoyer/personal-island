param(
  [Parameter(Mandatory=$true)][ValidatePattern('^tunnel_[a-zA-Z0-9]+$')][string]$TunnelId,
  [string]$TunnelClient = 'tunnel-client',
  [string]$TunnelProfile = 'personal-island',
  [switch]$Initialize
)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$binary = Join-Path $projectRoot 'target/debug/task-mcp.exe'
if (!(Test-Path -LiteralPath $binary)) { throw 'Build task-mcp first: cargo build -p task-mcp' }
if (!(Get-Command $TunnelClient -ErrorAction SilentlyContinue)) { throw 'Install the official tunnel-client from Platform tunnel settings first; see docs/CHATGPT_MCP_RU.md' }
if (!$env:CONTROL_PLANE_API_KEY) { throw 'Set CONTROL_PLANE_API_KEY locally in this terminal. Do not paste API keys into chat.' }
if ($TunnelProfile -notmatch '^[a-zA-Z0-9_-]+$') { throw 'Invalid profile name' }
# The local MCP stdio transport does not expose an HTTP listener.
$command = '"' + $binary + '" --require-request-key'
if ($Initialize) {
  & $TunnelClient init --sample sample_mcp_stdio_local --profile $TunnelProfile --tunnel-id $TunnelId --mcp-command $command
  if ($LASTEXITCODE -ne 0) { throw 'Tunnel profile initialization failed' }
}
& $TunnelClient doctor --profile $TunnelProfile --explain
if ($LASTEXITCODE -ne 0) { throw 'Tunnel readiness check failed' }
& $TunnelClient run --profile $TunnelProfile
if ($LASTEXITCODE -ne 0) { throw 'OpenAI tunnel disconnected' }
