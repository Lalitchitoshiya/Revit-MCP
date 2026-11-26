<#
.SYNOPSIS
  Read-only check of a Revit MCP installation (clean-machine / VM testing, support).

.DESCRIPTION
  After installing the MSI:        powershell -ExecutionPolicy Bypass -File verify-install.ps1
  After uninstalling it:           powershell -ExecutionPolicy Bypass -File verify-install.ps1 -Uninstalled

  Installed mode checks: bundle files, Apps & features entry, which installed
  Revit versions the bundle covers, conflicting developer manifests, then runs
  `revit-mcp-server doctor` (session, live add-in health, Claude registration,
  access policy, audit chain). Start Revit with a project open first to get the
  live add-in check.

  Uninstalled mode checks that the bundle, the Apps & features entry and the
  Claude registrations are gone (the audit log is intentionally kept).

  Changes nothing. Exit code = number of failed checks.
#>
param([switch]$Uninstalled)

$fails = 0
function Check([bool]$ok, [string]$what) {
  if ($ok) { Write-Host "  PASS $what" -ForegroundColor Green }
  else { Write-Host "  FAIL $what" -ForegroundColor Red; $script:fails++ }
}
function Info([string]$what) { Write-Host "  info $what" -ForegroundColor Gray }

$bundle = Join-Path $env:APPDATA "Autodesk\ApplicationPlugins\RevitMCP.bundle"
$exe = Join-Path $bundle "Contents\Server\revit-mcp-server.exe"
$arp = Get-ChildItem "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall" -ErrorAction SilentlyContinue |
  ForEach-Object { Get-ItemProperty $_.PSPath } | Where-Object { $_.DisplayName -eq "Revit MCP" }
$desktopConfigs = @(Join-Path $env:APPDATA "Claude\claude_desktop_config.json") +
  @(Get-ChildItem (Join-Path $env:LOCALAPPDATA "Packages") -Directory -Filter "Claude_*" -ErrorAction SilentlyContinue |
    ForEach-Object { Join-Path $_.FullName "LocalCache\Roaming\Claude\claude_desktop_config.json" }) +
  @(Get-ChildItem (Join-Path $env:LOCALAPPDATA "Claude-Data") -Directory -ErrorAction SilentlyContinue |
    ForEach-Object { Join-Path $_.FullName "claude_desktop_config.json" })
function Registered-InDesktop {
  foreach ($c in $desktopConfigs) {
    if ((Test-Path $c) -and ((Get-Content $c -Raw) -match '"revit-mcp"\s*:')) { return $c }
  }
  return $null
}

if ($Uninstalled) {
  Write-Host "Revit MCP uninstall check" -ForegroundColor Cyan
  Check (-not (Test-Path $bundle)) "bundle folder removed ($bundle)"
  Check (-not $arp) "Apps & features entry removed"
  Check (-not (Test-Path "HKCU:\Software\RevitMCP")) "HKCU\Software\RevitMCP removed"
  $reg = Registered-InDesktop
  Check (-not $reg) "Claude Desktop entry removed$(if ($reg) { " (still in $reg)" })"
  $claude = Get-Command claude -ErrorAction SilentlyContinue
  if ($claude) {
    & $claude.Source mcp get revit-mcp *> $null
    Check ($LASTEXITCODE -ne 0) "Claude Code entry removed"
  }
  $audit = Join-Path $env:LOCALAPPDATA "RevitMCP\audit\audit.jsonl"
  if (Test-Path $audit) { Info "audit log kept on purpose: $audit" }
  Write-Host "`n$fails failed check(s)"; exit $fails
}

Write-Host "Revit MCP install check" -ForegroundColor Cyan
Check (Test-Path (Join-Path $bundle "PackageContents.xml")) "bundle installed ($bundle)"
Check (Test-Path $exe) "MCP server present"
if (Test-Path $exe) { Info ((& $exe --version) -join " ") }
Check ([bool]$arp) "Apps & features entry$(if ($arp) { ": $($arp.DisplayName) $($arp.DisplayVersion) by $($arp.Publisher)" })"

$supported = @()
if (Test-Path (Join-Path $bundle "PackageContents.xml")) {
  [xml]$pc = Get-Content (Join-Path $bundle "PackageContents.xml")
  $supported = @($pc.ApplicationPackage.Components | ForEach-Object { $_.RuntimeRequirements.SeriesMin.TrimStart('R') })
  foreach ($v in $supported) {
    Check (Test-Path (Join-Path $bundle "Contents\$v\RevitMCP.Addin.dll")) "add-in build for Revit $v"
  }
}
$revits = Get-ChildItem "$env:ProgramFiles\Autodesk" -Directory -Filter "Revit 20*" -ErrorAction SilentlyContinue |
  Where-Object { Test-Path (Join-Path $_.FullName "Revit.exe") } | ForEach-Object { $_.Name.Substring(6) }
if (-not $revits) { Info "no Revit found under $env:ProgramFiles\Autodesk" }
foreach ($r in $revits) {
  if ($supported -contains $r) { Info "Revit $r installed: covered" } else { Info "Revit $r installed: NOT supported by this build" }
}

foreach ($root in @("$env:APPDATA\Autodesk\Revit\Addins", "$env:ProgramData\Autodesk\Revit\Addins")) {
  Get-ChildItem $root -Recurse -Filter "RevitMCP.addin" -ErrorAction SilentlyContinue | ForEach-Object {
    Check $false "no conflicting developer manifest (found $($_.FullName); remove it: addin\deploy.ps1 -Remove)"
  }
}

if (Test-Path $exe) {
  Write-Host "`nrevit-mcp-server doctor:" -ForegroundColor Cyan
  & $exe doctor
  if ($LASTEXITCODE -ne 0) { Info "Revit not reachable: start Revit with a project open for the live add-in check" }
}
Write-Host "`n$fails failed check(s)"; exit $fails
