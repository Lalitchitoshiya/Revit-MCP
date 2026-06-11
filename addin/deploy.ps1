<#
.SYNOPSIS
  Build the Revit MCP add-in and shadow-deploy it so Revit never locks the build output.

.DESCRIPTION
  Revit locks whatever assembly its manifest points at, for the whole session.
  To keep `dotnet build` always working, we point the manifest at a COPY in
  %LOCALAPPDATA%\RevitMCP\addin and load from there. Then:
    - `dotnet build -c Release` (to bin\Release) succeeds even while Revit is open;
    - this script copies the fresh DLL to the deploy folder (needs Revit CLOSED,
      because Revit locks the deploy copy while running) and writes the manifest.

  Typical loop after the first run:
    1. (edit add-in code)
    2. close Revit
    3. .\deploy.ps1
    4. open Revit  ->  new code is live

.PARAMETER RevitApiDir
  Folder containing RevitAPI.dll / RevitAPIUI.dll.

.PARAMETER RevitVersion
  Revit major version (Addins subfolder + target runtime).
#>
param(
  [string]$RevitApiDir = "C:\Program Files\Autodesk\Revit 2027",
  [string]$RevitVersion = "2027",
  [string]$TargetFramework = "net10.0-windows"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "==> Building (Release, $TargetFramework)..." -ForegroundColor Cyan
dotnet build "$root\RevitMCP.Addin.csproj" -c Release `
  -p:RevitApiDir=$RevitApiDir -p:TargetFramework=$TargetFramework | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Build failed." }

$builtDll = Join-Path $root "bin\Release\RevitMCP.Addin.dll"
if (-not (Test-Path $builtDll)) { throw "Built DLL not found at $builtDll" }

$deployDir = Join-Path $env:LOCALAPPDATA "RevitMCP\addin"
$deployDll = Join-Path $deployDir "RevitMCP.Addin.dll"
New-Item -ItemType Directory -Force -Path $deployDir | Out-Null

if (Get-Process -Name Revit -ErrorAction SilentlyContinue) {
  Write-Warning "Revit is running and locks the deploy copy. Close Revit, then re-run .\deploy.ps1."
  Write-Host "(The build itself succeeded; only the deploy copy is blocked.)" -ForegroundColor Yellow
  exit 1
}

Write-Host "==> Deploying to $deployDll" -ForegroundColor Cyan
Copy-Item $builtDll $deployDll -Force

$addinsDir = Join-Path $env:APPDATA "Autodesk\Revit\Addins\$RevitVersion"
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
$dest = Join-Path $addinsDir "RevitMCP.addin"
$manifest | Set-Content -Encoding utf8 $dest

Write-Host "==> Done. Manifest -> $dest" -ForegroundColor Green
Write-Host "    Start Revit to load the updated add-in." -ForegroundColor Green
