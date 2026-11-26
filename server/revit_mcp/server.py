"""MCP server exposing Revit tools to Claude (docs/04-mcp-tool-contract.md).

Phase 0: health_check. Phase 1: read-only discovery tools that ground the
conversation in the live model (get_model_summary, list_levels, list_grids,
list_types, search_families, query_elements, get_context). Phase 2+: the
stage -> preview -> approve -> commit -> undo lifecycle.

Governance: human approval of commit/undo is requested by THIS server via MCP
elicitation (the model cannot answer it), forwarded to the add-in, and written
to the add-in's hash-chained audit log. Access is gated by scoped tokens
(revit_mcp.auth), enforced in the add-in and pre-checked here.

Logs go to STDERR — STDOUT is reserved for the MCP stdio transport.
"""

from __future__ import annotations

import getpass
import logging
import os
import secrets
import sys
import time
from datetime import datetime, timezone

import mcp.types as mcp_types
from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, Field

from . import __version__, audit, auth, protocol
from .addin_client import AddinClient, AddinError
from .session import Session, SessionNotFound, read_session

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("revit_mcp.server")

mcp = FastMCP("revit-mcp")


def _err(code: str, message: str, hint: str | None = None) -> dict:
    return {"ok": False, "error": {"code": code, "message": message, "hint": hint}}


async def _call(method: str, params: dict | None = None,
                timeout: float = protocol.REQUEST_TIMEOUT_S) -> dict:
    """Connect to the add-in, invoke one method, and wrap the result.

    Centralises session lookup, connection, and graceful error handling (NFR-7)
    so every tool returns a uniform {ok, data|error} shape.
    """
    try:
        session = read_session()
    except SessionNotFound as e:
        log.warning("no session file: %s", e)
        return _err(protocol.ErrorCodes.NO_SESSION_FILE, str(e),
                    "Open Revit with the RevitMCP add-in installed, then retry.")

    denied = _precheck_scope(session, method)
    if denied is not None:
        return denied

    try:
        async with AddinClient(session) as client:
            result = await client.request(method, params, timeout=timeout)
            return {"ok": True, "data": result}
    except AddinError as e:
        log.warning("%s failed: %s", method, e)
        return _err(e.code, e.message, e.hint)
    except Exception as e:  # noqa: BLE001 — never leak a raw stack to the model
        log.exception("%s unexpected error", method)
        return _err(protocol.ErrorCodes.INTERNAL_ERROR, str(e))


def _precheck_scope(session: Session, method: str) -> dict | None:
    """Fail fast (with a useful hint) when the configured token obviously can't
    call `method`. UX only — the add-in re-verifies signature, expiry, revocation
    and scope on every request and is the real enforcement point."""
    claims = auth.decode_unverified(session.token)
    if claims is None:
        return None  # legacy session token: full access, add-in decides
    if time.time() >= claims.get("exp", 0):
        return _err("TOKEN_EXPIRED", f"The configured access token ({claims.get('sub')}) has expired.",
                    "Issue a new one: revit-mcp-server auth issue ... (developer: python -m revit_mcp.auth issue)")
    need = auth.required_scope(method)
    if need not in claims.get("scopes", []):
        return _err("SCOPE_DENIED",
                    f"This client's token ({claims.get('sub')}) has scopes {claims.get('scopes')}; "
                    f"'{method}' needs '{need}'.",
                    "This client is not allowed to change the model. Ask the user to make the change "
                    "from a client holding a model:write token.")
    return None


def _access_info() -> dict:
    """What the configured credential allows (decoded, unverified — for display)."""
    try:
        session = read_session()
    except Exception:  # noqa: BLE001
        return {"token_source": None}
    claims = auth.decode_unverified(session.token)
    if claims is None:
        return {"token_source": session.token_source, "kind": "session",
                "sub": "session", "scopes": list(auth.ALL_SCOPES), "expires_at": None}
    return {"token_source": session.token_source, "kind": "scoped", "sub": claims.get("sub"),
            "scopes": claims.get("scopes"), "jti": claims.get("jti"),
            "expires_at": datetime.fromtimestamp(claims.get("exp", 0), timezone.utc).isoformat()}


