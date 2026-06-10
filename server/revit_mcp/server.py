"""MCP server exposing Revit tools to Claude (docs/04-mcp-tool-contract.md).

Phase 0: health_check. Phase 1: read-only discovery tools that ground the
conversation in the live model (get_model_summary, list_levels, list_grids,
list_types, search_families, query_elements, get_context).

Logs go to STDERR — STDOUT is reserved for the MCP stdio transport.
"""

from __future__ import annotations

import logging
import sys

from mcp.server.fastmcp import FastMCP

from . import protocol
from .addin_client import AddinClient, AddinError
from .session import SessionNotFound, read_session

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("revit_mcp.server")

mcp = FastMCP("revit-mcp")


def _err(code: str, message: str, hint: str | None = None) -> dict:
    return {"ok": False, "error": {"code": code, "message": message, "hint": hint}}


async def _call(method: str, params: dict | None = None) -> dict:
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

    try:
        async with AddinClient(session) as client:
            result = await client.request(method, params)
            return {"ok": True, "data": result}
    except AddinError as e:
        log.warning("%s failed: %s", method, e)
        return _err(e.code, e.message, e.hint)
    except Exception as e:  # noqa: BLE001 — never leak a raw stack to the model
        log.exception("%s unexpected error", method)
        return _err(protocol.ErrorCodes.INTERNAL_ERROR, str(e))


@mcp.tool()
async def health_check() -> dict:
    """Check that Revit is reachable and report its version, the open document,
    and the model's units. Call this FIRST in a session; if data.document_open
    is false, ask the user to open a project before doing anything else.
    """
    return await _call("health.check")


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
    to refer to a type precisely; never invent type names.
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
