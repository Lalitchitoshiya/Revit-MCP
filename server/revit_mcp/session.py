"""Locate and read session.json published by the Revit add-in (docs/06 §6.7)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Session:
    port: int
    token: str
    protocol_version: str
    revit_version: str | None
    pid: int | None
    # Where `token` came from: "session" (session.json, full access) or
    # "env"/"file" (a scoped token from REVIT_MCP_TOKEN / REVIT_MCP_TOKEN_FILE).
    token_source: str = "session"


class SessionNotFound(Exception):
    """No session file — the Revit add-in is not running."""


def session_path() -> Path:
    """%LOCALAPPDATA%\\RevitMCP\\session.json, overridable via REVIT_MCP_SESSION."""
    override = os.environ.get("REVIT_MCP_SESSION")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "RevitMCP" / "session.json"


def read_session() -> Session:
    path = session_path()
    if not path.exists():
        raise SessionNotFound(
            f"No session file at {path}. Is Revit running with the RevitMCP add-in loaded?"
        )
    # utf-8-sig tolerates a BOM (some Windows tools add one) and plain UTF-8.
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    token, source = configured_token(str(data["token"]))
    return Session(
        port=int(data["port"]),
        token=token,
        protocol_version=str(data.get("protocol_version", "")),
        revit_version=data.get("revit_version"),
        pid=data.get("pid"),
        token_source=source,
    )


def configured_token(session_token: str) -> tuple[str, str]:
    """The credential this server presents to the add-in.

    A scoped token (see revit_mcp.auth) configured per client wins over the
    full-access session token, so e.g. a reviewer's client can be read-only.
    """
    env = os.environ.get("REVIT_MCP_TOKEN", "").strip()
    if env:
        return env, "env"
    file = os.environ.get("REVIT_MCP_TOKEN_FILE", "").strip()
    if file:
        return Path(file).read_text(encoding="utf-8-sig").strip(), "file"
    return session_token, "session"