@mcp.tool()
async def health_check() -> dict:
    """Check that Revit is reachable and report its version, the open document,
    and the model's units. Call this FIRST in a session; if data.document_open
    is false, ask the user to open a project before doing anything else.
    `data.access` shows what this client may do (scopes, expiry) and
    `data.approval_mode` how commits are approved.
    """
    result = await _call("health.check")
    if result.get("ok"):
        result["data"]["server_version"] = __version__
        result["data"]["access"] = _access_info()
        result["data"]["approval_mode"] = _approval_mode()
    return result


@mcp.tool()
async def get_model_summary() -> dict:
    """Summarise the open model: project title, units, project base point,
    the list of levels (name + elevation), and element counts per category.
    Use this to ground a conversation before referencing levels or counts.
    """
    return await _call("model.summary")


@mcp.tool()
async def list_levels() -> dict:
    """List the model's levels (id, name, elevation in model units), sorted by
    elevation. Use the returned ids/names when a request refers to a level.
    """
    return await _call("levels.list")


@mcp.tool()
async def list_grids() -> dict:
    """List the model's grids (id, name, endpoints) plus computed intersections
    of non-parallel linear grids, so a reference like "grid A-1" resolves to a
    point.
    """
    return await _call("grids.list")


@mcp.tool()
async def list_types(category: str) -> dict:
    """List available types for a category, e.g. "walls", "doors", "windows",
    "floors", "rooms". Returns id, family_name, type_name. Use the returned ids
    to refer to a type precisely; never invent type names. The same type_name can
    appear under different families — when a name is ambiguous, reference the type
    by `id`, and if intent is unclear ask the user which one.
    """
    return await _call("types.list", {"category": category})


@mcp.tool()
async def search_families(query: str, category: str | None = None, limit: int = 10) -> dict:
    """Search LOADED families/types by keyword (e.g. "single flush door"),
    optionally constrained to a category. Returns ranked matches. If empty, the
    family likely needs loading into the project first.
    """
    params: dict = {"query": query, "limit": limit}
    if category is not None:
        params["category"] = category
    return await _call("families.search", params)


@mcp.tool()
async def query_elements(
    category: str | None = None,
    level: str | None = None,
    ids: list[int] | None = None,
    near_point: list[float] | None = None,
    radius: float | None = None,
    limit: int = 200,
) -> dict:
    """Query existing elements, filtered by any combination of category, level
    name, explicit ids, or proximity (near_point [x,y] + radius, in model units).
    Returns id, category, type_name, level, and a geometry summary per element.
    Provide at least one filter; results are capped at `limit`.

    For spatial language ("the north wall", "the wall on the left"), use each
    wall's geometry (line endpoints + `facing.cardinal`) to identify the right
    element. If more than one element plausibly matches, list the candidates and
    ASK the user which one — do not guess silently.
    """
    params: dict = {"limit": limit}
    if category is not None:
        params["category"] = category
    if level is not None:
        params["level"] = level
    if ids:
        params["ids"] = ids
    if near_point is not None:
        params["near_point"] = near_point
    if radius is not None:
        params["radius"] = radius
    return await _call("elements.query", params)


@mcp.tool()
async def get_context() -> dict:
    """Return the user's current Revit selection and active view (name, type,
    associated level). Use this to resolve relative phrases like "this wall" or
    "on this level".
    """
    return await _call("context.get")


# --------------------------------------------------------------------------- #
# Phase 2: stage -> preview -> commit -> undo mutation lifecycle (docs/03 §3.3)
# --------------------------------------------------------------------------- #
#
# The plan registry and confirmation enforcement live HERE, in the server. The
# add-in receives a fully-formed plan on preview/commit and performs the actual,
# transactional model changes. A commit is REFUSED unless (1) it carries the
# confirmation_token issued at staging, (2) the plan was previewed without
# errors, (3) it has not already been committed (single-use), and (4) a HUMAN
# approves it through an MCP elicitation prompt raised by this server (see
# _approval_mode) — the model cannot answer that prompt. The add-in separately
# refuses un-previewed/changed plans, enforces token scope, and writes the audit.

