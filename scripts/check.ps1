# Run from the project root: .\scripts\check.ps1
$ErrorActionPreference = 'Stop'
Push-Location (Resolve-Path (Join-Path $PSScriptRoot '..'))
try {
  cargo fmt --all -- --check
  if ($LASTEXITCODE -ne 0) { throw 'cargo fmt failed' }
  cargo test -p task-core
  if ($LASTEXITCODE -ne 0) { throw 'task-core tests failed' }
  cargo check -p task-mcp
  if ($LASTEXITCODE -ne 0) { throw 'task-mcp check failed' }
  if ($env:OS -eq 'Windows_NT') {
    cargo test -p personal-island-desktop --lib
    if ($LASTEXITCODE -ne 0) { throw 'desktop clipboard tests failed' }
  }
  Push-Location 'apps/desktop'
  try {
    npm.cmd run check
    if ($LASTEXITCODE -ne 0) { throw 'Svelte type check failed' }
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Svelte build failed' }
  } finally { Pop-Location }
  Write-Host 'Core, MCP and frontend checks passed. Full Tauri bundle must be built on Windows.'
} finally { Pop-Location }
