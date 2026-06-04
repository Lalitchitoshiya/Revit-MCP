"""Async socket client for the Revit add-in (docs/05-addin-protocol.md).

Newline-delimited JSON over loopback TCP, with handshake, per-request token,
and bounded timeouts (NFR-7). One request/response at a time, matching the
add-in's single-client model.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging

from . import protocol
from .session import Session

log = logging.getLogger("revit_mcp.client")


class AddinError(Exception):
    """A structured error returned by the add-in (carries a code)."""

    def __init__(self, code: str, message: str, hint: str | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.hint = hint


class AddinClient:
    """Connects, handshakes, and issues RPC requests to the add-in."""

    def __init__(self, session: Session):
        self._session = session
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._ids = itertools.count(1)
        self.welcome: dict | None = None

    async def __aenter__(self) -> "AddinClient":
        await self.connect()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def connect(self) -> None:
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", self._session.port),
                timeout=protocol.CONNECT_TIMEOUT_S,
            )
        except (OSError, asyncio.TimeoutError) as e:
            raise AddinError(
                protocol.ErrorCodes.REVIT_NOT_REACHABLE,
                f"Could not connect to the Revit add-in on 127.0.0.1:{self._session.port}.",
                "Is Revit open with the RevitMCP add-in loaded?",
            ) from e

        await self._handshake()

    async def _handshake(self) -> None:
        hello = {
            "type": "hello",
            "protocol_version": protocol.PROTOCOL_VERSION,
            "token": self._session.token,
        }
        await self._send_line(hello)
        reply = await self._read_line()
        log.info("handshake reply: type=%s", reply.get("type"))

        if reply.get("type") == "error":
            code = reply.get("code", protocol.ErrorCodes.INTERNAL_ERROR)
            raise AddinError(code, f"Handshake rejected by add-in ({code}).")
        if reply.get("type") != "welcome":
            raise AddinError(protocol.ErrorCodes.INTERNAL_ERROR, "Unexpected handshake reply.")
        if not protocol.is_compatible(reply.get("protocol_version", "")):
            raise AddinError(
                protocol.ErrorCodes.VERSION_INCOMPATIBLE,
                f"Add-in protocol {reply.get('protocol_version')} != ours {protocol.PROTOCOL_VERSION}.",
            )
        self.welcome = reply

    async def request(self, method: str, params: dict | None = None,
                      timeout: float = protocol.REQUEST_TIMEOUT_S) -> dict:
        req_id = f"req-{next(self._ids)}"
        message = {
            "id": req_id,
            "token": self._session.token,
            "method": method,
            "params": params or {},
        }
        log.info("→ id=%s method=%s", req_id, method)  # token redacted (NFR-5)
        await self._send_line(message)

        try:
            resp = await asyncio.wait_for(self._read_line(), timeout=timeout)
        except asyncio.TimeoutError as e:
            raise AddinError(
                protocol.ErrorCodes.REVIT_BUSY_TIMEOUT,
                f"No response to '{method}' within {timeout}s.",
                "Revit may be busy or showing a modal dialog.",
            ) from e

        outcome = "ok" if resp.get("ok") else (resp.get("error") or {}).get("code", "error")
        log.info("← id=%s outcome=%s", resp.get("id"), outcome)

        if not resp.get("ok"):
            err = resp.get("error") or {}
            raise AddinError(
                err.get("code", protocol.ErrorCodes.INTERNAL_ERROR),
                err.get("message", "Unknown error."),
                err.get("hint"),
            )
        return resp.get("result") or {}

    async def close(self) -> None:
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:  # noqa: BLE001 — best-effort close
                pass
            self._writer = None
            self._reader = None

    async def _send_line(self, obj: dict) -> None:
        assert self._writer is not None
        self._writer.write((json.dumps(obj) + "\n").encode("utf-8"))
        await self._writer.drain()

    async def _read_line(self) -> dict:
        assert self._reader is not None
        raw = await self._reader.readline()
        if not raw:
            raise AddinError(
                protocol.ErrorCodes.REVIT_NOT_REACHABLE,
                "Connection closed by the add-in.",
            )
        return json.loads(raw.decode("utf-8"))