_plans: dict[str, dict] = {}
_last_committed: str | None = None


def _shape_diagnostics(plan: dict) -> list[dict]:
    """Cheap server-side checks before bothering Revit (docs/04 §4.2)."""
    diags: list[dict] = []
    actions = plan.get("actions")
    if not isinstance(actions, list) or not actions:
        diags.append({"severity": "error", "code": "MISSING_FIELD",
                      "message": "plan.actions must be a non-empty list."})
        return diags
    for i, a in enumerate(actions):
        op = a.get("op")
        params = a.get("params", {})
        if not op:
            diags.append({"severity": "error", "code": "MISSING_FIELD",
                          "message": f"action {i}: missing 'op'."})
            continue
        if op == "place_wall":
            for field in ("start", "end", "level", "type"):
                if field not in params:
                    diags.append({"severity": "error", "code": "MISSING_FIELD",
                                  "message": f"action {i} (place_wall): missing params.{field}."})
    return diags


@mcp.tool()
async def stage_plan(plan: dict) -> dict:
    """Register a placement plan WITHOUT touching the model, and get back a
    plan_id plus a confirmation_token required to commit later.

    A plan is: {"intent": str, "default_unit"?: str,
                "actions": [{"op": "place_wall", "handle"?: "$w1",
                             "params": {"start": [x,y], "end": [x,y],
                                        "level": {"level_name": "Level 1"},
                                        "type": {"type_name": "Interior - Partition",
                                                 "category": "walls"},
                                        "height"?: 3000, "base_offset"?: 0}}]}
    Coordinates/lengths are in the MODEL's units (call get_model_summary first);
    or pass {"value": n, "unit": "mm|cm|m|ft|in"}. Reference levels/types by the
    exact names from list_levels/list_types — never invent them.

    A single plan can contain MANY actions and is committed atomically — compose
    a compound request ("a 4x3 m room with a door") into ONE plan, using $handles
    so a door can be hosted on a wall created earlier in the same plan.

    Ground every reference in discovery results (list_levels/list_types/
    query_elements) — never invent names. If a reference is ambiguous or the
    intent is unclear, ASK the user rather than guessing.

    NEXT: call preview_plan(plan_id), show the user the summary AND any warnings,
    then call commit_plan — the server itself asks the user to approve.
    """
    plan_id = "pln_" + secrets.token_hex(5)
    token = "cft_" + secrets.token_hex(8)
    _plans[plan_id] = {"plan": plan, "token": token, "previewed": False, "plan_hash": None,
                       "summary": None, "warnings": [], "status": "staged"}
    diags = _shape_diagnostics(plan)
    log.info("staged %s (%d actions, %d shape diagnostics)",
             plan_id, len(plan.get("actions", [])), len(diags))
    return {"ok": True, "data": {
        "plan_id": plan_id,
        "confirmation_token": token,
        "action_count": len(plan.get("actions", [])),
        "shape_diagnostics": diags,
    }}


@mcp.tool()
async def preview_plan(plan_id: str) -> dict:
    """Validate a staged plan READ-ONLY against the live model and report what
    would happen (per-action diagnostics + a summary). Nothing is modified.

    `overall` is "ok", "warnings", or "errors". Always relay the summary and any
    warnings to the user before committing. If overall is "errors", the plan
    cannot commit — fix the offending references (e.g. an AMBIGUOUS_REF lists the
    candidate ids; a HOST_WRONG_CATEGORY means the host isn't a wall) or ask the
    user, then stage and preview again.
    """
    entry = _plans.get(plan_id)
    if entry is None:
        return _err("PLAN_NOT_FOUND", f"No staged plan '{plan_id}'.", "Call stage_plan first.")

    result = await _call("plan.preview", {"plan_id": plan_id, "plan": entry["plan"]})
    if result.get("ok"):
        data = result["data"]
        entry["plan_hash"] = data.get("plan_hash")
        entry["previewed"] = data.get("overall") != "errors"
        entry["summary"] = data.get("summary")
        entry["warnings"] = [d.get("message") for a in data.get("actions", [])
                             for d in a.get("diagnostics", []) if d.get("severity") == "warning"]
    return result


