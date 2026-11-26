# 10 — Release: installer, Autodesk App Store, clean-machine testing

How Revit MCP is packaged for people who don't have Python, a repo or a
developer setup: one per-user MSI, plus the Autodesk `.bundle` the App Store
needs.

## What a user gets

| | |
|---|---|
| Installer | `RevitMCP-<version>.msi`, ~13 MB, **per user, no admin rights** |
| Installs to | `%APPDATA%\Autodesk\ApplicationPlugins\RevitMCP.bundle` (Revit loads it automatically) |
| Revit | 2025, 2026, 2027 (one add-in build each; `PackageContents.xml` picks the right one) |
| Python | not needed: the MCP server is a frozen `revit-mcp-server.exe` |
| Claude | the installer registers the server with **Claude Desktop** (config file) and **Claude Code** (`claude mcp add --scope user`), if present |
| Ribbon | *Revit MCP* tab: Status, Connect Claude, Pause/Resume, Audit log, Help, Logs |
| Uninstall | Apps & features → Revit MCP. Removes the bundle and both Claude registrations; keeps the audit log |

Bundle layout:

```
RevitMCP.bundle\
  PackageContents.xml                  Autodesk manifest (versions 2025..2027)
  Contents\2025|2026|2027\             RevitMCP.addin + RevitMCP.Addin.dll
  Contents\Server\revit-mcp-server.exe MCP server, + _internal\ (frozen Python runtime)
  Contents\Resources\help.html         F1 / Help button
```

`revit-mcp-server.exe` commands: no arguments = MCP server (what Claude starts);
`setup register|unregister|status`; `doctor`; `auth ...`; `audit ...`; `--version`.

## Build

```powershell
powershell -ExecutionPolicy Bypass -File installer\build.ps1 -Test
```

Needs .NET SDK 10 and Python 3.11 (NuGet/PyPI access on the first run). Revit
does **not** need to be installed: the add-in compiles against the reference
packages `Nice3point.Revit.Api.*`. Outputs (git-ignored):

| Output | Use |
|---|---|
| `dist\RevitMCP-<v>.msi` | direct download / IT deployment |
| `dist\RevitMCP-<v>-bundle.zip` | Autodesk App Store submission |
| `dist\SHA256SUMS.txt` | checksums for the release page |
| `build\stage\RevitMCP.bundle` | the unzipped bundle |

`-Test` runs the 48 unit tests and the 20-check governance end-to-end test
**against the built exe**. `-SkipServer` reuses the frozen server; `-RevitVersions 2027`
builds a subset; `-RequireSigning` fails an unsigned build.

### Versions and identity

* `VERSION` (repo root) is the single version, `MAJOR.MINOR.PATCH`. Every build
  stamps it into the add-in, the exe, the MSI and `PackageContents.xml`.
* `installer\product.json` holds the publisher, URLs and the fixed GUIDs.
  **Never change `msi_upgrade_code` or `bundle_upgrade_code` after the first
  public release**; they are how upgrades are recognised. Bump `VERSION` for every
  release; the MSI upgrades in place (major upgrade).
* `installer\requirements-server.lock` pins the exact Python packages frozen into
  the exe (the versions the tests ran against). Update it deliberately.

## Code signing

Unsigned builds work but trigger Revit's "unsigned add-in" prompt, SmartScreen
warnings and antivirus false positives, so **sign every public build**.

1. Buy an OV or EV **code-signing certificate** in the company's name (takes
   1–2 weeks: identity checks). EV/HSM certs live on a token or cloud HSM.
2. Install the Windows SDK *Signing Tools* (signtool.exe).
3. Before building, set **one** of:
   * `REVITMCP_SIGN_THUMBPRINT` = cert thumbprint (cert in CurrentUser\My, incl. EV token), or
   * `REVITMCP_SIGN_PFX` + `REVITMCP_SIGN_PFX_PASSWORD`.
4. `build.ps1 -RequireSigning` signs the three add-in DLLs, the exe and the MSI
   (SHA-256, RFC 3161 timestamp) and verifies each signature.

No secret is stored in the repo.

## Clean-machine test (before every release)

Use fresh Windows 11 VMs (snapshots), one per Revit version you can license.

