"""Stub Revit add-in: speaks the wire protocol (docs/05) WITHOUT Revit.

Lets you exercise the full MCP-server → add-in path on a dev machine that has
no Revit installed. It binds an ephemeral loopback port, writes session.json
exactly like the real add-in, and answers `health.check` with fake-but-shaped
data. Run it, then run the MCP server (or tools/test_health.py) against it.

    python -m tools.stub_addin            # runs until Ctrl-C
    python -m tools.stub_addin --no-doc   # simulate "no project open"

This mirrors the C# add-in's framing/handshake so the Python client code is
validated against the same contract the real add-in implements.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
from pathlib import Path

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
        if hello.get("token") != self.token:
            await self._send(writer, {"type": "error", "code": "BAD_TOKEN"})
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
            if req.get("token") != self.token:
                await self._send(writer, {"id": rid, "ok": False,
                                          "error": {"code": "BAD_TOKEN", "message": "bad token"}})
                continue
            method = req.get("method")
            if method == "health.check":
                await self._send(writer, {"id": rid, "ok": True, "result": self._health_result()})
            else:
                await self._send(writer, {"id": rid, "ok": False,
                                          "error": {"code": "UNKNOWN_METHOD",
                                                    "message": f"Unknown method '{method}'."}})
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
