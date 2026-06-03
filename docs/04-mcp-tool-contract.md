# 04 — MCP Tool Contract

This is the surface Claude sees. Tools are intentionally **few, deterministic, and composable**: discovery tools ground the conversation, the lifecycle tools mutate safely. Claude does the natural-language reasoning and orchestration; the tools do not.

Conventions:
- All lengths in tool I/O carry an explicit `unit` or are documented as model units; see [§06](06-data-models.md). Internally the server converts to feet at the add-in boundary.
- Every tool returns `{ ok: bool, data?, error?: { code, message, hint } }`.
- `error.code` values are enumerated in [§05 §5.5](05-addin-protocol.md).

## 4.1 Discovery tools (read-only, side-effect free — FR-D*)

### `health_check`
Confirms the full path Claude → server → add-in → Revit is alive.
- **Input:** none.
- **Output:** `{ revit_connected, document_open, document_title, revit_version, protocol_version, units: { length, area } }`.
- Call this first in a session; if `document_open` is false, stop and tell the user to open a project.

### `get_model_summary`  *(FR-D1)*
- **Input:** none.
- **Output:** project title; length/area units; project base point; `levels: [{id, name, elevation}]`; `category_counts: { walls, doors, windows, floors, rooms, grids, ... }`.

### `list_levels` / `list_grids`  *(FR-D2)*
- **Input:** none.
- **Output (levels):** `[{ id, name, elevation }]`.
- **Output (grids):** `[{ id, name, kind: "line"|"arc", start?: [x,y], end?: [x,y] }]`, plus a convenience `intersections: [{ grids: [a,b], point: [x,y] }]` to resolve "grid A-1".

### `list_types`  *(FR-D3)*
- **Input:** `{ category: "walls"|"doors"|"windows"|"floors"|"rooms"|... }`.
- **Output:** `[{ id, family_name, type_name, is_placeable }]`.

### `search_families`  *(FR-D4)*
- **Input:** `{ query: string, category?: string, limit?: number=10 }`.
- **Output:** ranked `[{ id, family_name, type_name, category, score }]`. Operates only over **loaded** families (NG2). If nothing matches, returns empty + a hint that the family may need loading.

### `query_elements`  *(FR-D5)*
- **Input:** `{ category?, level?, near_point?: [x,y], radius?, ids?: [id] }` (all optional; at least one filter recommended).
- **Output:** `[{ id, category, type_name, level, geometry_summary }]` where `geometry_summary` is category-appropriate (wall → `{ line: [[x,y],[x,y]], height }`; door → `{ host_id, location: [x,y] }`; etc.).

### `get_context`  *(FR-D6, SHOULD)*
- **Input:** none.
- **Output:** `{ selection: [id], active_view: { name, type, level? } }`. Lets Claude resolve "this wall" / "this level".

## 4.2 Mutation lifecycle tools (FR-P*)

### `stage_plan`  *(FR-P1)*
Registers a plan; does **not** touch the model.
- **Input:** `{ plan: Plan }` — see the `Plan`/`Action` schema in [§06](06-data-models.md).
- **Output:** `{ plan_id, confirmation_token, action_count, shape_diagnostics: [...] }`.
  - `shape_diagnostics` are cheap server-side checks (missing required fields, unit-less coords, references to undefined plan-local handles).
- **Note:** `confirmation_token` is opaque; it must be presented to the user and echoed back on commit. Claude must not invent it (G3, §03.3).

### `preview_plan`  *(FR-P1, FR-P2)*
Validates the staged plan **read-only** against the live model and returns what *would* happen.
- **Input:** `{ plan_id }`.
- **Output:**
  ```
  {
    plan_id,
    overall: "ok" | "warnings" | "errors",
    actions: [
      { index, op, status: "ok"|"warning"|"error",
        resolved: { type_id?, level_id?, host_id?, points?: [...] },
        preview: { /* e.g. wall length, door host point, room area */ },
        diagnostics: [ { severity, code, message, hint } ] }
    ],
    summary: "Would create 1 wall (4.0 m) and 1 door on Level 1."
  }
  ```
- `errors` block commit; `warnings` do not but should be relayed to the user.

### `commit_plan`  *(FR-P3, FR-P4, FR-P6)*
Executes a staged plan inside one transaction group. **Refused without a valid confirmation token.**
- **Input:** `{ plan_id, confirmation_token }`.
- **Output (success):** `{ plan_id, committed: true, created: [{ handle, id, category }], modified: [...], deleted: [...] }`.
- **Output (failure):** `{ ok:false, error:{ code: "ACTION_FAILED", failed_index, message } }` — model is unchanged (rolled back).
- **Pre-conditions:** plan previewed with `overall != "errors"`; token matches; document still open.

### `undo_plan`  *(FR-P5)*
- **Input:** `{ plan_id }` (defaults to the most recent committed plan if omitted).
- **Output:** `{ plan_id, undone: true }`.
- Reverts the transaction group for that plan. Errors if other operations have since made it un-targetable, with a hint to use Revit's native undo.

## 4.3 Element operation reference (what an Action can be — FR-E*)

These are not separate MCP tools; they are the `op` values inside a `Plan`'s actions (the plan is staged/previewed/committed as one unit). Full field schemas in [§06](06-data-models.md). Summary:

| `op` | Required params | Notes |
|------|-----------------|-------|
| `place_wall` | `start [x,y]`, `end [x,y]`, `level`, `type` | `base_offset?`, `height?` or `top_level?`. Straight walls v1. |
| `place_door` | `host` (wall id or plan-local handle), `type`, location (`distance_along` **or** `point`) | Hosted; `flip?`, `hand?`. |
| `place_window` | `host`, `type`, location, `sill_height?` | Hosted. |
| `place_floor` | `boundary: [[x,y],...]` (closed loop), `level`, `type` | SHOULD. |
| `place_room` | `point [x,y]`, `level`, `name?`, `number?` | SHOULD. Point must be in an enclosed region. |
| `create_level` | `elevation`, `name` | SHOULD. |
| `create_grid` | `start [x,y]`, `end [x,y]`, `name` | COULD. |
| `modify_element` | `id`, `changes: {...}` | COULD. |
| `delete_element` | `id` | COULD. |

`host` and references between actions in the same plan use **plan-local handles** (e.g. `"$wall1"`) so a door can reference a wall created earlier in the same plan before it has a real `ElementId` (§06).

## 4.4 What the tools deliberately do NOT do

- **No free-form "do what I mean" tool.** There is no `execute_natural_language(text)` endpoint. Claude must translate intent into an explicit `Plan` of typed actions — this is what makes the system inspectable and deterministic (G2).
- **No silent writes.** Every mutation goes through stage→preview→commit. There is no direct "create wall now" tool.
- **No invented data.** Tools resolve references against the live model and reject what doesn't exist.

## 4.5 Expected Claude usage pattern (guidance, encoded in tool descriptions)

1. `health_check` → ensure a document is open.
2. Use discovery tools to ground every type/level/family/coordinate the user's intent implies.
3. If anything is ambiguous, ask the user (FR-C2) — do not guess.
4. `stage_plan` → `preview_plan`. Relay the preview summary + warnings to the user.
5. Ask the user to confirm; on confirmation, `commit_plan` with the token.
6. Report the result; offer `undo_plan`.
