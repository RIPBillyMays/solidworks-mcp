# Registers the SOLIDWORKS MCP server in Claude Desktop's config.
#
# Why this script exists: Claude Desktop keeps claude_desktop_config.json in memory and
# rewrites the whole file on every session/connector change ("Config file written" in
# %LOCALAPPDATA%\Claude\Logs\main.log, often several times a minute). An edit made while
# Desktop is running is overwritten by its stale in-memory copy. Desktop does keep an
# mcpServers key it read at startup, so the fix is: edit only while Desktop is fully quit.
#
# Usage (plain PowerShell, NOT from inside Claude Desktop, after Quit from the tray icon):
#   powershell -ExecutionPolicy Bypass -File tools\compat\register_claude_desktop.ps1
#   ...add -Check to only report whether the entry is present.
param([switch]$Check)

$ErrorActionPreference = 'Stop'
$cfg = Join-Path $env:APPDATA 'Claude\claude_desktop_config.json'
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$exe = Join-Path $repo '.venv\Scripts\solidworks-mcp.exe'
$sandbox = Join-Path $repo 'sandbox'

$json = Get-Content $cfg -Raw | ConvertFrom-Json
$present = ($json.PSObject.Properties.Name -contains 'mcpServers') -and `
           ($json.mcpServers.PSObject.Properties.Name -contains 'solidworks')
if ($Check) { "solidworks entry present: $present"; exit ([int](-not $present)) }

# Desktop is an MSIX app; its processes run from ...\WindowsApps\Claude_*. Claude Code's
# CLI is also claude.exe but lives elsewhere, so filter by path.
$desktop = Get-Process claude -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like '*\WindowsApps\Claude_*' }
if ($desktop) {
    Write-Error 'Claude Desktop is still running. Right-click the tray icon > Quit, wait 5 s, then rerun.'
}
if (-not (Test-Path $exe)) { Write-Error "Server exe not found: $exe" }

Copy-Item $cfg "$cfg.bak-$(Get-Date -Format yyyy-MM-dd-HHmmss)"
$entry = [pscustomobject]@{
    command = $exe
    args    = @()
    env     = [pscustomobject]@{ SW_MCP_OUTPUT_ROOT = $sandbox }
}
if ($json.PSObject.Properties.Name -notcontains 'mcpServers') {
    $json | Add-Member -NotePropertyName mcpServers -NotePropertyValue ([pscustomobject]@{})
}
$json.mcpServers | Add-Member -NotePropertyName solidworks -NotePropertyValue $entry -Force

# UTF-8 without BOM: Desktop's JSON parser rejects a BOM.
$text = $json | ConvertTo-Json -Depth 50
[IO.File]::WriteAllText($cfg, $text, (New-Object Text.UTF8Encoding $false))
$null = Get-Content $cfg -Raw | ConvertFrom-Json   # validate round-trip
"Registered. Now start Claude Desktop, then rerun with -Check after it has been open a minute."
