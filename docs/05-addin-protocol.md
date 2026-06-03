# 05 — Add-in Wire Protocol

The protocol between the **Python MCP server** (client) and the **C# Revit add-in** (server). It is deliberately small and JSON-RPC-flavoured.

## 5.1 Transport

- **TCP**, bound to `127.0.0.1` only (NFR-3). Port is published in `session.json` (§06.7).
- **Framing:** one JSON object per line, UTF-8, terminated by `\n` (newline-delimited JSON). Rationale: trivial to implement on both sides, easy to log.
- **One client at a time.** The MCP server is the sole client. A second connection is refused.
- **Bounded timeouts** on every request (NFR-7): the client waits at most `request_timeout_ms` (default 30 000; commits may use a larger ceiling) before returning `REVIT_BUSY_TIMEOUT`.

## 5.2 Handshake (on connect — NFR-8)

First message from client:
```jsonc
{ "type": "hello", "protocol_version": "1.0", "token": "<from session.json>" }
```
Add-in replies:
```jsonc
{ "type": "welcome", "protocol_version": "1.0", "revit_version": "2025",
  "document_open": true, "document_title": "Project1.rvt" }
// or
{ "type": "error", "code": "VERSION_INCOMPATIBLE" | "BAD_TOKEN" }
```
Mismatched major protocol version or bad token → connection closed.

## 5.3 Request / response

Request:
```jsonc
{ "id": "req-7", "token": "<token>", "method": "types.list",
  "params": { "category": "walls" } }
```
Response (success):
```jsonc
{ "id": "req-7", "ok": true, "result": { ... } }
```
Response (error):
```jsonc
{ "id": "req-7", "ok": false,
  "error": { "code": "NO_ACTIVE_DOCUMENT", "message": "...", "hint": "..." } }
```
- `id` echoes the request for correlation (NFR-5).
- `token` is revalidated per request (defence in depth).
- Geometry in params is in **feet/radians** — the MCP server has already converted (§06.1).

## 5.4 Methods (map to MCP tools / actions)

| Method | Backs | Mutating? | Notes |
|--------|-------|-----------|-------|
| `health.check` | `health_check` | no | Returns version, doc state, units. |
| `model.summary` | `get_model_summary` | no | |
| `levels.list` / `grids.list` | `list_levels`/`list_grids` | no | grids include computed intersections. |
| `types.list` | `list_types` | no | by category. |
| `families.search` | `search_families` | no | ranked, loaded families only. |
| `elements.query` | `query_elements` | no | by category/level/region/ids. |
| `context.get` | `get_context` | no | selection + active view. |
| `plan.preview` | `preview_plan` | **no (read-only)** | resolves refs, computes preview, no transaction left open. |
| `plan.commit` | `commit_plan` | **yes** | one `TransactionGroup`; atomic (§03.3, FR-P6). |
| `plan.undo` | `undo_plan` | **yes** | rolls back a committed group. |

> Note: `stage_plan`/`confirmation_token` logic lives in the **MCP server**, not the add-in. The add-in receives the fully-formed plan on `plan.preview` and `plan.commit`. The add-in trusts the server's confirmation enforcement but still requires the plan to have passed `plan.preview` (it tracks previewed plan hashes) before `plan.commit`.

### `plan.preview` params
```jsonc
{ "plan": { "intent": "...", "actions": [ /* actions with refs resolved to feet */ ] } }
```
### `plan.commit` params
```jsonc
{ "plan_hash": "<hash returned by preview>", "plan": { ...same plan... } }
```
The add-in recomputes the hash and rejects a commit whose plan differs from what was previewed (`PLAN_CHANGED_SINCE_PREVIEW`) — preventing a preview/commit mismatch.

## 5.5 Error codes (canonical)

| Code | Meaning |
|------|---------|
| `BAD_TOKEN` | Missing/invalid auth token. |
| `VERSION_INCOMPATIBLE` | Protocol major version mismatch. |
| `NO_ACTIVE_DOCUMENT` | No project document open in Revit. |
| `REVIT_BUSY_TIMEOUT` | UI thread not serviced within timeout (modal dialog, long op). |
| `UNKNOWN_METHOD` | Method not recognised. |
| `INVALID_PARAMS` | Params failed schema validation. |
| `UNKNOWN_TYPE` / `UNKNOWN_LEVEL` / `FAMILY_NOT_LOADED` | Reference resolution failed (also appear as preview diagnostics). |
| `HOST_MISSING` / `HOST_WRONG_CATEGORY` | Hosted element's host invalid. |
| `AMBIGUOUS_REF` | A name-based ref matched >1 element. |
| `ROOM_NOT_ENCLOSED` | Room point not inside a bounded region. |
| `ACTION_FAILED` | An action threw during commit; group rolled back. Includes `failed_index`. |
| `PLAN_NOT_PREVIEWED` / `PLAN_CHANGED_SINCE_PREVIEW` | Commit hygiene violations. |
| `PLAN_NOT_FOUND` | Unknown plan id (server-side). |
| `CONFIRMATION_REQUIRED` | Commit attempted without valid confirmation token (server-side). |
| `INTERNAL_ERROR` | Unexpected add-in exception (message included, stack logged). |

## 5.6 Threading contract (restates §03.2 as the add-in's obligation)

- The socket listener thread MUST NOT call any `Autodesk.Revit.*` API.
- Each request that needs the model is enqueued and run inside the single `IExternalEventHandler.Execute`, on the UI thread, in a valid API context.
- `plan.commit` opens exactly one `TransactionGroup`; each action runs in its own `Transaction`; `Assimilate()` on full success, `RollBack()` (group) on any failure.
- `plan.preview` performs no committed transaction; if it must use a transaction to measure geometry, that transaction is always rolled back, leaving the model unchanged.

## 5.7 Logging (NFR-5)

Both sides log per request: `id`, `method`, `plan_id`/`plan_hash`, duration_ms, outcome (`ok`/error code). The `token` field is always redacted. Add-in additionally logs Revit exception details on `ACTION_FAILED`/`INTERNAL_ERROR`.

## 5.8 Versioning

`protocol_version` is `MAJOR.MINOR`. Same MAJOR = compatible (additive MINOR changes allowed); differing MAJOR = refuse to connect. The MCP server and add-in ship their supported version; mismatch surfaces as `VERSION_INCOMPATIBLE` at handshake (NFR-8).
