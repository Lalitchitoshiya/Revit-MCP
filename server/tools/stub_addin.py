"""Stub Revit add-in: speaks the wire protocol (docs/05) WITHOUT Revit.

Lets you exercise the full MCP-server → add-in path on a dev machine that has
no Revit installed. It binds an ephemeral loopback port, writes session.json
exactly like the real add-in, and answers `health.check` with fake-but-shaped
data. Run it, then run the MCP server (or tools/test_health.py) against it.

    python -m tools.stub_addin            # runs until Ctrl-C
    python -m tools.stub_addin --no-doc   # simulate "no project open"

This mirrors the C# add-in's framing/handshake so the Python client code is
validated against the same contract the real add-in implements.

Governance mirror (for demos/tests without Revit): accepts the session token or
scoped tokens from auth.json (revit_mcp.auth.verify — same rules as the C#
TokenValidator), enforces per-method scopes, implements a fake
plan.preview/commit/undo, and writes audit records in the add-in's format.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import hashlib
import secrets
from pathlib import Path

from revit_mcp import audit, auth

PROTOCOL_VERSION = "1.0"


def session_path() -> Path:
    override = os.environ.get("REVIT_MCP_SESSION")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "RevitMCP" / "session.json"


class StubAddin:
    def __init__(self, document_open: bool = True):
        self.token = secrets.token_hex(32)
        self.document_open = document_open
        self.previewed: set[str] = set()
        self.committed: dict[str, list[int]] = {}
        self.next_id = 1000

    def _verify(self, token: str | None) -> auth.Principal:
        return auth.verify(token, auth.load_policy(), self.token)

    def _deny(self, method: str, token: str | None, code: str, reason: str) -> None:
        claims = auth.decode_unverified(token or "") or {}
        audit.append({"event": "auth.denied", "outcome": code, "method": method, "reason": reason,
                      "principal": {"kind": "scoped(unverified)" if claims else "opaque",
                                    "sub": claims.get("sub"), "jti": claims.get("jti")}})

    def _plan_audit(self, params: dict, who: auth.Principal) -> dict:
        plan = params.get("plan") or {}
        return {"plan_id": params.get("plan_id"), "intent": plan.get("intent"),
                "summary": params.get("summary"), "approval": params.get("approval"),
                "principal": {"kind": who.kind, "sub": who.sub, "scopes": who.scopes, "jti": who.jti},
                "document": {"title": "reference.rvt", "path": "C:/stub/reference.rvt"},
                "revit_user": "stub-user", "os_user": os.environ.get("USERNAME"), "machine": "stub"}

    def _dispatch(self, method: str, params: dict, who: auth.Principal) -> dict:
        """Returns {"ok":True,"result":...} or {"ok":False,"error":...}."""
        def fail(code, msg):
            return {"ok": False, "error": {"code": code, "message": msg}}
        if method == "health.check":
            return {"ok": True, "result": self._health_result()}
        if method == "plan.preview":
            plan = params.get("plan") or {}
            h = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
            self.previewed.add(h)
            n = len(plan.get("actions", []))
            return {"ok": True, "result": {"plan_hash": h, "overall": "ok", "actions": [],
                                           "summary": f"Would create {n} action(s)."}}
        if method == "plan.commit":
            plan = params.get("plan") or {}
            h = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
            rec = self._plan_audit(params, who)
            rec["plan_hash"] = h
            if params.get("plan_hash") not in (None, h) or h not in self.previewed:
                audit.append({"event": "plan.commit", "outcome": "refused", **rec})
                return fail("PLAN_NOT_PREVIEWED", "not previewed")
            self.previewed.discard(h)  # one preview authorises one commit
            created = []
            for _ in plan.get("actions", []):
                self.next_id += 1
                created.append({"id": self.next_id, "category": "Walls"})
            self.committed[params["plan_id"]] = [c["id"] for c in created]
            audit.append({"event": "plan.commit", "outcome": "committed", **rec, "created": created})
            return {"ok": True, "result": {"plan_id": params["plan_id"], "committed": True,
                                           "created": created, "audited": True}}
        if method == "plan.undo":
            ids = self.committed.pop(params.get("plan_id"), None)
            if ids is None:
                return fail("PLAN_NOT_FOUND", "no such committed plan")
            audit.append({"event": "plan.undo", "outcome": "undone", **self._plan_audit(params, who),
                          "deleted_ids": ids})
            return {"ok": True, "result": {"plan_id": params["plan_id"], "undone": True,
                                           "deleted_count": len(ids), "audited": True}}
        return fail("UNKNOWN_METHOD", f"Unknown method '{method}'.")

    def _health_result(self) -> dict:
        return {
            "revit_connected": True,
            "revit_version": "2025",
            "revit_version_name": "Autodesk Revit 2025 (STUB)",
            "protocol_version": PROTOCOL_VERSION,
            "document_open": self.document_open,
            "document_title": "reference.rvt" if self.document_open else None,
            "units": {"length": "millimeters", "area": "square meters"} if self.document_open
            else {"length": None, "area": None},
        }

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        print(f"[stub] client connected: {peer}")

        # --- handshake ---
        hello_raw = await reader.readline()
        if not hello_raw:
            writer.close()
            return
        hello = json.loads(hello_raw)
        if hello.get("type") != "hello" or hello.get("protocol_version", "").split(".")[0] != "1":
            await self._send(writer, {"type": "error", "code": "VERSION_INCOMPATIBLE"})
            writer.close()
            return
        try:
            self._verify(hello.get("token"))
        except auth.AuthError as e:
            self._deny("handshake", hello.get("token"), e.code, e.message)
            await self._send(writer, {"type": "error", "code": e.code})
            writer.close()
            return

        await self._send(writer, {
            "type": "welcome",
            "protocol_version": PROTOCOL_VERSION,
            "revit_version": "2025",
            "document_open": self.document_open,
            "document_title": "reference.rvt" if self.document_open else None,
        })

        # --- request loop ---
        while True:
            line = await reader.readline()
            if not line:
                break
            req = json.loads(line)
            rid = req.get("id")
            method = req.get("method")
            try:
                who = self._verify(req.get("token"))
            except auth.AuthError as e:
                self._deny(method, req.get("token"), e.code, e.message)
                await self._send(writer, {"id": rid, "ok": False,
                                          "error": {"code": e.code, "message": e.message}})
                continue
            need = auth.required_scope(method)
            if not who.can(need):
                msg = f"Token '{who.sub}' may not call '{method}'; it needs '{need}'."
                self._deny(method, req.get("token"), "SCOPE_DENIED", msg)
                await self._send(writer, {"id": rid, "ok": False,
                                          "error": {"code": "SCOPE_DENIED", "message": msg}})
                continue
            await self._send(writer, {"id": rid, **self._dispatch(method, req.get("params") or {}, who)})
        print(f"[stub] client disconnected: {peer}")
        writer.close()

    @staticmethod
    async def _send(writer: asyncio.StreamWriter, obj: dict) -> None:
        writer.write((json.dumps(obj) + "\n").encode("utf-8"))
        await writer.drain()


async def serve(document_open: bool) -> None:
    stub = StubAddin(document_open=document_open)
    server = await asyncio.start_server(stub.handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    path = session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "port": port,
        "token": stub.token,
        "protocol_version": PROTOCOL_VERSION,
        "revit_version": "2025",
        "pid": os.getpid(),
    }, indent=2), encoding="utf-8")

    print(f"[stub] listening on 127.0.0.1:{port}  (document_open={document_open})")
    print(f"[stub] wrote session file: {path}")
    async with server:
        await server.serve_forever()


def main() -> None:
    ap = argparse.ArgumentParser(description="Stub Revit add-in for protocol testing.")
    ap.add_argument("--no-doc", action="store_true", help="simulate no project open")
    args = ap.parse_args()
    try:
        asyncio.run(serve(document_open=not args.no_doc))
    except KeyboardInterrupt:
        print("\n[stub] stopped.")


if __name__ == "__main__":
    main()
