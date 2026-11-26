"""Support diagnostics: is everything wired up on this PC?

    revit-mcp-server doctor        (developer: python -m revit_mcp doctor)

Read-only. Checks the session file, a live health.check against the Revit
add-in, Claude registration, the access policy and the audit chain, and prints
one line per check. Exit code 0 when Revit is reachable, 1 otherwise.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from . import __version__, audit, auth, clients
from .addin_client import AddinClient, AddinError
from .session import SessionNotFound, read_session, session_path


def _line(ok: bool | None, what: str, detail: str) -> None:
    mark = {True: "ok", False: "!!", None: "--"}[ok]
    print(f"[{mark}] {what}: {detail}")


def _pid_alive(pid: int | None) -> bool | None:
    """True/False if we can tell, None if unknown. (Never os.kill: on Windows it terminates.)"""
    if not pid or os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    handle = k32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None if ctypes.get_last_error() == 5 else False  # access denied => exists
    try:
        code = wintypes.DWORD()
        return bool(k32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
    finally:
        k32.CloseHandle(handle)


async def _health() -> dict:
    s = read_session()
    async with AddinClient(s) as c:
        return await c.request("health.check", {}, timeout=10)


def main(argv: list[str] | None = None, prog: str = "python -m revit_mcp doctor") -> int:
    argparse.ArgumentParser(prog=prog, description=__doc__.splitlines()[0]).parse_args(argv)
    command, args = clients.server_command()
    print(f"Revit MCP server {__version__}  ({' '.join([command, *args])})")
    print(f"Python {sys.version.split()[0]}, Windows user {os.environ.get('USERNAME', '?')}\n")

    reachable = False
    try:
        s = read_session()
        if _pid_alive(s.pid) is False:
            _line(False, "Session file", f"{session_path()} is stale: the Revit process ({s.pid}) that wrote it is gone. "
                                         "Start Revit; the file is rewritten on startup.")
            raise SessionNotFound
        _line(True, "Session file", f"{session_path()} (port {s.port}, Revit {s.revit_version}, token from {s.token_source})")
        try:
            hc = asyncio.run(_health())
            reachable = True
            doc = hc.get("document_title") if hc.get("document_open") else "no project open"
            _line(True, "Revit add-in", f"Revit {hc.get('revit_version')}, add-in {hc.get('addin_version', '?')}, {doc}")
            if not hc.get("document_open"):
                _line(None, "Project", "open a project in Revit before asking Claude to work on it")
        except AddinError as e:
            _line(False, "Revit add-in", f"{e.code}: {e.message}")
        except OSError as e:
            _line(False, "Revit add-in", f"not reachable ({e}); is Revit running, and not paused (Revit MCP > Status)?")
    except SessionNotFound:
        if session_path().exists():
            pass  # stale file, already reported
        else:
            _line(False, "Session file", f"none at {session_path()}: Revit is not running, the add-in didn't load, or it is paused")

    for o in clients.status():
        _line(o.ok if o.ok else None, o.target, o.detail)

    pol = auth.load_policy()
    if pol is None:
        _line(None, "Access control", "default (local Claude client has full access after approval)")
    else:
        live = [i for i in pol.get("issued", []) if i.get("jti") not in pol.get("revoked_jti", [])]
        _line(True, "Access control", f"{auth.auth_path()} ({len(pol.get('keys', []))} key(s), {len(live)} unrevoked token(s), "
                                      f"session token {'allowed' if pol.get('allow_session_token', True) else 'disabled'})")

    ok, n, msg = audit.verify()
    _line(ok if n else None, "Audit log", f"{audit.audit_path()}: {msg}")
    return 0 if reachable else 1


if __name__ == "__main__":
    raise SystemExit(main())