class _ApprovalForm(BaseModel):
    approve: bool = Field(description="Approve this change to the Revit model?")
    comment: str = Field(default="", description="Optional note for the audit log")


def _approval_mode() -> str:
    """REVIT_MCP_APPROVAL:
    - "elicit"          the server asks the human; a client that can't show the
                        prompt cannot commit (strongest — use for demo/production)
    - "elicit_or_token" (default) ask the human when the client supports it,
                        otherwise fall back to the confirmation token alone and
                        record the approval as NOT human-verified
    - "token"           legacy: confirmation token only (not human-verified)
    """
    mode = os.environ.get("REVIT_MCP_APPROVAL", "elicit_or_token").strip().lower()
    return mode if mode in ("elicit", "elicit_or_token", "token") else "elicit_or_token"


def _client_can_elicit(ctx: Context | None) -> bool:
    if ctx is None:
        return False
    try:
        return ctx.session.check_client_capability(
            mcp_types.ClientCapabilities(elicitation=mcp_types.ElicitationCapability()))
    except Exception:  # noqa: BLE001 — no request context (direct call from a script)
        return False


def _client_name(ctx: Context | None) -> str | None:
    try:
        info = ctx.session.client_params.clientInfo  # type: ignore[union-attr]
        return f"{info.name} {info.version}".strip()
    except Exception:  # noqa: BLE001
        return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


async def _obtain_approval(ctx: Context | None, prompt: str) -> tuple[dict | None, dict | None]:
    """Ask the HUMAN (not the model) to approve. Returns (approval, error)."""
    mode = _approval_mode()
    base = {"approved_by": getpass.getuser(), "client": _client_name(ctx), "mode": mode,
            "prompt": prompt}

    if mode != "token" and _client_can_elicit(ctx):
        result = await ctx.elicit(prompt, _ApprovalForm)  # type: ignore[union-attr]
        if result.action == "accept" and result.data.approve:
            return {**base, "method": "elicitation", "human_verified": True,
                    "approved_at": _utc_now(), "comment": result.data.comment or None}, None
        log.info("approval not given (%s)", result.action)
        return None, _err("APPROVAL_DECLINED", "The user did not approve this change; nothing was modified.",
                          "Ask the user what they would like to change, then stage a new plan.")

    if mode == "elicit":
        return None, _err("APPROVAL_UNAVAILABLE",
                          "This server requires human approval via an approval prompt, but the connected "
                          "client cannot display one. Nothing was modified.",
                          "Use a client that supports MCP elicitation (e.g. Claude Code), or set "
                          "REVIT_MCP_APPROVAL=elicit_or_token.")
    return {**base, "method": "confirmation_token", "human_verified": False,
            "approved_at": _utc_now(), "comment": None}, None


def _precheck_configured(method: str) -> dict | None:
    try:
        return _precheck_scope(read_session(), method)
    except Exception:  # noqa: BLE001 — no session: _call reports it properly
        return None


