# 03 — Architecture

## 3.1 Components

```
┌──────────────────────────────────────────────────────────────────────────┐
│ HOST (Claude Desktop / Claude Code / Anthropic API client)                 │
│  - Holds the conversation, decides which MCP tools to call                 │
└───────────────▲────────────────────────────────────────────────────────────┘
                │ MCP (JSON-RPC over stdio)
┌───────────────┴──────────────────────────────────────────────────────────┐
│ MCP SERVER  (Python, `mcp` SDK)                                            │
│  - Exposes the tool contract (§04) to the host                             │
│  - Translates tool calls → add-in wire requests (§05)                      │
│  - Holds the per-session plan registry (staged plans, ids)                 │
│  - Enforces "no commit without confirmation" at the protocol level         │
│  - Unit conversion boundary (§06), validation pre-checks                   │
│  - Socket CLIENT to the add-in                                             │
└───────────────▲──────────────────────────────────────────────────────────┘
                │ TCP, line-delimited JSON, loopback + token (§05)
┌───────────────┴──────────────────────────────────────────────────────────┐
│ REVIT ADD-IN  (C#, .NET — IExternalApplication)                            │
│                                                                            │
│  ┌──────────────────┐   enqueue    ┌───────────────────────────────────┐  │
│  │ Socket listener  │ ───────────▶ │ Request queue (thread-safe)       │  │
│  │ (background      │              └───────────────────────────────────┘  │
│  │  thread)         │ ◀─── result ───────────────┐                        │
│  └──────────────────┘                            │                        │
│            │ ExternalEvent.Raise()               │ signal complete        │
│            ▼                                      │                        │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │ IExternalEventHandler  (runs on Revit UI thread, valid API context)  │ │
│  │   - dequeues request, dispatches to a Command handler                │ │
│  │   - Command handlers: model.summary, types.list, plan.validate, ...  │ │
│  │   - wraps mutations in Transaction / TransactionGroup                │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
│            │                                                               │
│            ▼  Autodesk.Revit.DB / .UI                                      │
│      ┌──────────────┐                                                      │
│      │ Revit model  │                                                      │
│      └──────────────┘                                                      │
└────────────────────────────────────────────────────────────────────────────┘
```

## 3.2 The hard constraint: Revit API thread affinity

The Revit API may **only** be called:
1. on Revit's **main UI thread**, and
2. within a **valid API context** (driven by Revit, e.g. inside an external command, an `ExternalEvent` handler, or an `Idling`/`DocumentChanged` callback).

A socket listener inherently runs on a **background thread**, which is *not* a valid context. Therefore the add-in uses the **`ExternalEvent` pattern** as the bridge:

1. The socket listener (background thread) parses an incoming request and pushes a `PendingRequest` (carrying the parsed command + a `ManualResetEventSlim` + a slot for the result) onto a thread-safe queue.
2. The listener calls `ExternalEvent.Raise()`. This asks Revit to invoke our `IExternalEventHandler.Execute(UIApplication)` **on the UI thread, in a valid context, when Revit is idle.**
3. `Execute` drains the queue, runs each command's handler (which may open Transactions), fills in the result, and signals the `ManualResetEventSlim`.
4. The listener thread, which was waiting on that event (with a timeout — NFR-7), wakes, serializes the result, and writes it back to the socket.

**Consequences captured as rules:**
- The listener thread holds **no** `Document`/`Element` references and calls **no** Revit API.
- Only the handler touches the API. All transactions live there.
- If Revit is mid-modal-dialog, `Raise()` won't be serviced until it closes; the listener's bounded wait converts this into a timeout error rather than a hang (NFR-7).

### Why not `Idling`?
`Idling` fires continuously and is suited to polling, but `ExternalEvent` is the idiomatic, lower-overhead choice for "run this on demand on the UI thread." We use `ExternalEvent`. (`Idling` may be added later for progress/cancellation if needed.)

## 3.3 The stage → preview → commit → undo lifecycle

This lifecycle is the backbone of the safety model (G3, FR-P*).

```
 stage_plan(plan)         preview_plan(plan_id)        commit_plan(plan_id, confirm)        undo_plan(plan_id)
        │                        │                              │                                  │
        ▼                        ▼                              ▼                                  ▼
 server stores plan,     add-in validates plan       REQUIRES confirm token from user;     TransactionGroup
 assigns plan_id,        READ-ONLY against the        add-in opens a TransactionGroup,      rolled back (or
 returns id + a          model; returns per-action    runs each action in its own           Document.Undo if
 confirmation token      diagnostics + a preview      Transaction; Assimilate on full       it's the last op),
 the user must echo      (counts, geometry, ids       success, RollBack + report on any     plan marked
                         that WOULD be created)        failure (FR-P6); returns real ids     reverted
```

