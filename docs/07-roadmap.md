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

## Extensibility note (beyond v1)

The action-vocabulary design (typed ops behind one lifecycle) means structural/MEP (NG1) is added later by introducing new `op`s + add-in handlers — the protocol, lifecycle, and safety model are unchanged. Family authoring (NG2) and cloud/worksharing (NG3) are larger and out of this roadmap.
