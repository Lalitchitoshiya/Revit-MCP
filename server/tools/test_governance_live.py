"""Governance checks against the LIVE C# add-in (Revit open with a project).

    python -m revit_mcp.auth init            # once, if auth.json doesn't exist yet
    python -m tools.test_governance_live      # non-mutating checks
    python -m tools.test_governance_live --commit   # + commit/undo a test wall (audited)

Proves the add-in itself (not just the MCP server) enforces access:
  - a read-only token can read and preview, but plan.commit / plan.undo sent
    DIRECTLY to the socket are refused with SCOPE_DENIED, and the denial is
    written to the audit log with the token's identity;
  - expired and revoked tokens are refused at the handshake (revocation takes
    effect without restarting Revit);
  - --commit: a write token commits one wall and undoes it; both are audited
    with approval metadata, and the audit chain verifies.

Uses the real auth.json/audit.jsonl the add-in reads. It only ADDS short-lived
test tokens (and revokes the one it uses for the revocation check); it never
rotates your keys or changes policy.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import time

from revit_mcp import audit, auth
from revit_mcp.addin_client import AddinClient, AddinError
from revit_mcp.session import read_session

PASS, FAIL = 0, 0


def check(cond: bool, msg: str) -> None:
    global PASS, FAIL
    print(("  PASS " if cond else "  FAIL ") + msg)
    PASS, FAIL = PASS + bool(cond), FAIL + (not cond)


async def call(token: str, method: str, params: dict | None = None, timeout: float = 35.0):
    s = dataclasses.replace(read_session(), token=token)
    async with AddinClient(s) as c:
        return await c.request(method, params or {}, timeout=timeout)


async def expect_error(token: str, method: str, params: dict | None = None) -> str | None:
    try:
        await call(token, method, params)
        return None
    except AddinError as e:
        return e.code


def mint(pol: dict, sub: str, scopes: list[str], ttl: int, now: int | None = None) -> str:
    tok, claims = auth.mint(pol, sub, scopes, ttl, now=now)
    pol["issued"].append({k: claims[k] for k in ("jti", "sub", "scopes", "iat", "exp", "kid")})
    return tok


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="also commit + undo a test wall")
    args = ap.parse_args()

    pol = auth.load_policy()
    if pol is None:
        print(f"No {auth.auth_path()} — run: python -m revit_mcp.auth init   (then rerun)")
        return 1
    read_tok = mint(pol, "live-test/read-only", [auth.READ], 600)
    write_tok = mint(pol, "live-test/writer", [auth.READ, auth.WRITE], 600)
    expired_tok = mint(pol, "live-test/expired", [auth.READ], 1, now=int(time.time()) - 60)
    revoke_tok = mint(pol, "live-test/to-revoke", [auth.READ], 600)
    auth.save_policy(pol)

    try:
        hc = await call(read_tok, "health.check")
    except AddinError as e:
        print(f"Add-in not reachable or rejected the test token ({e.code}): {e.message}")
        print("Is Revit open with the NEW add-in deployed (deploy.ps1 + restart)?")
        return 1
    print(f"Revit {hc.get('revit_version')} | doc: {hc.get('document_title')}")

    print("\n[1] read-only token: reads allowed, mutations refused BY THE ADD-IN")
    lv = await call(read_tok, "levels.list")
    check(bool(lv.get("levels")), "levels.list allowed")
    n0 = len(audit.read_records())
    code = await expect_error(read_tok, "plan.commit", {"plan_id": "x", "plan": {"actions": []}})
    check(code == "SCOPE_DENIED", f"direct plan.commit -> {code}")
    code = await expect_error(read_tok, "plan.undo", {"plan_id": "x"})
    check(code == "SCOPE_DENIED", f"direct plan.undo -> {code}")
    recs = audit.read_records()[n0:]
    check(len(recs) == 2 and all(r["event"] == "auth.denied" and r["principal"]["sub"] == "live-test/read-only"
                                 for r in recs), "both denials audited with token identity")

    print("\n[2] expiry and revocation (no Revit restart)")
    code = await expect_error(expired_tok, "health.check")
    check(code == "TOKEN_EXPIRED", f"expired token -> {code}")
    check((await call(revoke_tok, "health.check")).get("revit_connected") is True, "token works before revoke")
    pol = auth.load_policy()
    pol["revoked_jti"].append(auth.decode_unverified(revoke_tok)["jti"])
    auth.save_policy(pol)
    time.sleep(0.05)
    code = await expect_error(revoke_tok, "health.check")
    check(code == "TOKEN_REVOKED", f"revoked token -> {code}")

    if args.commit:
        print("\n[3] write token: commit + undo one test wall, both audited")
        lvl = lv["levels"][0]["name"]
        types = await call(write_tok, "types.list", {"category": "walls"})
        wt = types["types"][0]["type_name"]
        m = lambda v: {"value": v, "unit": "m"}  # noqa: E731
        plan = {"intent": "governance live test wall", "actions": [{"op": "place_wall", "params": {
            "start": [m(0), m(0)], "end": [m(3), m(0)], "level": {"level_name": lvl},
            "type": {"type_name": wt, "category": "walls"}, "height": m(3)}}]}
        pv = await call(write_tok, "plan.preview", {"plan_id": "pln_livetest", "plan": plan})
        check(pv.get("overall") in ("ok", "warnings"), f"preview {pv.get('overall')}")
        approval = {"method": "live-test", "human_verified": False, "approved_by": "test_governance_live"}
        com = await call(write_tok, "plan.commit", {"plan_id": "pln_livetest", "plan_hash": pv["plan_hash"],
                                                    "plan": plan, "approval": approval,
                                                    "summary": pv.get("summary")}, timeout=135)
        check(com.get("committed") and com.get("audited"), f"committed + audited ({len(com.get('created', []))} created)")
        code = await expect_error(write_tok, "plan.commit", {"plan_id": "pln_livetest", "plan_hash": pv["plan_hash"],
                                                             "plan": plan, "approval": approval})
        check(code == "PLAN_NOT_PREVIEWED", f"replay of the same previewed plan refused -> {code}")
        und = await call(write_tok, "plan.undo", {"plan_id": "pln_livetest", "approval": approval}, timeout=135)
        check(und.get("undone") and und.get("audited"), f"undone + audited ({und.get('deleted_count')} removed)")
        last2 = audit.read_records()[-3:]
        check([r["outcome"] for r in last2] == ["committed", "refused", "undone"],
              f"audit outcomes {[r['outcome'] for r in last2]}")
        check(last2[0].get("revit_user") is not None and last2[0]["principal"]["sub"] == "live-test/writer",
              f"record has Revit user '{last2[0].get('revit_user')}' and token identity")

    print("\n[4] audit chain")
    ok, n, msg = audit.verify()
    check(ok, msg)

    print(f"\n{PASS} passed, {FAIL} failed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
