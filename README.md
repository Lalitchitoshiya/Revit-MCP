# Revit MCP — Natural-Language BIM Automation

An MCP-based intelligent automation system that connects **Anthropic Claude** to **Autodesk Revit**, letting users describe design intent in plain language ("add a 3 m partition wall between grids B and C on Level 2, with a single door centred on it") and have the corresponding BIM elements placed programmatically in the live Revit model.

This repository is developed **specification-first**. Code is written to satisfy the specs in [`docs/`](docs/); the specs are the source of truth and change before the code does.

## How it works (one paragraph)

Claude talks to a **Python MCP server** over stdio. The MCP server exposes a small, deterministic toolset (discover model context, search element types, stage a placement plan, preview it, commit it, undo it). The MCP server is itself a **client of a C# Revit add-in** that hosts a localhost socket inside the running Revit session. The add-in receives JSON commands, marshals them onto Revit's UI thread via an `ExternalEvent`, executes the Revit API calls inside transactions, and returns structured results. Every mutating batch is wrapped in one undoable transaction group, and nothing is written until the user confirms a previewed plan.

```
┌─────────┐  MCP/stdio  ┌──────────────┐  TCP/JSON   ┌────────────────────┐
│ Claude  │ ──────────▶ │ Python MCP   │ ──────────▶ │ C# Revit Add-in    │
│ (host)  │ ◀────────── │ server       │ ◀────────── │ (socket + Revit API)│
└─────────┘   tools     └──────────────┘   results   └────────────────────┘
                                                              │
                                                       ExternalEvent
                                                              ▼
                                                      Revit UI thread
                                                      (Transactions)
```

## Specification index

| # | Document | Purpose |
|---|----------|---------|
| 01 | [Problem Statement](docs/01-problem-statement.md) | Refined problem, goals, non-goals, personas, success metrics |
| 02 | [Requirements](docs/02-requirements.md) | Functional + non-functional requirements (testable) |
| 03 | [Architecture](docs/03-architecture.md) | Components, threading model, data flow, key constraints |
| 04 | [MCP Tool Contract](docs/04-mcp-tool-contract.md) | The tools Claude sees, with schemas and semantics |
| 05 | [Add-in Wire Protocol](docs/05-addin-protocol.md) | JSON protocol between MCP server and Revit add-in |
| 06 | [Data Models](docs/06-data-models.md) | Plan/Action/Preview schemas, units, coordinate conventions |
| 07 | [Roadmap](docs/07-roadmap.md) | Phased delivery plan with exit criteria per phase |
| 08 | [Acceptance Criteria](docs/08-acceptance-criteria.md) | End-to-end scenarios that define "done" |

## Status — implemented & verified live on Autodesk Revit 2027

The system is **built and working end-to-end**, developed in spec-driven phases. Each phase was verified live against a real model (the *Snowdon Towers Sample Architectural* project).

| Phase | Capability | Status |
|-------|-----------|--------|
| 0 | **Bridge** — Claude ↔ MCP server ↔ Revit round-trip (`health_check`) | ✅ verified live |
| 1 | **Discovery** — read levels, grids, types, families, elements, selection | ✅ verified live |
| 2 | **Safety spine** — stage → preview → confirm → commit → undo (`place_wall`) | ✅ verified live |
| 3 | **Breadth** — doors, windows, floors, rooms, levels (hosted + handles) | ✅ verified live |
| 4 | **Orchestration** — multi-element plans, summaries, ambiguity, dialog safety | ✅ verified live |
| 5 | **Hardening** — automated tests + resilience suite | 🟢 mostly done (one open item) |

### What's proven live
- A **wall + a hosted door** created together in one plan; **one undo removes both** (intra-plan handles + atomic undo).
- A **4×3 m room** = 4 walls + a floor + a door, staged/previewed/committed as **one atomic plan**, with a plain-English summary, then reverted by a single undo.
- **6/6 resilience checks** (bad token, version mismatch, commit-hygiene refusals, wrong confirmation token, stale session — all fail cleanly, no hangs).
- **14 automated unit tests** pass (`pytest`, no Revit needed).
- **Grounding:** every placement uses real type/level/family names read from the live model — nothing invented.

### Known open item
Commit can stall if Revit's UI thread is busy or shows a non-failure modal dialog mid-placement (transaction warnings are already auto-handled). Planned fix: auto-dismiss dialogs during commit.

## Repository layout

```
addin/    C# Revit add-in (IExternalApplication: loopback socket + ExternalEvent UI-thread bridge)
          deploy.ps1 — shadow-copy build/deploy so the manifest never locks the build output
server/   Python MCP server (FastMCP, stdio) + socket client; tools/ live test scripts; tests/ unit tests
docs/     Specification package (01–08) + Phase-0 setup + the project presentation (.pptx)
```

## Quickstart

**1. Build & install the add-in** (Windows + Revit 2024–2027 + .NET SDK):
```powershell
cd addin
.\deploy.ps1 -RevitApiDir "C:\Program Files\Autodesk\Revit 2027" -RevitVersion 2027
```
Start Revit, click **Always Load**, and open an **architectural project** (`.rvt`, not a family).

**2. Set up the MCP server:**
```powershell
cd server
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -e ".[test]"
python -m pytest tests/        # 14 unit tests, no Revit needed
```

**3. Register with a local Claude client** (Claude Desktop or Claude Code) — see [`.mcp.json.example`](.mcp.json.example) / [docs/phase-0-setup.md](docs/phase-0-setup.md). Then talk to it:
> *"Run a health check. What levels and wall types are in my model? Stage a 4 m wall on Level 1 with a door 2 m along it and preview it."*

> **Note:** this is a **local** system — Revit, the server, and the client all run on one machine over `127.0.0.1`. It cannot be driven from a cloud/web chat (claude.ai / ChatGPT web), only from a desktop client on the same PC.

**Verify against live Revit** (with a project open):
```powershell
python -m tools.test_discovery     # read-only discovery
python -m tools.test_lifecycle     # stage→preview→commit→undo (place a wall, then undo)
python -m tools.test_resilience    # 6/6 safe-failure checks
```

## Presentation

A short overview deck: [docs/Revit-MCP-Presentation.pptx](docs/Revit-MCP-Presentation.pptx) (16:9, regenerate via [docs/generate_presentation.py](docs/generate_presentation.py)).
