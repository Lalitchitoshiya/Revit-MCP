"""MCP server exposing Revit tools to Claude (docs/04-mcp-tool-contract.md).

Phase 0 surface: a single `health_check` tool that proves the full path
Claude → MCP server → add-in → Revit UI thread → back, with graceful failures
(NFR-7) and per-request logging (NFR-5). Logs go to STDERR — STDOUT is reserved
for the MCP stdio transport.
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


@mcp.tool()
async def health_check() -> dict:
    """Check that Revit is reachable and report its version, the open document,
    and the model's units. Call this first in a session; if `document_open` is
    false, ask the user to open a project before doing anything else.

    Returns a dict with `ok`. On success, `data` holds revit_connected,
    revit_version, document_open, document_title, protocol_version, and units.
    On failure, `error` holds a code/message/hint explaining what to fix.
    """
    try:
        session = read_session()
    except SessionNotFound as e:
        log.warning("no session file: %s", e)
        return _err(protocol.ErrorCodes.NO_SESSION_FILE, str(e),
                    "Open Revit with the RevitMCP add-in installed, then retry.")

    try:
        async with AddinClient(session) as client:
            result = await client.request("health.check")
            log.info("health_check ok: revit=%s doc_open=%s",
                     result.get("revit_version"), result.get("document_open"))
            return {"ok": True, "data": result, "welcome": client.welcome}
    except AddinError as e:
        log.warning("health_check failed: %s", e)
        return _err(e.code, e.message, e.hint)
    except Exception as e:  # noqa: BLE001 — never leak a raw stack to the model
        log.exception("health_check unexpected error")
        return _err(protocol.ErrorCodes.INTERNAL_ERROR, str(e))


def _err(code: str, message: str, hint: str | None = None) -> dict:
    return {"ok": False, "error": {"code": code, "message": message, "hint": hint}}
