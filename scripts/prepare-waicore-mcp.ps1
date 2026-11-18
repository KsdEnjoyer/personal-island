# Creates local credentials without printing their values. No OpenAI API key.
param([Parameter(Mandatory=$true)][string]$PublicBase)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$uri=[Uri]$PublicBase
if (!$uri.IsAbsoluteUri -or $uri.Scheme -ne 'https' -or $uri.UserInfo -or $uri.Query -or $uri.Fragment) { throw 'PublicBase must be your HTTPS gateway URL without credentials or query parameters' }
$privateDir=Join-Path $env:LOCALAPPDATA 'PersonalIsland/waicore-mcp'
$null=New-Item -ItemType Directory -Path $privateDir -Force
$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$null=& icacls.exe $privateDir /inheritance:r /grant:r ('*'+$sid+':(OI)(CI)(F)') '*S-1-5-18:(OI)(CI)(F)'
if ($LASTEXITCODE -ne 0) {throw 'Could not protect the local MCP credentials'}
$credentialsFile=Join-Path $privateDir 'owner.json'
if (!(Test-Path -LiteralPath $credentialsFile)) {
  $bytes=New-Object byte[] 24
  $random=[Security.Cryptography.RandomNumberGenerator]::Create()
  try {$random.GetBytes($bytes)} finally {$random.Dispose()}
  $password=[Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_')
  [IO.File]::WriteAllText($credentialsFile,(@{owner_password=$password;public_base=$PublicBase.TrimEnd('/')}|ConvertTo-Json))
  $password=$null
}
Write-Output 'Local MCP owner credentials are ready in a protected directory.'
