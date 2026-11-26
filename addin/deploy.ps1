<#
.SYNOPSIS
  DEVELOPER deploy: build the add-in for one Revit version and shadow-deploy it.
  (End users install the MSI built by installer\build.ps1 instead.)

.DESCRIPTION
  Revit locks whatever assembly its manifest points at, for the whole session.
  To keep `dotnet build` always working, we point the manifest at a COPY in
  %LOCALAPPDATA%\RevitMCP\addin and load from there. Then:
    - `dotnet build -c Release` (to bin\Release\<version>) succeeds even while Revit is open;
    - this script copies the fresh DLL to the deploy folder (needs Revit CLOSED,
      because Revit locks the deploy copy while running) and writes the manifest.

  Typical loop after the first run:
    1. (edit add-in code)
    2. close Revit
    3. .\deploy.ps1
    4. open Revit  ->  new code is live

  Do not keep this developer manifest AND the installed product (MSI / .bundle)
  at the same time: both register the same add-in id and Revit reports a
  duplicate. Use `.\deploy.ps1 -Remove` before installing the MSI.

.PARAMETER RevitVersion
  Revit major version (2025, 2026, 2027).

.PARAMETER Remove
  Remove the developer manifest and deploy copy instead of deploying.
#>
param(
  [string]$RevitVersion = "2027",
  [switch]$Remove
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$deployDir = Join-Path $env:LOCALAPPDATA "RevitMCP\addin"
$deployDll = Join-Path $deployDir "RevitMCP.Addin.dll"
$addinsDir = Join-Path $env:APPDATA "Autodesk\Revit\Addins\$RevitVersion"
$dest = Join-Path $addinsDir "RevitMCP.addin"

if (Get-Process -Name Revit -ErrorAction SilentlyContinue) {
  $revitRunning = $true
}

if ($Remove) {
  if ($revitRunning) { Write-Warning "Close Revit first (it locks the deploy copy)."; exit 1 }
  if (Test-Path $dest) { Remove-Item $dest -Force; Write-Host "Removed $dest" }
  if (Test-Path $deployDll) { Remove-Item $deployDll -Force; Write-Host "Removed $deployDll" }
  Write-Host "==> Developer deploy removed for Revit $RevitVersion." -ForegroundColor Green
  exit 0
}

Write-Host "==> Building (Release, Revit $RevitVersion)..." -ForegroundColor Cyan
dotnet build "$root\RevitMCP.Addin.csproj" -c Release -p:RevitVersion=$RevitVersion | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Build failed." }

$builtDll = Join-Path $root "bin\Release\$RevitVersion\RevitMCP.Addin.dll"
if (-not (Test-Path $builtDll)) { throw "Built DLL not found at $builtDll" }

New-Item -ItemType Directory -Force -Path $deployDir | Out-Null

if ($revitRunning) {
  Write-Warning "Revit is running and locks the deploy copy. Close Revit, then re-run .\deploy.ps1."
  Write-Host "(The build itself succeeded; only the deploy copy is blocked.)" -ForegroundColor Yellow
  exit 1
}

$bundle = Join-Path $env:APPDATA "Autodesk\ApplicationPlugins\RevitMCP.bundle"
if (Test-Path $bundle) {
  Write-Warning "The installed product is present ($bundle). Uninstall it first (Apps & features > Revit MCP) or Revit will report a duplicate add-in."
  exit 1
}

Write-Host "==> Deploying to $deployDll" -ForegroundColor Cyan
Copy-Item $builtDll $deployDll -Force

New-Item -ItemType Directory -Force -Path $addinsDir | Out-Null
$manifest = @"
<?xml version="1.0" encoding="utf-8"?>
<RevitAddIns>
  <AddIn Type="Application">
    <Name>RevitMCP</Name>
    <Assembly>$deployDll</Assembly>
    <FullClassName>RevitMCP.Addin.RevitMcpApp</FullClassName>
    <ClientId>8f1c9d2e-4b3a-4c6e-9a7d-2f0b5e1c7a44</ClientId>
    <VendorId>RVTMCP</VendorId>
    <VendorDescription>Revit MCP bridge</VendorDescription>
  </AddIn>
</RevitAddIns>
"@
$manifest | Set-Content -Encoding utf8 $dest

Write-Host "==> Done. Manifest -> $dest" -ForegroundColor Green
Write-Host "    Start Revit to load the updated add-in." -ForegroundColor Green
