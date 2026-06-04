# Phase 0 — Setup & Verification

Phase 0 is the **skeleton & bridge** ([roadmap](07-roadmap.md)): it proves the
full path **Claude → Python MCP server → C# Revit add-in → Revit UI thread → back**
with a single `health_check` tool. No model is read or modified yet.

```
addin/    C# Revit add-in (IExternalApplication + loopback socket + ExternalEvent bridge)
server/   Python MCP server (FastMCP, stdio) + socket client + stub add-in for testing
```

## Exit criterion (from the roadmap)

> From a Claude host, `health_check` returns live Revit version + document state;
> the round-trip is logged on both sides with a correlation id; closing Revit
> yields a graceful error, not a hang.

---

## A. Verify the Python path *without* Revit (stub add-in)

You can validate the entire MCP-server → add-in protocol on any machine — no
Revit required — using the bundled stub that speaks the same wire protocol.

```powershell
cd "d:\Revit MCP\server"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .

# Terminal 1 — start the stub add-in (writes session.json, listens on loopback)
python -m tools.stub_addin
#   ...or simulate no project open:  python -m tools.stub_addin --no-doc

# Terminal 2 — drive health_check end-to-end
python -m tools.test_health
```

Expected (Terminal 2):

```json
{
  "ok": true,
  "data": {
    "revit_connected": true,
    "revit_version": "2025",
    "document_open": true,
    "document_title": "reference.rvt",
    "protocol_version": "1.0",
    "units": { "length": "millimeters", "area": "square meters" }
  },
  "welcome": { "type": "welcome", ... }
}
```

Graceful-failure checks (NFR-7):
- **Stub not running** → `health_check` returns `ok:false` with `NO_SESSION_FILE`
  or `REVIT_NOT_REACHABLE` (no hang).
- **`--no-doc`** → `document_open:false` so Claude knows to ask the user to open a project.

---

## B. Build & install the real Revit add-in

Requires a machine with Revit (2024–2026) and the .NET 8 SDK.

```powershell
cd "d:\Revit MCP\addin"
# Point at YOUR Revit install (folder with RevitAPI.dll / RevitAPIUI.dll):
dotnet build -c Release -p:RevitApiDir="C:\Program Files\Autodesk\Revit 2025"
```

Install the manifest + assembly so Revit loads it on startup:

1. Copy `addin\RevitMCP.addin` to
   `%ProgramData%\Autodesk\Revit\Addins\2025\RevitMCP.addin`.
2. Edit its `<Assembly>` to the **full path** of the built
   `RevitMCP.Addin.dll` (under `addin\bin\Release\`), or copy the DLL next to the
   manifest and leave the relative name.
3. Start Revit. On startup the add-in:
   - opens a loopback TCP socket on an ephemeral port,
   - writes `%LOCALAPPDATA%\RevitMCP\session.json` (port + per-session token),
   - logs to `%LOCALAPPDATA%\RevitMCP\logs\addin-<date>.log`.

Open any project so `health_check` reports a document.

---

## C. Register the MCP server with your Claude host

Point your MCP client (Claude Desktop, Claude Code, etc.) at the server. Example
MCP server entry:

```json
{
  "mcpServers": {
    "revit": {
      "command": "d:\\Revit MCP\\server\\.venv\\Scripts\\python.exe",
      "args": ["-m", "revit_mcp"]
    }
  }
}
```

Then ask the host to run **health_check**. With Revit open it returns the live
version, document title, and units. The server logs each call to **stderr** with
a correlation id; the add-in logs the matching request line — together they prove
the round-trip (NFR-5).

---

## What Phase 0 deliberately does NOT do

- No model reads (`list_levels`, `list_types`, …) — that's **Phase 1**.
- No mutations / transactions — the stage→preview→commit→undo spine is **Phase 2**.

## Architecture references

- The thread-affinity bridge (socket thread → `ExternalEvent` → UI thread):
  [03-architecture.md §3.2](03-architecture.md).
- The wire protocol (framing, handshake, error codes):
  [05-addin-protocol.md](05-addin-protocol.md).
- The session/auth file: [06-data-models.md §6.7](06-data-models.md).
