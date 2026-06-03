# 06 — Data Models

This document defines the schemas that cross boundaries: the `Plan`/`Action` objects Claude builds, the preview/diagnostic shapes, and the unit/coordinate conventions everything depends on.

## 6.1 Units & coordinates (the contract that prevents silent disasters — NFR-9)

- **Model units** are whatever the project uses (mm, m, ft). `health_check`/`get_model_summary` report them as `units.length`.
- **Tool I/O** uses model units **by default**, and every coordinate/length object **may** carry an explicit `unit` to override. A length with no resolvable unit is a `shape_diagnostic` error at staging (FR-P2).
- **Internal Revit unit** is decimal **feet**. Conversion happens at exactly one place: the MCP server's add-in boundary (the serializer that builds the wire request). The add-in receives **feet**. Nothing downstream guesses.
- **Coordinates** are 2D `[x, y]` in the project's plan coordinate system (relative to the **project base point** reported by `get_model_summary`), plus elevation supplied separately by `level`. Z for hosted elements is derived from the level/host, not given directly in v1.
- **Angles** (where used) are degrees in I/O, radians on the wire.

```jsonc
// A length value, two accepted forms:
4000                      // number → model units
{ "value": 4.0, "unit": "m" }   // explicit
// A point:
{ "x": 1200, "y": 0 }     // model units
{ "x": {"value":4,"unit":"ft"}, "y": 0 }  // mixed allowed; each value resolved independently
```

## 6.2 Plan

A `Plan` is the unit of staging/preview/commit/undo.

```jsonc
{
  "plan": {
    "intent": "string",          // human-readable summary of user intent (for logs/preview, not executed)
    "default_unit": "mm",        // optional; applies to bare numbers in this plan
    "actions": [ Action, ... ]   // ordered; executed in order within one TransactionGroup
  }
}
```

After `stage_plan`, the server owns:

```jsonc
{
  "plan_id": "pln_01H...",        // opaque, session-scoped
  "confirmation_token": "cft_...",// one-time, required for commit (§03.3)
  "status": "staged" | "previewed" | "committed" | "undone" | "failed",
  "created_at": "<server timestamp>"
}
```

## 6.3 Action

Discriminated union on `op`. Common envelope:

```jsonc
{
  "op": "place_wall",
  "handle": "$wall1",      // optional plan-local id; lets later actions reference this one (§6.4)
  "params": { ... }        // op-specific, below
}
```

### `place_wall`
```jsonc
{ "start": Point, "end": Point, "level": Ref, "type": Ref,
  "base_offset"?: Length, "height"?: Length, "top_level"?: Ref,
  "location_line"?: "wall_centerline"|"finish_face_exterior"|... }
```
Exactly one of `height` / `top_level`. Straight walls only in v1.

### `place_door`
```jsonc
{ "host": Ref, "type": Ref,
  "distance_along"?: Length,   // measured from wall start
  "point"?: Point,             // alternative: nearest point on host
  "flip_facing"?: bool, "flip_hand"?: bool }
```
Exactly one of `distance_along` / `point`. `host` may be an existing wall `Ref` or a plan-local `handle` of a `place_wall` earlier in the same plan.

### `place_window`
```jsonc
{ "host": Ref, "type": Ref, "distance_along"?: Length, "point"?: Point,
  "sill_height"?: Length }
```

### `place_floor`  *(SHOULD)*
```jsonc
{ "boundary": [Point, ...],  // closed loop; first/last auto-closed; ≥3 points
  "level": Ref, "type": Ref, "height_offset"?: Length }
```

### `place_room`  *(SHOULD)*
```jsonc
{ "point": Point, "level": Ref, "name"?: string, "number"?: string }
```
Point must lie inside a bounded region; otherwise preview returns `ROOM_NOT_ENCLOSED`.

### `create_level`  *(SHOULD)*
```jsonc
{ "elevation": Length, "name": string }
```

### `create_grid`  *(COULD)*
```jsonc
{ "start": Point, "end": Point, "name": string }
```

### `modify_element` / `delete_element`  *(COULD)*
```jsonc
{ "id": ElementId, "changes": { "type"?: Ref, "param"?: {name, value}, ... } }
{ "id": ElementId }
```

## 6.4 References (`Ref`) and plan-local handles

A `Ref` resolves to a real model object at preview time. Accepted forms:

```jsonc
123456                          // a raw ElementId (from a discovery tool)
{ "id": 123456 }                // explicit ElementId
{ "type_name": "Generic - 200mm", "category": "walls" }  // resolved by name+category
{ "level_name": "Level 1" }     // resolved by name
{ "handle": "$wall1" }          // plan-local: another action's `handle` in THIS plan
```

- Name-based refs are resolved against the live model; ambiguity (two matches) → `error` diagnostic asking the user to choose (FR-C2).
- A `handle` ref is resolved to the `ElementId` produced when its source action commits — enabling intra-plan dependencies (door hosted on a wall created moments earlier, §03.5). At **preview**, handle refs are validated for existence/order (the source action must appear earlier and be of a compatible category) but resolve to a *projected* result rather than a real id.

## 6.5 Preview / diagnostics

```jsonc
{
  "plan_id": "pln_...",
  "overall": "ok" | "warnings" | "errors",
  "actions": [
    {
      "index": 0,
      "op": "place_wall",
      "status": "ok" | "warning" | "error",
      "resolved": { "type_id": 9876, "level_id": 311, "points_ft": [[...],[...]] },
      "preview": { "length": { "value": 4.0, "unit": "m" } },
      "diagnostics": [
        { "severity": "warning", "code": "WALL_VERY_SHORT", "message": "...", "hint": "..." }
      ]
    }
  ],
  "summary": "Would create 1 wall (4.0 m) and 1 door on Level 1."
}
```

Diagnostic `code`s (extensible): `UNKNOWN_TYPE`, `UNKNOWN_LEVEL`, `FAMILY_NOT_LOADED`, `HOST_MISSING`, `HOST_WRONG_CATEGORY`, `POINT_OUT_OF_BOUNDS`, `UNITLESS_LENGTH`, `ROOM_NOT_ENCLOSED`, `OVERLAPPING_GEOMETRY`, `AMBIGUOUS_REF`, `WALL_VERY_SHORT`. Severities: `error` (blocks commit), `warning` (informational), `info`.

## 6.6 Commit result

```jsonc
{
  "plan_id": "pln_...",
  "committed": true,
  "created": [ { "handle": "$wall1", "id": 778812, "category": "walls" },
               { "handle": null,     "id": 778813, "category": "doors" } ],
  "modified": [],
  "deleted": [],
  "transaction_group_name": "RevitMCP: <plan.intent truncated>"
}
```

The `handle`↔`id` map lets Claude refer back to created elements in subsequent turns (e.g. "now move that door").

## 6.7 Session/auth artifact (NFR-3)

Written by the add-in on startup, read by the MCP server:

```jsonc
// %LOCALAPPDATA%\RevitMCP\session.json   (restricted ACL, current user only)
{ "port": 8765, "token": "<random 256-bit hex>", "protocol_version": "1.0",
  "revit_version": "2025", "pid": 12345 }
```
The token is sent on every wire request; logs redact it (NFR-5).
