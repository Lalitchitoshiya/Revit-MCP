"""Governance unit tests — tokens, scopes, audit chain, approval logic. No Revit,
no socket. Run: python -m pytest tests/

End-to-end (real MCP client + stub add-in): python -m tools.test_governance
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from revit_mcp import audit, auth, server

NOW = 1_800_000_000
SESSION = "s" * 64


@pytest.fixture
def policy():
    return auth.new_policy()


# ----------------------------------------------------------------- tokens

def test_scoped_token_roundtrip(policy):
    tok, claims = auth.mint(policy, "alice/desktop", [auth.READ], 3600, now=NOW)
    p = auth.verify(tok, policy, SESSION, now=NOW + 10)
    assert (p.kind, p.sub, p.scopes, p.jti) == ("scoped", "alice/desktop", [auth.READ], claims["jti"])
    assert p.can(auth.READ) and not p.can(auth.WRITE)


@pytest.mark.parametrize("mutate,code", [
    (lambda t, pol: t[:-3] + ("AAA" if not t.endswith("AAA") else "BBB"), "BAD_TOKEN"),  # signature
    (lambda t, pol: "garbage", "BAD_TOKEN"),
    (lambda t, pol: None, "BAD_TOKEN"),
])
def test_tampered_or_missing_tokens_rejected(policy, mutate, code):
    tok, _ = auth.mint(policy, "a", [auth.READ], 3600, now=NOW)
    with pytest.raises(auth.AuthError) as e:
        auth.verify(mutate(tok, policy), policy, SESSION, now=NOW)
    assert e.value.code == code


def test_expiry(policy):
    tok, _ = auth.mint(policy, "a", [auth.READ], 60, now=NOW)
    auth.verify(tok, policy, SESSION, now=NOW + 59)
    with pytest.raises(auth.AuthError, match="TOKEN_EXPIRED"):
        auth.verify(tok, policy, SESSION, now=NOW + 60)


def test_revocation(policy):
    tok, claims = auth.mint(policy, "a", [auth.WRITE], 3600, now=NOW)
    policy["revoked_jti"].append(claims["jti"])
    with pytest.raises(auth.AuthError, match="TOKEN_REVOKED"):
        auth.verify(tok, policy, SESSION, now=NOW)


def test_rotation_with_grace(policy):
    old, _ = auth.mint(policy, "a", [auth.READ], 86400, now=NOW)
    new_key = auth.rotate(policy, grace_s=900, now=NOW)
    new, claims = auth.mint(policy, "b", [auth.READ], 86400, now=NOW)
    assert claims["kid"] == new_key["kid"]
    auth.verify(old, policy, SESSION, now=NOW + 899)          # still inside grace
    with pytest.raises(auth.AuthError, match="TOKEN_EXPIRED"):
        auth.verify(old, policy, SESSION, now=NOW + 901)      # key retired
    auth.verify(new, policy, SESSION, now=NOW + 901)


def test_session_token_full_access_unless_disabled(policy):
    p = auth.verify(SESSION, policy, SESSION)
    assert p.kind == "session" and p.can(auth.WRITE)
    policy["allow_session_token"] = False
    with pytest.raises(auth.AuthError, match="BAD_TOKEN"):
        auth.verify(SESSION, policy, SESSION)


def test_unknown_scope_rejected_at_issue(policy):
    with pytest.raises(ValueError):
        auth.mint(policy, "a", ["model:admin"], 60)


@pytest.mark.parametrize("s,secs", [("90s", 90), ("15m", 900), ("8h", 28800), ("30d", 2592000)])
def test_parse_ttl(s, secs):
    assert auth.parse_ttl(s) == secs


# --------------------------------------------------------- scope map parity

def test_scope_map_matches_csharp():
    """The Python mirror and the add-in's Scopes.cs must agree exactly."""
    cs = Path(__file__).resolve().parents[2] / "addin" / "src" / "Auth" / "Scopes.cs"
    pairs = dict(re.findall(r'\["([a-z.]+)"\]\s*=\s*(Read|Write)', cs.read_text(encoding="utf-8")))
    cs_map = {m: auth.READ if s == "Read" else auth.WRITE for m, s in pairs.items()}
    assert cs_map == auth.METHOD_SCOPES


def test_unlisted_methods_fail_closed():
    assert auth.required_scope("elements.delete") == auth.WRITE
    assert auth.required_scope("plan.preview") == auth.READ


