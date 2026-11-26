"""Governance end-to-end WITHOUT Revit: approval prompts, audit log, token scopes.

    python -m tools.test_governance
    REVIT_MCP_SERVER_EXE=...evit-mcp-server.exe python -m tools.test_governance   # test the packaged exe

Starts the stub add-in (tools/stub_addin.py, same auth rules as the C# add-in)
in an isolated temp folder, then drives the REAL MCP server over stdio with a
real MCP client that answers the server's approval prompts (elicitation) the way
a human would in Claude Code. Nothing touches your real session/auth/audit files.

Scenarios: human approves -> committed + audited (human_verified); human
declines -> nothing changes; replayed commit refused; read-only token can read
but not commit (server AND add-in refuse, denial audited); client without
approval prompts under strict/default modes; approved undo audited; expired and
revoked tokens; audit chain intact, then tamper detected.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import mcp.types as types
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from revit_mcp import audit, auth
from revit_mcp.addin_client import AddinClient, AddinError
from revit_mcp.session import read_session

PASS, FAIL = 0, 0
HERE = Path(__file__).resolve().parent.parent  # server/


def check(cond: bool, msg: str) -> None:
    global PASS, FAIL
    print(("  PASS " if cond else "  FAIL ") + msg)
    PASS, FAIL = PASS + bool(cond), FAIL + (not cond)


def approve_with(answer: bool | None, comment: str = "", seen: list | None = None):
    """An elicitation callback acting as the human. None = dismiss the prompt."""
    async def cb(context, params: types.ElicitRequestParams):
        if seen is not None:
            seen.append(params.message)
        if answer is None:
            return types.ElicitResult(action="cancel")
        return types.ElicitResult(action="accept", content={"approve": answer, "comment": comment})
    return cb


async def run_client(env: dict, steps, elicit=None):
    exe = os.environ.get("REVIT_MCP_SERVER_EXE")  # packaged build (installer/build.ps1) instead of source
    command, args = (exe, []) if exe else (sys.executable, ["-m", "revit_mcp"])
    params = StdioServerParameters(command=command, args=args, env=env, cwd=str(HERE))
    async with stdio_client(params, errlog=open(os.devnull, "w")) as (r, w):
        async with ClientSession(r, w, elicitation_callback=elicit) as s:
            await s.initialize()

            async def call(name, **args):
                res = await s.call_tool(name, args)
                return json.loads(res.content[0].text)
            return await steps(call)


PLAN = {"intent": "governance demo wall", "actions": [{"op": "place_wall", "params": {
    "start": [0, 0], "end": [4000, 0], "level": {"level_name": "Level 1"},
    "type": {"type_name": "Generic - 200mm", "category": "walls"}}}]}


async def stage_preview(call):
    st = (await call("stage_plan", plan=PLAN))["data"]
    pv = await call("preview_plan", plan_id=st["plan_id"])
    return st, pv


async def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="revit-mcp-gov-"))
    env = {**os.environ,
           "REVIT_MCP_SESSION": str(tmp / "session.json"),
           "REVIT_MCP_AUTH": str(tmp / "auth.json"),
           "REVIT_MCP_AUDIT": str(tmp / "audit.jsonl"),
           "PYTHONIOENCODING": "utf-8"}
    os.environ.update({k: env[k] for k in ("REVIT_MCP_SESSION", "REVIT_MCP_AUTH", "REVIT_MCP_AUDIT")})

    pol = auth.new_policy()
    write_tok, _ = auth.mint(pol, "lalit/claude-code", [auth.READ, auth.WRITE], 3600)
    read_tok, _ = auth.mint(pol, "reviewer/claude-desktop", [auth.READ], 3600)
    expired_tok, _ = auth.mint(pol, "old-laptop", [auth.READ, auth.WRITE], 1, now=int(time.time()) - 60)
    revoked_tok, rc = auth.mint(pol, "leaked", [auth.READ, auth.WRITE], 3600)
    pol["revoked_jti"].append(rc["jti"])
    auth.save_policy(pol)

    stub = subprocess.Popen([sys.executable, "-m", "tools.stub_addin"], cwd=str(HERE), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            if (tmp / "session.json").exists():
                break
            await asyncio.sleep(0.1)
        await asyncio.sleep(0.2)

        print("[1] write token + human APPROVES -> committed, audited as human-verified")
        seen: list[str] = []

        async def s1(call):
            st, pv = await stage_preview(call)
            c = await call("commit_plan", plan_id=st["plan_id"], confirmation_token=st["confirmation_token"])
            again = await call("commit_plan", plan_id=st["plan_id"], confirmation_token=st["confirmation_token"])
            return st, c, again
        st1, c1, again = await run_client({**env, "REVIT_MCP_TOKEN": write_tok, "REVIT_MCP_APPROVAL": "elicit"},
                                          s1, approve_with(True, "ok for demo", seen))
        check(c1.get("ok") is True, f"commit ok ({c1.get('error')})")
        check(bool(seen) and "governance demo wall" in seen[0], "approval prompt (from server) showed the intent")
        check(c1.get("data", {}).get("approval", {}).get("human_verified") is True, "result says human-verified")
        check(again.get("error", {}).get("code") == "PLAN_ALREADY_COMMITTED", "replayed commit refused")

        print("\n[2] human DECLINES -> nothing changes")
        async def s2(call):
            st, _ = await stage_preview(call)
            return await call("commit_plan", plan_id=st["plan_id"], confirmation_token=st["confirmation_token"])
        n_before = len(audit.read_records())
        c2 = await run_client({**env, "REVIT_MCP_TOKEN": write_tok}, s2, approve_with(False))
        check(c2.get("error", {}).get("code") == "APPROVAL_DECLINED", f"APPROVAL_DECLINED ({c2.get('error', {}).get('code')})")
        c2b = await run_client({**env, "REVIT_MCP_TOKEN": write_tok}, s2, approve_with(None))
        check(c2b.get("error", {}).get("code") == "APPROVAL_DECLINED", "dismissed prompt also refuses")
        check(len(audit.read_records()) == n_before, "no commit reached the add-in")

        print("\n[3] read-only token: can read, cannot change the model")
        async def s3(call):
            hc = await call("health_check")
            st, pv = await stage_preview(call)
            c = await call("commit_plan", plan_id=st["plan_id"], confirmation_token=st["confirmation_token"])
            return hc, pv, c
        hc, pv3, c3 = await run_client({**env, "REVIT_MCP_TOKEN": read_tok}, s3, approve_with(True))
        check(hc.get("ok") and hc["data"]["access"]["scopes"] == [auth.READ], "health_check reports read-only access")
        check(pv3.get("ok") is True, "preview (read-only) allowed")
        check(c3.get("error", {}).get("code") == "SCOPE_DENIED", f"server refuses commit: SCOPE_DENIED ({c3.get('error')})")
        # Bypass the MCP server entirely: the add-in must refuse too.
        s = read_session()
        object.__setattr__(s, "token", read_tok)
        try:
            async with AddinClient(s) as cl:
                await cl.request("plan.commit", {"plan_id": "x", "plan": PLAN})
            check(False, "add-in should refuse direct commit with read token")
        except AddinError as e:
            check(e.code == "SCOPE_DENIED", f"add-in refuses direct socket commit: {e.code}")
        last = audit.read_records()[-1]
        check(last["event"] == "auth.denied" and last["principal"]["sub"] == "reviewer/claude-desktop",
              "denial written to audit log with the token's identity")

        print("\n[4] client that CANNOT show approval prompts")
        async def s4(call):
            st, _ = await stage_preview(call)
            return await call("commit_plan", plan_id=st["plan_id"], confirmation_token=st["confirmation_token"])
        c4 = await run_client({**env, "REVIT_MCP_TOKEN": write_tok, "REVIT_MCP_APPROVAL": "elicit"}, s4, None)
        check(c4.get("error", {}).get("code") == "APPROVAL_UNAVAILABLE", "strict mode: refused (APPROVAL_UNAVAILABLE)")
        c4b = await run_client({**env, "REVIT_MCP_TOKEN": write_tok}, s4, None)
        check(c4b.get("ok") is True and c4b["data"]["approval"]["human_verified"] is False,
              "default mode: committed but recorded as NOT human-verified")

        print("\n[5] approved UNDO is audited")
        async def s5(call):
            st, _ = await stage_preview(call)
            await call("commit_plan", plan_id=st["plan_id"], confirmation_token=st["confirmation_token"])
            return await call("undo_plan", plan_id=st["plan_id"])
        u5 = await run_client({**env, "REVIT_MCP_TOKEN": write_tok}, s5, approve_with(True, "revert"))
        last = audit.read_records()[-1]
        check(u5.get("ok") is True and last["event"] == "plan.undo" and last["approval"]["human_verified"],
              "undo committed with human-verified approval in audit")

        print("\n[6] expired / revoked tokens")
        async def s6(call):
            return await call("health_check")
        e6 = await run_client({**env, "REVIT_MCP_TOKEN": expired_tok}, s6)
        check(e6.get("error", {}).get("code") == "TOKEN_EXPIRED", f"expired -> TOKEN_EXPIRED ({e6.get('error', {}).get('code')})")
        r6 = await run_client({**env, "REVIT_MCP_TOKEN": revoked_tok}, s6)
        check(r6.get("error", {}).get("code") == "TOKEN_REVOKED", f"revoked -> TOKEN_REVOKED ({r6.get('error', {}).get('code')})")

        print("\n[7] audit log: readable in chat, chain intact, tamper detected")
        async def s7(call):
            return await call("get_audit_log", limit=5)
        g = await run_client({**env, "REVIT_MCP_TOKEN": read_tok}, s7)
        check(g["data"]["chain_intact"] is True, g["data"]["chain_message"])
        commits = [r for r in audit.read_records() if r["event"] == "plan.commit" and r["outcome"] == "committed"]
        first = commits[0]
        check(first["approval"]["comment"] == "ok for demo" and first["principal"]["sub"] == "lalit/claude-code"
              and first["created"], "record has approver, comment, token identity, created ids")
        for e in g["data"]["entries"][-3:]:
            print("     " + e["line"])
        p = audit.audit_path()
        txt = p.read_text(encoding="utf-8").replace('"ok for demo"', '"edited later"')
        p.write_text(txt, encoding="utf-8")
        ok, _, msg = audit.verify()
        check(not ok, f"tampering detected: {msg}")
    finally:
        stub.terminate()

    print(f"\n{PASS} passed, {FAIL} failed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
