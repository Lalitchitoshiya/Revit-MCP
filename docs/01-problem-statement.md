# 01 — Problem Statement

## 1.1 Context

Placing elements in Autodesk Revit is precise but laborious. Even routine work — laying out partition walls, hosting doors and windows, defining floors and rooms, adding levels and grids — requires the user to: pick the right tool, select the correct family/type, set the level and constraints, draw geometry with exact coordinates, and repeat per element. The knowledge of *what to do* is often easy to state in words ("put a door in the middle of that wall"); the *doing* is many clicks.

Large language models can turn natural-language design intent into structured operations, but they cannot touch a desktop application's in-memory model on their own. Revit, critically, **exposes no network API** — its API is an in-process .NET API that may only be called on the application's UI thread within a valid API context. Bridging "Claude understands intent" to "Revit changes the model" is the core problem.

## 1.2 Problem statement (refined)

> **Build an MCP-based automation system that lets a user, in conversation with Claude, place and modify architectural BIM elements in a *live, open* Revit model through natural language — safely (nothing is written without preview and confirmation, everything is undoable), deterministically (the same intent yields the same Revit API operations), and within the hard constraints of the Revit API (UI-thread affinity, transactions, family/type resolution, internal units).**

The system interprets conversational intent, maps it to a structured, validated *placement plan* of discrete Revit API operations, previews the consequences to the user, and — on confirmation — executes the plan inside a single undoable transaction.

## 1.3 Goals

- **G1 — Conversational placement.** Users describe intent in natural language; the system places the corresponding elements without the user touching Revit's UI.
- **G2 — Deterministic mapping.** Intent is resolved to an explicit, inspectable plan of typed operations before anything executes. No "magic" hidden in the model layer.
- **G3 — Safety by default.** Every mutation is previewed, requires confirmation, and is reversible with a single undo.
- **G4 — Respect Revit's constraints.** All model access is correctly marshalled to the UI thread and wrapped in transactions; units and coordinates are handled explicitly.
- **G5 — Grounded in reality.** The system reads the *actual* open model (levels, grids, loaded families, existing elements) and plans against it — it never invents type names or coordinates.

## 1.4 Non-goals (for v1)

- **NG1** — Structural and MEP disciplines (columns, beams, ducts, pipes, fixtures). Architecture only in v1. (Designed to be extensible — see roadmap.)
- **NG2** — Family *authoring* (creating new families/types from scratch). v1 only places instances of families already loaded in the project.
- **NG3** — Multi-user / cloud Revit (BIM 360 / ACC worksharing coordination, real-time collaboration). v1 targets a single local Revit session.
- **NG4** — Headless / unattended Revit. v1 requires a human-attended Revit session (needed for the confirm step and for licensing).
- **NG5** — Full schedules, sheets, annotation, rendering, and documentation automation.
- **NG6** — Drawing/sketch recognition or image-to-model. Input is text (and structured tool calls), not images, in v1.

## 1.5 Personas

- **P1 — BIM Modeler / Architect ("Ava").** Comfortable in Revit, wants to offload repetitive placement and rough layout to speed up early design. Primary user.
- **P2 — Junior designer ("Leo").** Knows design intent but not every Revit workflow; benefits from describing intent in words.
- **P3 — Developer / integrator ("Dev").** Extends the toolset, adds new element operations, maintains the add-in. Reads the specs to know the contracts.

## 1.6 Representative user stories

- *"As Ava, I want to say 'add a straight wall from grid A1 to A4 on Level 1 using the Generic 200mm type' and have it placed, so I skip drawing it by hand."*
- *"As Leo, I want to ask 'where can I put a door on the east wall of the lobby?' and get a sensible placement I can confirm, so I don't have to know the hosting rules."*
- *"As Ava, I want to preview exactly which elements a request will create and where, and reject it if it's wrong, before anything touches my model."*
- *"As Ava, I want one undo to revert the whole batch a prompt produced, so a bad result is cheap to discard."*

## 1.7 Success metrics

| Metric | Target (v1) |
|--------|-------------|
| **Intent success rate** — fraction of in-scope prompts (from the acceptance scenario set) that produce a correct, confirmable plan without manual coordinate entry | ≥ 80% |
| **Safety** — model mutations that occur without an explicit user confirmation | **0** (hard requirement) |
| **Reversibility** — committed batches fully revertible by one undo | 100% |
| **Grounding** — placements referencing a type/level/family that does not exist in the model | **0** (must be caught at preview) |
| **Round-trip latency** — discovery/query tool call p50 | < 1.5 s |
| **Round-trip latency** — commit of a ≤ 20-element plan p50 | < 5 s |

## 1.8 Key risks & assumptions

- **A1** — Revit is installed, licensed, open, with a project document active and the add-in loaded. (Validated by a health check; see [§04](04-mcp-tool-contract.md).)
- **R1 — Thread/context violations.** Calling the Revit API off the UI thread throws. Mitigated by the `ExternalEvent` marshalling model ([§03](03-architecture.md)).
- **R2 — Family/type not loaded.** "Place a door" fails if no door family is loaded. Mitigated by discovery tools + preview diagnostics that surface the gap instead of crashing.
- **R3 — Ambiguous spatial language** ("the north wall", "the middle"). Mitigated by grounding against real model elements and asking the user to disambiguate when confidence is low.
- **R4 — Coordinate/unit errors.** Revit's internal unit is decimal feet. Mitigated by an explicit unit-conversion boundary ([§06](06-data-models.md)).