@mcp.tool()
async def commit_plan(plan_id: str, confirmation_token: str, ctx: Context = None) -> dict:  # type: ignore[assignment]
    """Commit a previewed plan to the model in ONE undoable transaction.
    REFUSED unless confirmation_token matches the one from stage_plan. Before
    committing, the SERVER shows the user an approval prompt with the previewed
    summary; the change is applied only if they approve it there. On
    APPROVAL_DECLINED nothing changed — ask the user what to adjust. Each plan
    commits at most once. Returns the created element ids.
    """
    global _last_committed
    entry = _plans.get(plan_id)
    if entry is None:
        return _err("PLAN_NOT_FOUND", f"No staged plan '{plan_id}'.")
    if entry["status"] == "committed":
        return _err("PLAN_ALREADY_COMMITTED", f"Plan '{plan_id}' was already committed.",
                    "Stage a new plan for further changes.")
    if confirmation_token != entry["token"]:
        return _err("CONFIRMATION_REQUIRED",
                    "Missing or invalid confirmation token.",
                    "Commit only after the user approves the preview; pass the token from stage_plan.")
    if not entry["previewed"]:
        return _err("PLAN_NOT_PREVIEWED", "Preview the plan (without errors) before committing.",
                    "Call preview_plan first.")
    # Don't ask a human to approve something this client isn't allowed to do.
    denied = _precheck_configured("plan.commit")
    if denied is not None:
        return denied

    plan = entry["plan"]
    lines = ["Approve this change to the Revit model?",
             f"Intent: {plan.get('intent') or '(none given)'}",
             f"Preview: {entry.get('summary') or str(len(plan.get('actions', []))) + ' action(s)'}"]
    if entry.get("warnings"):
        lines.append("Warnings: " + "; ".join(entry["warnings"][:5]))
    lines.append(f"Plan {plan_id} - applied as one undoable step.")
    approval, error = await _obtain_approval(ctx, "\n".join(lines))
    if error is not None:
        return error

    result = await _call("plan.commit", {
        "plan_id": plan_id,
        "plan_hash": entry["plan_hash"],
        "plan": plan,
        "approval": approval,
        "summary": entry.get("summary"),
    }, timeout=protocol.COMMIT_TIMEOUT_S)
    if result.get("ok"):
        entry["status"] = "committed"
        _last_committed = plan_id
        result["data"]["summary"] = _summarize_created(result["data"].get("created", []))
        result["data"]["approval"] = {k: approval[k] for k in ("method", "human_verified", "approved_by")}
    return result


_NOUNS = {"walls": "wall", "doors": "door", "windows": "window",
          "floors": "floor", "rooms": "room", "levels": "level"}


def _summarize_created(created: list[dict]) -> str:
    """Human one-liner from the created elements, e.g. 'Created 4 walls, 1 door.'"""
    counts: dict[str, int] = {}
    for c in created:
        cat = (c.get("category") or "element").lower()
        counts[cat] = counts.get(cat, 0) + 1
    if not counts:
        return "Created nothing."
    parts = []
    for cat, n in counts.items():
        noun = _NOUNS.get(cat, cat.rstrip("s") or cat)
        parts.append(f"{n} {noun}{'' if n == 1 else 's'}")
    return "Created " + ", ".join(parts) + "."


@mcp.tool()
async def undo_plan(plan_id: str | None = None, ctx: Context = None) -> dict:  # type: ignore[assignment]
    """Undo a committed plan, removing the elements it created. Defaults to the
    most recently committed plan when plan_id is omitted. The server asks the
    user to approve the removal first (it deletes elements — and anything Revit
    hosts on them, e.g. doors a user later placed on those walls).
    """
    global _last_committed
    target = plan_id or _last_committed
    if target is None:
        return _err("PLAN_NOT_FOUND", "No committed plan to undo.")
    denied = _precheck_configured("plan.undo")
    if denied is not None:
        return denied
    entry = _plans.get(target) or {}
    what = entry.get("summary") or "the elements created by that plan"
    approval, error = await _obtain_approval(
        ctx, f"Approve UNDO of plan {target}?\nThis removes: {what}\n"
             "(plus anything Revit hosts on those elements).")
    if error is not None:
        return error
    result = await _call("plan.undo", {"plan_id": target, "approval": approval,
                                       "summary": f"Undo: {what}"},
                         timeout=protocol.COMMIT_TIMEOUT_S)
    if result.get("ok"):
        n = result["data"].get("deleted_count")
        result["data"]["summary"] = f"Reverted plan {target}: removed {n} element(s)."
        if entry:
            entry["status"] = "undone"
        if _last_committed == target:
            _last_committed = None
    return result


@mcp.tool()
async def get_audit_log(limit: int = 10) -> dict:
    """Show recent entries of the local approval audit log: who approved each
    model change, when, how (human-verified prompt vs token only), what was
    created/removed, and which access token was used. Also reports whether the
    log's tamper-evident hash chain is intact.
    """
    ok, n, msg = audit.verify()
    recs = audit.tail(max(1, min(limit, 100)))
    return {"ok": True, "data": {
        "path": str(audit.audit_path()),
        "chain_intact": ok, "chain_message": msg, "total_records": n,
        "entries": [{"line": audit.summarize(r), "record": r} for r in recs],
    }}
