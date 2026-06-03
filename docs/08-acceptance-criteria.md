# 08 — Acceptance Criteria

End-to-end scenarios that define "done". Each maps to requirements ([§02](02-requirements.md)) and a roadmap phase ([§07](07-roadmap.md)). Format: **Given / When / Then**. These double as the manual + automated test charter.

## Reference fixture

All scenarios run against **`reference.rvt`**: a small project with Levels 1–3, grids A–D × 1–4, wall types incl. "Generic - 200mm", a loaded "Single-Flush" door family and a "Fixed" window family, units = **millimetres**. Latency targets (NFR-6) are measured here.

---

## Discovery (Phase 1)

### AC-D1 — Model summary *(FR-D1)*
- **Given** `reference.rvt` open and the add-in loaded.
- **When** Claude calls `health_check` then `get_model_summary`.
- **Then** it reports units = mm, Levels 1–3 with correct elevations, and non-zero counts for walls/grids — all matching the live model; p50 < 1.5 s.

### AC-D2 — Type listing is grounded *(FR-D3, FR-C1)*
- **When** the user asks "what wall types can I use?"
- **Then** Claude lists only types returned by `list_types("walls")` — including "Generic - 200mm" — and invents none.

### AC-D3 — Family search *(FR-D4)*
- **When** the user asks "do I have a single door loaded?"
- **Then** `search_families("single door", category:"doors")` returns the "Single-Flush" family and Claude reports it; for a not-loaded family it reports "not loaded" with the load hint (no crash).

### AC-D4 — Query existing elements *(FR-D5)*
- **Given** ≥1 wall on Level 1.
- **When** the user asks "what walls are on Level 1?"
- **Then** Claude returns ids + location lines + height from `query_elements`, matching the model.

---

## Single-wall lifecycle (Phase 2) — the safety spine

### AC-W1 — Happy path with confirmation *(FR-P1,P3,P4, FR-E1)*
- **When** the user says "add a 4 m Generic 200 mm wall on Level 1 from (0,0) running east", Claude grounds the type/level, `stage_plan`s, `preview_plan`s.
- **Then** the preview summary says "Would create 1 wall (4.0 m) on Level 1", model is **unchanged**.
- **And** only after the user confirms and Claude calls `commit_plan` with the token does exactly one wall appear, with the correct length/level/type. Created id returned.

### AC-W2 — No write without confirmation *(FR-P4 — hard requirement)*
- **When** Claude attempts `commit_plan` without the `confirmation_token` (or with a wrong one).
- **Then** the call is refused with `CONFIRMATION_REQUIRED` and the model is unchanged. **(0 unconfirmed mutations — must hold across the whole suite.)**

### AC-W3 — Atomic undo *(FR-P5)*
- **Given** a committed wall from AC-W1.
- **When** the user says "undo that" and Claude calls `undo_plan`.
- **Then** the wall is removed in a single step and the model returns to its prior state.

### AC-W4 — Bad reference caught at preview *(FR-P2, grounding metric)*
- **When** a plan references wall type "Concrete 999 mm" (not in the model).
- **Then** `preview_plan` returns `overall:"errors"` with `UNKNOWN_TYPE` on that action, `commit_plan` is blocked, and **nothing** reaches the model.

### AC-W5 — Unitless coordinate rejected *(FR-P2, NFR-9)*
- **When** a plan contains a length with no resolvable unit in an mm-defaulted plan that omits `default_unit` and uses a bare value flagged ambiguous.
- **Then** staging/preview flags `UNITLESS_LENGTH` and blocks commit.

---

## Element breadth (Phase 3)

### AC-M1 — Hosted door, single plan *(FR-E2, §03.5)*
- **When** the user says "add that wall and put a single door 1 m from its start", Claude builds **one** plan with `place_wall` (`handle:"$w"`) + `place_door` (`host:{handle:"$w"}`).
- **Then** preview validates the door type is loaded and the host handle resolves; on confirm+commit, both are created in **one** `TransactionGroup`; the door is hosted on the new wall at 1.0 m; one `undo_plan` removes **both**.

### AC-M2 — Window with sill *(FR-E3)*
- **When** "add a fixed window centred on wall X with 900 mm sill".
- **Then** the window is hosted at the wall midpoint with sill height 900 mm.

### AC-M3 — Missing host rejected *(FR-P2)*
- **When** a `place_door` references a host id that is a floor (wrong category) or doesn't exist.
- **Then** preview returns `HOST_WRONG_CATEGORY` / `HOST_MISSING` and blocks commit.

### AC-M4 — Floor from boundary *(FR-E4, SHOULD)*
- **When** "make a 4×3 m floor at the origin on Level 1".
- **Then** a floor with the correct closed boundary and area is previewed and (on confirm) created.

### AC-M5 — Atomic rollback on mid-plan failure *(FR-P6)*
- **Given** a 3-action plan whose 3rd action will throw (e.g. invalid geometry that slips past preview).
- **When** `commit_plan` runs.
- **Then** the entire `TransactionGroup` is rolled back, `ACTION_FAILED` with `failed_index:2` is returned, and **none** of the 3 elements persist.

---

## Orchestration & UX (Phase 4)

### AC-C1 — Ambiguity triggers a question, not a guess *(FR-C2)*
- **Given** two walls plausibly matching "the north wall".
- **When** the user says "put a door on the north wall".
- **Then** Claude surfaces both candidates (ids/locations) and asks the user to choose; it does **not** silently pick one.

### AC-C2 — Compound request → one coherent plan *(FR-C3, FR-C4)*
- **When** "create a 4×3 m room enclosed by four 200 mm walls on Level 1 with a door on the south wall".
- **Then** Claude grounds all types, stages **one** plan (4 walls + door, using handles), previews it as a whole, and after confirm reports a concise summary ("Created 4 walls, 1 door on Level 1; say 'undo' to revert").

---

## Resilience (Phase 5)

### AC-R1 — Revit closed
- **When** Revit is not running and any tool is called.
- **Then** a clear "Revit not reachable" error returns within the timeout; no hang.

### AC-R2 — No active document
- **When** Revit is open with no project document and a tool is called.
- **Then** `NO_ACTIVE_DOCUMENT` with a hint to open a project.

### AC-R3 — Revit busy (modal dialog)
- **When** a modal dialog is open in Revit during a tool call.
- **Then** the call returns `REVIT_BUSY_TIMEOUT` within the bounded wait; no deadlock; subsequent calls work once the dialog closes.

### AC-R4 — Version mismatch
- **When** the MCP server's protocol major version ≠ the add-in's.
- **Then** the handshake fails with `VERSION_INCOMPATIBLE`; no tools are offered as working.

### AC-R5 — Preview/commit drift
- **When** the plan sent to `plan.commit` differs from the previewed plan.
- **Then** the add-in returns `PLAN_CHANGED_SINCE_PREVIEW` and commits nothing.

---

## Cross-cutting invariants (must hold in every scenario)

| Invariant | Source |
|-----------|--------|
| No model mutation occurs without a valid, user-originated confirmation token. | FR-P4, success metric "Safety = 0" |
| Every committed plan is revertible by one `undo_plan`. | FR-P5 |
| No plan references a type/level/family/host that isn't in the live model at commit. | FR-C1, grounding metric |
| Every mutating commit is exactly one `TransactionGroup` (atomic). | NFR-2, FR-P6 |
| No Revit API call occurs off the UI thread. | NFR-1 |
| Every tool call is logged with a correlation id; tokens redacted. | NFR-5 |
