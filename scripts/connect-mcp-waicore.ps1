param(
  [Parameter(Mandatory=$true)][string]$VpsAddress,
  [string]$UserName = 'islandrelay',
  [string]$IdentityFile = (Join-Path $env:USERPROFILE '.ssh/personal_island_relay_ed25519'),
  [ValidateRange(1024,65535)][int]$LocalPort = 18741,
  [ValidateRange(1024,65535)][int]$RemotePort = 18741
)
$ErrorActionPreference = 'Stop'
if ($VpsAddress -notmatch '^[a-zA-Z0-9.:-]+$' -or $VpsAddress.StartsWith('-')) { throw 'Invalid VPS address' }
if ($UserName -notmatch '^[a-z_][a-z0-9_-]*$') { throw 'Invalid SSH user' }
if (!(Test-Path -LiteralPath $IdentityFile -PathType Leaf)) { throw 'SSH key file was not found' }
$connection = @('-i',$IdentityFile,'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=10')
$target = "${UserName}@${VpsAddress}"
# Configure GatewayPorts no and the restricted relay account on your VPS first.
# This account deliberately has no administrative shell.
Write-Output "Private VPS relay: 127.0.0.1:$RemotePort -> PC 127.0.0.1:$LocalPort. Keep this process running; Ctrl+C disconnects it."
& ssh @connection -N -T -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=3 `
  -R "127.0.0.1:${RemotePort}:127.0.0.1:${LocalPort}" $target
if ($LASTEXITCODE -ne 0) { throw 'Private SSH tunnel disconnected' }
