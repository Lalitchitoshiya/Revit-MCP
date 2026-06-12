"""Phase 5 resilience: the system fails safely on bad input / hostile conditions.

    python -m tools.test_resilience

Covers (docs/08 AC-R*, docs/05 §5.5):
  - BAD_TOKEN and VERSION_INCOMPATIBLE rejected at handshake (no UI thread needed)
  - plan.commit hygiene: PLAN_CHANGED_SINCE_PREVIEW (hash drift) and
    PLAN_NOT_PREVIEWED (never previewed) refuse to mutate
  - CONFIRMATION_REQUIRED: server refuses commit with a wrong token
  - REVIT_NOT_REACHABLE: a stale session (dead port) errors cleanly, no hang

NO_ACTIVE_DOCUMENT and REVIT_BUSY are environment states (close the doc / open a
dialog) and are checked manually.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile

from revit_mcp import protocol
from revit_mcp.addin_client import AddinClient, AddinError
from revit_mcp.server import commit_plan, health_check, preview_plan, stage_plan
from revit_mcp.session import read_session

PASS, FAIL = 0, 0


def check(cond: bool, msg: str) -> None:
    global PASS, FAIL
    print(("  PASS " if cond else "  FAIL ") + msg)
    if cond:
        PASS += 1
    else:
        FAIL += 1


async def raw_handshake(version: str, token: str) -> dict:
    """Send a custom hello and return the add-in's reply (handshake only)."""
    s = read_session()
    reader, writer = await asyncio.open_connection("127.0.0.1", s.port)
    writer.write((json.dumps({"type": "hello", "protocol_version": version, "token": token}) + "\n").encode())
    await writer.drain()
    line = await asyncio.wait_for(reader.readline(), timeout=5)
    writer.close()
    return json.loads(line)


async def main() -> int:
    hc = await health_check()
    if not hc.get("ok"):
        print("Revit not reachable — open a project and retry.")
        return 1
    print(f"Revit {hc['data']['revit_version']} | doc: {hc['data']['document_title']}")
    s = read_session()

    print("\n[1] handshake rejects a bad token")
    r = await raw_handshake(protocol.PROTOCOL_VERSION, "not-the-token")
    check(r.get("type") == "error" and r.get("code") == "BAD_TOKEN", f"BAD_TOKEN ({r.get('code')})")

    print("\n[2] handshake rejects an incompatible protocol version")
    r = await raw_handshake("9.0", s.token)
    check(r.get("type") == "error" and r.get("code") == "VERSION_INCOMPATIBLE", f"VERSION_INCOMPATIBLE ({r.get('code')})")

    minimal = {"intent": "resilience probe", "actions": [{"op": "place_wall", "params": {}}]}

    print("\n[3] commit refuses a plan whose hash drifted from preview")
    try:
        async with AddinClient(s) as c:
            await c.request("plan.commit", {"plan_id": "x", "plan_hash": "deadbeef", "plan": minimal})
        check(False, "expected PLAN_CHANGED_SINCE_PREVIEW")
    except AddinError as e:
        check(e.code == "PLAN_CHANGED_SINCE_PREVIEW", f"PLAN_CHANGED_SINCE_PREVIEW ({e.code})")

    print("\n[4] commit refuses a plan that was never previewed")
    try:
        async with AddinClient(s) as c:
            await c.request("plan.commit", {"plan_id": "x", "plan": minimal})  # no plan_hash
        check(False, "expected PLAN_NOT_PREVIEWED")
    except AddinError as e:
        check(e.code == "PLAN_NOT_PREVIEWED", f"PLAN_NOT_PREVIEWED ({e.code})")

    print("\n[5] server refuses commit with a wrong confirmation token")
    staged = await stage_plan({"intent": "token probe", "actions": [{"op": "place_wall", "params": {
        "start": [0, 0], "end": [1, 0], "level": {"level_name": "x"}, "type": {"id": 1}}}]})
    bad = await commit_plan(staged["data"]["plan_id"], "cft_wrong")
    check(not bad["ok"] and bad["error"]["code"] == "CONFIRMATION_REQUIRED",
          f"CONFIRMATION_REQUIRED ({bad.get('error', {}).get('code')})")

    print("\n[6] stale session (dead port) fails cleanly, no hang")
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"port": 1, "token": "x", "protocol_version": "1.0", "revit_version": "?", "pid": 0}, f)
    orig = os.environ.get("REVIT_MCP_SESSION")
    os.environ["REVIT_MCP_SESSION"] = path
    try:
        r6 = await health_check()
        check(not r6["ok"] and r6["error"]["code"] == "REVIT_NOT_REACHABLE",
              f"REVIT_NOT_REACHABLE ({r6.get('error', {}).get('code')})")
    finally:
        if orig is None:
            del os.environ["REVIT_MCP_SESSION"]
        else:
            os.environ["REVIT_MCP_SESSION"] = orig
        os.remove(path)

    print(f"\nRESILIENCE: {PASS} passed, {FAIL} failed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
