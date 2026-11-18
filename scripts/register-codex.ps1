# Run from PowerShell: .\scripts\register-codex.ps1
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $Root
try {
  Write-Host "Building Rust MCP binary..."
  cargo build --release -p task-mcp
  if ($LASTEXITCODE -ne 0) { throw "cargo build failed" }

  $Binary = Join-Path $Root "target\release\task-mcp.exe"
  if (!(Test-Path $Binary)) { throw "Cannot find $Binary" }

  # Can also configure with $env:PERSONAL_ISLAND_DB if desired; both
  # desktop and Codex need the SAME environment variable to share the DB.
  Write-Host "Registering MCP server in Codex: $Binary"
  codex mcp add personal-island -- $Binary
  if ($LASTEXITCODE -ne 0) { throw "codex mcp add failed" }
  codex mcp list
  Write-Host "MCP registered. Restart an existing Codex session to load it."
} finally { Pop-Location }
