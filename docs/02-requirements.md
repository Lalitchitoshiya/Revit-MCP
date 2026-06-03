# 02 — Requirements

Requirements are written to be **testable**. Each has an ID. Acceptance scenarios in [§08](08-acceptance-criteria.md) reference these IDs. Priority: **MUST** (v1 blocking), **SHOULD** (v1 if affordable), **COULD** (later).

## 2.1 Functional requirements

### Discovery & grounding (read-only)

| ID | Priority | Requirement |
|----|----------|-------------|
| FR-D1 | MUST | The system can report a **model summary**: project title, active document, length/area units, project base point, list of levels (name + elevation), and counts of elements per relevant category. |
| FR-D2 | MUST | The system can list **levels** (name, elevation, id) and **grids** (name, endpoints, id). |
| FR-D3 | MUST | The system can list **available types** for a category (e.g. wall types, door types, floor types) including type name, family name, and id. |
| FR-D4 | MUST | The system can **search loaded families/types** by keyword (e.g. "single flush door") and return ranked matches. |
| FR-D5 | MUST | The system can **query existing elements** by category, level, and/or bounding region, returning id, type, level, and a geometric summary (e.g. wall location line, door host id). |
| FR-D6 | SHOULD | The system can read the **current selection** in Revit and the **active view** (name, level, view type) to ground relative language ("this wall", "on this level"). |

### Planning, preview, mutation

| ID | Priority | Requirement |
|----|----------|-------------|
| FR-P1 | MUST | The system can accept a structured **placement plan** (an ordered list of typed actions) and **validate** it against the live model **without mutating** it, returning per-action diagnostics (ok / warning / error) and a preview summary. |
| FR-P2 | MUST | Validation MUST catch, at minimum: unknown type/family, unknown level, missing host for a hosted element, geometry outside reasonable bounds, and unit-less coordinates. |
| FR-P3 | MUST | The system can **commit** a previously-staged, validated plan, executing all actions inside a **single transaction group** so the whole batch is one undo step. It returns the created/modified element ids. |
| FR-P4 | MUST | No commit occurs without an explicit, plan-scoped **user confirmation** signal originating from the user (not Claude). |
| FR-P5 | MUST | The system can **undo** the last committed plan (and SHOULD support undoing a specific plan by id within the session). |
| FR-P6 | MUST | A failed action mid-commit MUST roll back the entire transaction group (atomic batch) and report which action failed and why. |
| FR-P7 | SHOULD | The system can **modify** existing elements (e.g. change a wall's type, move a door along its host) and **delete** elements, under the same stage→preview→commit→undo flow. |

### Element operations (v1 — architectural core)

The plan's action vocabulary. Each is an operation the add-in maps to Revit API calls.

| ID | Priority | Operation |
|----|----------|-----------|
| FR-E1 | MUST | `place_wall` — straight wall from point A to point B, on a level, of a given wall type, with height/base/top constraints. |
| FR-E2 | MUST | `place_door` — door hosted in a specified wall, located by distance-along-wall or by reference to a grid/point; given a door type. |
| FR-E3 | MUST | `place_window` — window hosted in a wall, located + sill height, given a window type. |
| FR-E4 | SHOULD | `place_floor` — floor from a closed boundary loop on a level, given a floor type. |
| FR-E5 | SHOULD | `place_room` — room placed at a point inside an enclosed region on a level, optional name/number. |
| FR-E6 | SHOULD | `create_level` — new level at an elevation with a name. |
| FR-E7 | COULD | `create_grid` — new grid line (linear) by two points with a name. |
| FR-E8 | COULD | `modify_element` / `delete_element` — generic edits per FR-P7. |

### Conversation & orchestration

| ID | Priority | Requirement |
|----|----------|-------------|
| FR-C1 | MUST | Claude MUST ground every plan in discovery-tool results — types, levels, families, and coordinates in a plan must trace to data read from the live model, not invented. |
| FR-C2 | MUST | When intent is ambiguous or grounding fails (e.g. two walls match "the north wall"), the system surfaces the ambiguity and asks the user to choose rather than guessing silently. |
| FR-C3 | SHOULD | The system can decompose a multi-element request ("a room with four walls and a door") into a single coherent plan and preview it as a whole. |
| FR-C4 | SHOULD | After a commit, the system reports a concise human summary of what changed (counts, ids, level). |

## 2.2 Non-functional requirements

| ID | Priority | Requirement |
|----|----------|-------------|
| NFR-1 (Thread safety) | MUST | All Revit API access occurs on Revit's UI thread via the `ExternalEvent` mechanism. The socket listener never touches the API directly. No `Autodesk.Revit` call is made outside a valid API context. |
| NFR-2 (Atomicity) | MUST | Every mutating commit is wrapped in a `TransactionGroup` that is `Assimilate()`d on full success and rolled back on any failure. |
| NFR-3 (Security) | MUST | The add-in socket binds to **loopback only** (`127.0.0.1`), accepts a single client at a time, and requires a per-session shared token (generated by the add-in, passed to the MCP server out-of-band) on every request. No remote exposure. |
| NFR-4 (Determinism) | MUST | Given the same model state and the same plan, commit produces the same elements. Tools do not depend on wall-clock time or randomness. |
| NFR-5 (Observability) | MUST | All requests/responses are logged (server side + add-in side) with a correlation id, plan id, and timing. Logs redact the auth token. |
| NFR-6 (Latency) | SHOULD | Read/discovery tool p50 < 1.5 s; commit of ≤ 20 elements p50 < 5 s (measured on a reference model, see [§08](08-acceptance-criteria.md)). |
| NFR-7 (Resilience) | MUST | If Revit is closed, busy in a modal dialog, has no active document, or the add-in is unloaded, tools fail **gracefully** with an actionable error — never hang indefinitely (bounded request timeout). |
| NFR-8 (Versioning) | SHOULD | The wire protocol and tool contract are versioned; the MCP server and add-in negotiate/validate a compatible version on connect ([§05](05-addin-protocol.md)). |
| NFR-9 (Units) | MUST | A single, documented unit-conversion boundary exists; the protocol carries explicit units; nothing relies on implicit feet. |
| NFR-10 (Portability) | SHOULD | The add-in supports a defined range of Revit versions (target: Revit 2024–2026); version-specific API differences are isolated. |
| NFR-11 (Idempotency of reads) | MUST | Discovery/query tools have no side effects and may be called freely. |
| NFR-12 (Testability) | SHOULD | The add-in command handlers are unit-testable against a mock/abstracted document where feasible; the MCP server is testable against a stub add-in implementing the wire protocol. |

## 2.3 Constraints

- **CN-1** — Revit API is .NET (C#); the add-in is C#. MCP server is Python (`mcp` SDK).
- **CN-2** — Revit must be human-attended in v1 (licensing + confirmation).
- **CN-3** — Communication is local only (single machine).
- **CN-4** — Revit internal length unit is decimal feet; all geometry crossing the API boundary must be converted explicitly (NFR-9).

## 2.4 Out of scope (traceability to non-goals)

Structural/MEP (NG1), family authoring (NG2), worksharing/cloud (NG3), headless Revit (NG4), documentation automation (NG5), image input (NG6). See [§01.4](01-problem-statement.md#14-non-goals-for-v1).
