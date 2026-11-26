# 07 — Roadmap

Phased delivery. Each phase has an **exit criterion** — it isn't "done" until that is demonstrably met. Phases are ordered so that risk (thread affinity, the wire bridge) is retired early, before element breadth is added.

## Phase 0 — Skeleton & bridge (retire the hardest risk first)

**Goal:** Prove the full path Claude → MCP server → add-in → Revit UI thread → back, with nothing but a health check.

- C# add-in (`IExternalApplication`) that, on startup, opens a loopback socket, writes `session.json`, and tears down on shutdown.
- `ExternalEvent` + handler + thread-safe request queue (§03.2) wired for one method: `health.check`.
- Python MCP server (`mcp` SDK, stdio) exposing one tool: `health_check`; reads `session.json`, connects, does the handshake (§05.2).
- Newline-delimited JSON framing, token auth, bounded timeout.

**Exit criterion:** From a Claude host, `health_check` returns live Revit version + document state, and the round-trip is logged on both sides with a correlation id. Closing Revit yields a graceful error, not a hang.

## Phase 1 — Discovery / grounding (read-only)

**Goal:** Claude can fully ground a conversation in the real model.

- Methods + tools: `model.summary`, `levels.list`, `grids.list` (with intersections), `types.list`, `families.search`, `elements.query`, `context.get`.
- Unit reporting + the conversion boundary scaffolding (read paths first).

**Exit criterion:** Acceptance scenarios AC-D1..AC-D4 ([§08](08-acceptance-criteria.md)) pass: Claude can answer "what levels/wall types/loaded doors exist?" and "what walls are on Level 1?" entirely from live data, with **zero** invented values, p50 < 1.5 s.

## Phase 2 — Single-element mutation lifecycle (the safety spine)

**Goal:** The stage→preview→commit→undo lifecycle works end-to-end for **one** op (`place_wall`).

- Server: plan registry, `plan_id`, `confirmation_token`, confirmation enforcement (§03.3).
- Add-in: `plan.preview` (read-only resolution + diagnostics), `plan.commit` (one `TransactionGroup`, atomic), `plan.undo`, `plan_hash` hygiene.
- Full diagnostic set for walls (`UNKNOWN_TYPE`, `UNKNOWN_LEVEL`, `UNITLESS_LENGTH`, `WALL_VERY_SHORT`, `POINT_OUT_OF_BOUNDS`).

**Exit criterion:** AC-W1..AC-W3 pass: a wall is placed only after preview + confirmation; one `undo_plan` reverts it; committing without the token is refused; a bad type is caught at preview and never reaches the model. **0 unconfirmed mutations.**

## Phase 3 — Architectural element breadth

**Goal:** Cover the v1 element vocabulary on top of the proven lifecycle.

- `place_door`, `place_window` (hosting + plan-local handles, §06.4) — **MUST**.
- `place_floor`, `place_room`, `create_level` — **SHOULD**.
- `create_grid`, `modify_element`, `delete_element` — **COULD** (as time allows).
- Multi-action plans within one transaction group; intra-plan handle resolution at commit.

**Exit criterion:** AC-M1..AC-M5 pass, including the worked example (§03.5): a wall + hosted door staged as one plan, previewed, confirmed, committed atomically, undone as one step.

## Phase 4 — Orchestration & UX polish

**Goal:** The conversational experience is robust.

- Tool descriptions tuned so Claude reliably follows discover→stage→preview→confirm→commit (§04.5).
- Ambiguity handling (FR-C2): multi-match refs surface a choice, not a guess.
- Multi-element decomposition (FR-C3) and post-commit human summaries (FR-C4).
- Warning relay: previews with warnings are clearly communicated before confirmation.

**Exit criterion:** AC-C1..AC-C2 pass: an ambiguous request triggers a clarifying question; a compound request ("a 4×3 m room with a door") produces one coherent, previewed plan. Intent success rate ≥ 80% over the scenario set.

## Phase 5 — Hardening, tests, docs

**Goal:** Production-grade reliability and maintainability.

- Add-in command handlers unit-tested against an abstracted document; MCP server tested against a **stub add-in** implementing the wire protocol (NFR-12).
- Resilience matrix (§03.6) exercised: closed Revit, no document, modal dialog, mid-commit failure, version mismatch.
- Multi-version support validated across Revit 2024–2026 (NFR-10); version-specific API isolated.
- Logging/observability finalised (NFR-5); install/setup docs for add-in + MCP server registration.