- **Staging** is server-side: the plan is registered, validated for shape/units, given a `plan_id` and a one-time `confirmation_token`.
- **Preview** is add-in-side and **read-only**: it resolves type names → `ElementId`s, levels, hosts, and computes resulting geometry *without* a transaction (or inside a transaction that is deliberately **rolled back**, used only to measure). It never leaves the model changed.
- **Commit** requires the caller to present the `confirmation_token` that the user explicitly approved (FR-P4). One `TransactionGroup` per commit (NFR-2, FR-P3).
- **Undo** reverts the group. The server tracks committed `plan_id`s so a specific plan can be targeted within the session (FR-P5).

> **Confirmation provenance.** The MCP server treats `commit_plan` as forbidden unless the call carries the exact `confirmation_token` issued at staging. Claude cannot fabricate it; the token is surfaced to the user in the preview and the user (or host UI) must supply it back. This is what makes "0 unconfirmed mutations" enforceable rather than a matter of prompt discipline.

## 3.4 Grounding model (anti-hallucination)

To satisfy FR-C1 / success-metric "grounding = 0 invented refs":

- Type names, level names, family names, host element ids, and base coordinates in any plan **must** originate from a prior discovery/query tool result.
- The add-in re-resolves every reference at **preview** time against the live model; anything that doesn't resolve becomes an `error` diagnostic, blocking commit.
- The MCP server may additionally tag plan fields with the discovery call/id they came from, enabling a server-side pre-check before bothering the add-in.

## 3.5 Data flow — a worked example

> User: *"Add a 4 m generic wall on Level 1 running east from grid intersection A-1, then put a single-leaf door 1 m from its start."*

1. **Claude → `get_model_summary`** → units = mm, Level 1 exists (elev 0).
2. **Claude → `list_grids`** → grid A and grid 1, intersection point resolved.
3. **Claude → `list_types("OST_Walls")`** → finds "Generic - 200mm".
4. **Claude → `search_families("single door")`** → finds "Single-Flush: 0915 x 2134mm".
5. **Claude → `stage_plan`** with two actions: `place_wall` (start = A-1 intersection, end = +4 m east, type, level) and `place_door` (host = *the wall just staged*, distance_along = 1 m, type). Server returns `plan_id`, `confirmation_token`.
6. **Claude → `preview_plan(plan_id)`** → add-in resolves refs, confirms the wall type & level exist, confirms the door type loaded, computes the door's host point. Returns "OK: 1 wall (4.0 m), 1 door hosted at 1.0 m" + warnings (none).
7. **Claude relays preview to user; user confirms.**
8. **Claude → `commit_plan(plan_id, confirmation_token)`** → one `TransactionGroup`: create wall (get its `ElementId`), then create door hosted on that wall. `Assimilate()`. Returns `{wall: id, door: id}`.
9. **Claude → user:** "Done — created 1 wall and 1 door on Level 1. Say 'undo' to revert."

Intra-plan references (the door referencing the not-yet-created wall) are handled by **plan-local handles** — see [§06](06-data-models.md).

## 3.6 Failure & resilience model (NFR-7)

| Condition | Behaviour |
|-----------|-----------|
| Revit not running / add-in not loaded | MCP server's connect fails fast; tools return a clear "Revit not reachable — is Revit open with the add-in loaded?" error. |
| No active document | Health check + every command returns `NO_ACTIVE_DOCUMENT`. |
| Revit busy (modal dialog) | `ExternalEvent` not serviced; listener's bounded wait → `REVIT_BUSY_TIMEOUT`. |
| Action fails mid-commit | `TransactionGroup.RollBack()`; respond with the failing action index + Revit exception message; model unchanged (FR-P6). |
| Plan id unknown / expired | `PLAN_NOT_FOUND`. |
| Commit without valid confirmation token | `CONFIRMATION_REQUIRED` — refused. |
| Protocol version mismatch | Connect handshake fails with `VERSION_INCOMPATIBLE` (NFR-8). |

## 3.7 Deployment & lifecycle

- The **add-in** is installed via a `.addin` manifest into Revit's Addins folder; it starts its socket listener in `OnStartup` (IExternalApplication) and tears it down in `OnShutdown`. On startup it generates a per-session token and writes it to a known local file (e.g. `%LOCALAPPDATA%\RevitMCP\session.json`, restricted ACL).
- The **MCP server** is launched by the host (its command/args registered in the host's MCP config). On start it reads the session token file and connects to the add-in's loopback port.
- See [§07](07-roadmap.md) for the order in which these come online.
