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

## Status

🟡 **Specification phase.** No implementation yet. Review and refine the documents above before any code is written.