**Exit criterion:** All MUST requirements met; resilience matrix green; latency NFRs met on the reference model; setup reproducible from docs on a clean machine.

## Sequencing rationale

- **Risk-first:** Phase 0 proves the thread-affinity bridge — the single biggest technical unknown — before any feature work.
- **Safety before breadth:** Phase 2 builds the mutation safety spine on one op; Phase 3 only adds element types onto an already-trusted lifecycle, so breadth never compromises the "0 unconfirmed mutations" guarantee.
- **Grounding before mutation:** Phase 1 ensures plans are built from real data before any write path exists.

## Tool backlog (post-v1, queued 2026-11-26)

Belongs to **phase 4 "new modelling features"** of the release plan (after
production release, the known limits and governance). Implemented today: the 13
tools of §04 with 6 ops (`place_wall`, `place_door`, `place_window`,
`place_floor`, `place_room`, `create_level`).

Rules for every new tool, unchanged from v1:
* **Reads** are direct tools; anything that **changes the model or the file**
  is a new `op` behind stage → preview → approve → commit → undo, audited.
* Launching apps and opening or saving files also need the human's approval
  (same approval prompt as a commit), because they aren't undoable.
* Effort is engineering days including live testing on one Revit version.

### Tool phase A (agreed 2026-11-26): implement first

The backlog is delivered in 3 tool phases; phase A is fixed, B and C are to be
discussed (from the candidate list below).