# ------------------------------------------------------------- audit chain

def test_audit_chain_and_tamper(tmp_path):
    p = tmp_path / "audit.jsonl"
    for i in range(3):
        audit.append({"event": "plan.commit", "outcome": "committed", "plan_id": f"p{i}", "note": "ünï <&>"}, p)
    ok, n, _ = audit.verify(p)
    assert ok and n == 3
    lines = p.read_text(encoding="utf-8").splitlines()

    p.write_text("\n".join(lines[:1] + lines[2:]) + "\n", encoding="utf-8")  # delete a record
    ok, _, msg = audit.verify(p)
    assert not ok and "chain broken" in msg

    p.write_text("\n".join([lines[0].replace("p0", "pX")] + lines[1:]) + "\n", encoding="utf-8")  # edit
    ok, _, msg = audit.verify(p)
    assert not ok and "does not match" in msg


def test_audit_verify_missing_file_is_ok(tmp_path):
    ok, n, _ = audit.verify(tmp_path / "none.jsonl")
    assert ok and n == 0


# ---------------------------------------------------------- approval logic

class _FakeSession:
    def __init__(self, can_elicit):
        self._can = can_elicit
        self.client_params = SimpleNamespace(clientInfo=SimpleNamespace(name="test-client", version="1"))

    def check_client_capability(self, cap):
        return self._can


class _FakeCtx:
    def __init__(self, can_elicit=True, action="accept", approve=True):
        self.session = _FakeSession(can_elicit)
        self.prompts = []
        self._action, self._approve = action, approve

    async def elicit(self, message, schema):
        self.prompts.append(message)
        if self._action != "accept":
            return SimpleNamespace(action=self._action)
        return SimpleNamespace(action="accept", data=schema(approve=self._approve, comment="note"))


@pytest.mark.asyncio
async def test_approval_human_accepts(monkeypatch):
    monkeypatch.setenv("REVIT_MCP_APPROVAL", "elicit")
    ctx = _FakeCtx()
    ap, err = await server._obtain_approval(ctx, "Approve?")
    assert err is None and ap["method"] == "elicitation" and ap["human_verified"] is True
    assert ap["comment"] == "note" and ap["client"] == "test-client 1" and ctx.prompts == ["Approve?"]


@pytest.mark.asyncio
@pytest.mark.parametrize("action,approve", [("decline", True), ("cancel", True), ("accept", False)])
async def test_approval_refusals(monkeypatch, action, approve):
    monkeypatch.setenv("REVIT_MCP_APPROVAL", "elicit_or_token")
    ap, err = await server._obtain_approval(_FakeCtx(action=action, approve=approve), "Approve?")
    assert ap is None and err["error"]["code"] == "APPROVAL_DECLINED"


@pytest.mark.asyncio
async def test_strict_mode_requires_prompt_capable_client(monkeypatch):
    monkeypatch.setenv("REVIT_MCP_APPROVAL", "elicit")
    ap, err = await server._obtain_approval(_FakeCtx(can_elicit=False), "Approve?")
    assert ap is None and err["error"]["code"] == "APPROVAL_UNAVAILABLE"


@pytest.mark.asyncio
async def test_default_mode_falls_back_unverified(monkeypatch):
    monkeypatch.delenv("REVIT_MCP_APPROVAL", raising=False)
    ap, err = await server._obtain_approval(None, "Approve?")
    assert err is None and ap["method"] == "confirmation_token" and ap["human_verified"] is False


@pytest.mark.asyncio
async def test_token_mode_never_prompts(monkeypatch):
    monkeypatch.setenv("REVIT_MCP_APPROVAL", "token")
    ctx = _FakeCtx()
    ap, _ = await server._obtain_approval(ctx, "Approve?")
    assert ctx.prompts == [] and ap["human_verified"] is False


def test_precheck_scope_blocks_read_only_commit(policy):
    tok, _ = auth.mint(policy, "reviewer", [auth.READ], 3600, now=int(time.time()))
    s = SimpleNamespace(token=tok)
    assert server._precheck_scope(s, "elements.query") is None
    assert server._precheck_scope(s, "plan.commit")["error"]["code"] == "SCOPE_DENIED"
    assert server._precheck_scope(SimpleNamespace(token=SESSION), "plan.commit") is None
