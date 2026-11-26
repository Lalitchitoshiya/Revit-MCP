<#
.SYNOPSIS
  Authenticode-sign files with signtool (called by build.ps1; safe to run alone).

.DESCRIPTION
  Signing is configured with environment variables, so no secret is ever stored in the repo:

    REVITMCP_SIGN_THUMBPRINT   SHA-1 thumbprint of a code-signing cert in the
                               CurrentUser\My store (also works for EV/HSM-backed certs)
    -- or --
    REVITMCP_SIGN_PFX          path to a .pfx file
    REVITMCP_SIGN_PFX_PASSWORD its password

    REVITMCP_SIGN_TIMESTAMP    RFC 3161 timestamp URL (default http://timestamp.digicert.com)

  With none set, prints a warning and exits 0 (the build stays UNSIGNED).
  signtool.exe comes with the Windows SDK; set REVITMCP_SIGNTOOL to its path if
  it is not found automatically.

.PARAMETER Files
  Files to sign (dll, exe, msi).

.PARAMETER Require
  Fail instead of warning when signing isn't configured (use for release builds).
#>
param(
  [Parameter(Mandatory = $true)][string[]]$Files,
  [switch]$Require
)

$ErrorActionPreference = "Stop"

$thumb = $env:REVITMCP_SIGN_THUMBPRINT
$pfx = $env:REVITMCP_SIGN_PFX
if (-not $thumb -and -not $pfx) {
  $msg = "Code signing is not configured (REVITMCP_SIGN_THUMBPRINT or REVITMCP_SIGN_PFX): files stay UNSIGNED."
  if ($Require) { throw $msg }
  Write-Warning $msg
  exit 0
}

function Find-SignTool {
  if ($env:REVITMCP_SIGNTOOL -and (Test-Path $env:REVITMCP_SIGNTOOL)) { return $env:REVITMCP_SIGNTOOL }
  $onPath = Get-Command signtool.exe -ErrorAction SilentlyContinue
  if ($onPath) { return $onPath.Source }
  $kits = "${env:ProgramFiles(x86)}\Windows Kits\10\bin"
  if (Test-Path $kits) {
    $found = Get-ChildItem $kits -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
      Where-Object { $_.FullName -match '\\x64\\' } | Sort-Object FullName -Descending | Select-Object -First 1
    if ($found) { return $found.FullName }
  }
  throw "signtool.exe not found. Install the Windows SDK (Signing Tools) or set REVITMCP_SIGNTOOL."
}

$signtool = Find-SignTool
$timestamp = if ($env:REVITMCP_SIGN_TIMESTAMP) { $env:REVITMCP_SIGN_TIMESTAMP } else { "http://timestamp.digicert.com" }

$common = @("sign", "/fd", "SHA256", "/tr", $timestamp, "/td", "SHA256", "/d", "Revit MCP")
if ($thumb) { $common += @("/sha1", $thumb) }
else { $common += @("/f", $pfx); if ($env:REVITMCP_SIGN_PFX_PASSWORD) { $common += @("/p", $env:REVITMCP_SIGN_PFX_PASSWORD) } }

foreach ($f in $Files) {
  if (-not (Test-Path $f)) { throw "Not found: $f" }
  Write-Host "  signing $f"
  & $signtool @common $f | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "signtool failed for $f (exit $LASTEXITCODE)" }
  & $signtool verify /pa /q $f | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "Signature did not verify for $f" }
}
Write-Host "  signed $($Files.Count) file(s)" -ForegroundColor Green
