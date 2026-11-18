param([string]$RepositoryRoot = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $RepositoryRoot).Path
$exe = Join-Path $root 'target\debug\personal-island-desktop.exe'
if (!(Test-Path -LiteralPath $exe)) { $exe = Join-Path $root 'target\release\personal-island-desktop.exe' }
if (!(Test-Path -LiteralPath $exe)) { throw "Build the desktop application first: $exe" }
$desktop = [Environment]::GetFolderPath('Desktop')
$path = Join-Path $desktop 'Personal Island.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($path)
$shortcut.TargetPath = $exe
$shortcut.Arguments = '--show'
$shortcut.WorkingDirectory = $root
$shortcut.IconLocation = (Join-Path $root 'apps\desktop\src-tauri\icons\icon.ico') + ',0'
$shortcut.Description = 'Personal Island'
$shortcut.Save()
Write-Output $path