| Tool | Kind | Design notes | Effort |
|---|---|---|---|
| `start_revit` | session, approved | Launch `Revit.exe` (version from the arg, else newest installed that the bundle supports), optional `.rvt` to open; wait for `session.json` + a live `health.check` (timeout ~3 min). Runs in the **MCP server** (Revit isn't there to ask). Report startup dialogs that block (licence/sign-in, unsigned add-in prompt, "what's new") as "waiting for you in Revit". Refuse if a Revit is already running unless asked for another version. | 1 |
| `close_revit` | session, approved | Exit Revit cleanly. **Default: refuse if any open document has unsaved changes** and list them; the user must choose `save` or `discard` (workshared: also `sync`/`relinquish` choice). Then close via `PostableCommand.ExitRevit` (Revit's own exit path), so the add-in shuts down and removes `session.json`. No API-level kill; `Stop-Process` is never used. | 0.5–1 |
| `list_documents`, `open_document` | read / session, approved | List open projects (title, path, active, modified, workshared). Open by path with `UIApplication.OpenAndActivateDocument` from the ExternalEvent handler (verify early: some API contexts forbid it). Workshared central: create/open a **local copy**, never the central file; detach is never automatic. `.rfa` refused. Audited. | 1 |
| `modify_element` | op | Change type, instance/type parameters (with unit conversion + read-only/formula checks), level offset/height, move by a vector, for one or many ids. Preview lists every element's before → after; refuses read-only and type-parameter changes that would affect other instances unless explicit. Undo = one step. | 2–3 |
| `delete_element` | op | Preview deletes inside a rolled-back transaction to get the **full dependant list** (hosted doors/windows, tags, dimensions, rooms bounded by the wall) and shows it before approval. Pinned elements refused unless explicit. | 1 |
| `place_family_instance` | op | Non-hosted, level-based families (furniture, fixtures, equipment, generic models, specialty): point, level, offset, rotation; type resolved via `search_families`/`list_types` with the usual ambiguity rules. Family must already be loaded. Face- and wall-hosted placement later. | 1.5–2 |
| `export` (PDF / DWG / IFC) | file, approved | Views/sheets (PDF, DWG) or the model (IFC), to a folder the user names; never overwrites without saying so; returns the file list. PDF: `PDFExportOptions` (combined or per sheet). DWG: export setup by name or default. IFC: version (IFC2x3/IFC4) + export setup; needs a transaction that is rolled back. Large exports: per-method timeout well above the 120 s commit limit. | 1.5–2 |

Total ≈ 9–11 days (about 2 weeks) on Revit 2027, plus a pass on 2025/2026.

Shared work this phase introduces (counted above):
* **Approval for non-undoable actions** (start/close/open/export): same
  human approval prompt as a commit, plus an audit record (`session.start`,
  `session.close`, `document.open`, `export`).
* Tool docstrings + tests (stub add-in for the server, live suite for the add-in).

### Candidate list (for phases B and C; to be discussed)

| # | Tool / op | Kind | What it does | Effort | Notes |
|---|---|---|---|---|---|
| 1 | `start_revit` | session, approved | Start Revit when it's closed (pick version if several, newest by default), wait for the add-in's `session.json`, optionally open a project | 1 | Needs the human's OK. Startup dialogs (licence/sign-in, unsigned add-in prompt until signed, "what's new") block it: detect and report "waiting for you in Revit" instead of hanging. Timeout ~3 min. |
| 2 | `open_document`, `list_documents`, `activate_document` | session, approved | Open a `.rvt` by path, list open projects, switch the active one | 1 | Workshared central models: open a **local copy** (never the central file), report worksharing state. Families (`.rfa`) refused with a clear message. |
| 3 | `select_elements` / `zoom_to` | read (UI only) | Select and zoom to elements in Revit ("show me the doors without a fire rating") | 0.5 | Biggest UX win per effort: the user sees what Claude means. No model change. |
| 4 | `get_warnings` + model checks | read | Revit warnings (`Document.GetWarnings`), unplaced/unenclosed rooms, duplicate/overlapping walls, untagged doors, naming-standard checks | 1 | QA questions today's tools can't answer. |
| 5 | `modify_element` | op | Change type, parameters, offsets/heights, move by a vector, for one or many elements | 2–3 | Spec'd as COULD in §04.3. Bulk edits ("set Fire Rating = 60 min on all Level 2 doors") preview the exact per-element changes. |
| 6 | `delete_element` | op | Delete elements | 1 | Preview **must list dependants** Revit will also delete (hosted doors/windows, tags, dimensions). |
| 7 | `create_grid` | op | Straight grids with names | 0.5 | Spec'd COULD. Pairs with #9. |
| 8 | `place_family_instance` | op | Non-hosted / level- or face-based families: furniture, fixtures, equipment, generic models | 1.5–2 | Uses `search_families`; rotation, level offset; refuses if not loaded (no family loading in v1). |
| 9 | `place_column` | op | Architectural/structural columns at points or at all grid intersections | 1 | "Put columns at every grid intersection on Level 1". |
| 10 | `copy_elements` / `mirror` / `array` / copy to levels | op | Copy by offset, mirror about a line, linear array, copy a set to other levels | 2 | "Copy these walls to Levels 2–5". Re-hosting rules for doors/windows. |
| 11 | `create_view` (plan, ceiling plan, section, 3D), `set_view_overrides` | op (views) | New views; colour elements by category, type or parameter value | 2 | Colour overrides were asked for earlier ("change building colour in 3D"). |
| 12 | `create_sheet`, `place_view_on_sheet` | op | Sheets with a title block; place views | 1.5–2 | Documentation workflow. |
| 13 | `tag_elements` | op | Tag all doors/windows/rooms in a view | 1–2 | Skips already-tagged. |
| 14 | `create_schedule` + `read_schedule` | op / read | Door/window/room schedules with chosen fields; read any schedule as a table | 2 | Read side lets Claude answer "export the door schedule". |
| 15 | `export_view_image` | read (file) | Render a view to PNG and return it to Claude | 1 | Lets Claude **see** the result and check its own work. Mind image size and privacy (model content goes to Claude). |
| 16 | `export` PDF / DWG / IFC | file, approved | Export views/sheets | 1.5–2 | Writes files outside the model; path chosen by the user. |
| 17 | `place_ceiling`, `place_roof` (footprint) | op | Ceilings by room or boundary; footprint roofs with slope | 2 each | Extends §04.3 breadth. |
| 18 | `save_document` / `sync_with_central` | file, approved | Save; sync workshared models with a comment | 1 | Last on purpose: not undoable, affects other users of a central model. |

Rough total: ~25–30 days. Suggested first batch (≈ 1 week): **#1–#6**. They
remove the "open Revit first" friction, let Claude point at things, answer QA
questions and fix what it finds.

Not in this backlog (larger, separate decisions): family authoring/loading,
stairs/railings, curtain-wall layout, MEP/structural analysis, linked models,
cloud (ACC/BIM 360) models, DWG-to-BIM (see the separate track).

## Extensibility note (beyond v1)

The action-vocabulary design (typed ops behind one lifecycle) means structural/MEP (NG1) is added later by introducing new `op`s + add-in handlers — the protocol, lifecycle, and safety model are unchanged. Family authoring (NG2) and cloud/worksharing (NG3) are larger and out of this roadmap.