| # | Step | Expect |
|---|---|---|
| 1 | Install Claude Desktop, then the MSI as a **standard (non-admin) user** | no UAC prompt; EULA shown |
| 2 | `verify-install.ps1` (from `installer\`) | all PASS |
| 3 | Start Revit, open a project | *Revit MCP* tab; no "unsigned" prompt (signed build) |
| 4 | Status button | "Ready: waiting for Claude" |
| 5 | Restart Claude Desktop; "Check the Revit connection" | health_check OK with `addin_version` / `server_version` |
| 6 | Stage → preview → approve a wall → undo | one undo step each; Audit log button shows both |
| 7 | Pause, then ask Claude anything | "not reachable"; Resume restores it |
| 8 | `verify-install.ps1` with Revit open | doctor shows the live add-in |
| 9 | Install the next version over it | upgrades in place, one Apps & features entry |
| 10 | Uninstall (Revit closed), then `verify-install.ps1 -Uninstalled` | all PASS |
| 11 | Install Claude **after** Revit MCP; click *Connect Claude* | registered |

Developer PCs (prefer a VM): a developer deploy (`addin\deploy.ps1`) and the
installed product register the same add-in id. Run `addin\deploy.ps1 -Remove`
before installing the MSI (verify-install.ps1 flags it). Also remove the
developer `revit` entry from Claude Desktop / Claude Code (the product registers
as `revit-mcp`); otherwise Claude lists every tool twice and the two servers
compete for the add-in's single connection.

## Autodesk App Store submission checklist

The authoritative rules are the current
[Revit publisher guidelines](https://aps.autodesk.com/marketplace/publisher-center/revit-publisher-guidelines)
and the Publisher Agreement; re-read them before submitting.

| Item | Status |
|---|---|
| Publisher account (company) on the Autodesk App Store | **to do** |
| Publisher name, URL, support email, help URL in `product.json` | **to do** (TODO placeholders) |
| Registered Developer Symbol → `addin_vendor_id` (currently `RVTMCP`) | **to do**: register with Autodesk |
| Signed binaries | **to do**: needs the certificate |
| Bundle with `PackageContents.xml` | done (`*-bundle.zip`) |
| Ribbon button for the main command, F1 help | done |
| Help / documentation page | done (`help.html`); host it at `help_url` too |
| EULA | **to do**: legal text for `installer\msi\License.rtf` (placeholder) |
| Privacy policy | **to do**: draft below, legal review |
| Icon, screenshots, demo video | placeholder icon (`installer\assets`, `make_icon.py`); rest to do |
| Listing states the Claude dependency | draft below |
| Clean install / uninstall tested on supported versions | test plan above; only Revit 2027 available here |

### Listing draft

> **Revit MCP: talk to your model with Claude.** Ask questions about your Revit
> project and make changes in plain language. Claude reads levels, grids, types
> and elements, proposes changes (walls, doors, windows, floors, rooms, levels),
> previews them against your live model, and changes nothing until you approve.
> Every change is one undo step and is recorded in a tamper-evident audit log.
> Optional read-only access tokens for reviewers.
>
> **Requires** Claude Desktop or Claude Code with a Claude plan (not included),
> and Revit 2025–2027 on Windows.

### Privacy policy draft (for legal review)

> Revit MCP runs entirely on your computer. Its Revit add-in accepts connections
> only from the same computer (127.0.0.1). When you use Claude with Revit MCP,
> the model information Claude requests (such as level names, element types,
> counts and the geometry of queried elements) is sent to Anthropic by your
> Claude application, under your Claude account and Anthropic's terms and
> privacy policy. Revit MCP does not send data anywhere else and collects no
> analytics or telemetry. Logs, the audit log and access settings are stored
> locally in `%LOCALAPPDATA%\RevitMCP` and are not uploaded.

## Known gaps in this release pipeline

* **Not yet installed or run inside Revit** from the MSI or bundle: the ribbon,
  bundle loading via `PackageContents.xml`, the relative `<Assembly>` path, and
  first-run registration need the clean-machine test above.
* Revit 2025/2026 builds compile but are **untested at runtime** (only Revit 2027
  is installed on the build PC).
* Current Claude Desktop downloads (claude.ai/download and the Microsoft Store)
  are both MSIX packages (`C:\Program Files\WindowsApps\Claude_...`). Which
  config file a given install reads **varies by PC, even on the same version**:
  `%APPDATA%\Claude\`, `%LOCALAPPDATA%\Packages\Claude_<id>\LocalCache\Roaming\Claude\`,
  or `%LOCALAPPDATA%\Claude-Data\claude_<id>\` (seen on a 6.28899 test PC).
  Since 1.0.2, registration writes all three (creating them if Claude was never
  opened) and replaces stale entries that start Revit MCP under another name
  (e.g. a hand-copied developer `revit` entry). The authoritative way to find
  the file on a PC: Claude > Settings > Desktop app > **Edit config**.
* Every `setup register` / `unregister` run (including the silent installer
  step) is logged to `%LOCALAPPDATA%\RevitMCP\logs\setup.log`: check it first
  when Claude doesn't show the Revit tools.
* Installs from the Autodesk App Store's own installer don't run our MSI
  actions: the add-in registers Claude on the first run of each version, but
  nothing unregisters it on uninstall (a stale entry Claude reports as failing).
* Longest installed path is ~120 characters under `%APPDATA%`; fine for normal
  profile names (limit 260).
* WiX is pinned to v5 (MS-RL). v6+ requires accepting the Open Source
  Maintenance Fee terms.
