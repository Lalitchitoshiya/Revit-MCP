"""Scoped, expiring, rotatable access tokens for the Revit add-in.

The add-in (C#) is the enforcement point; this module is the *issuer* and a
mirror of the verification rules (used by the stub add-in, unit tests, and the
server's early scope check). Both sides read the same policy/key file:

    %LOCALAPPDATA%\\RevitMCP\\auth.json      (override: REVIT_MCP_AUTH)

Token wire format (opaque to clients):

    rmcp1.<base64url(payload-json)>.<base64url(HMAC-SHA256(key, "rmcp1." + payload_b64))>

payload = {"v":1,"kid","sub","scopes":[...],"iat","exp","jti"}. The signature is
over the exact payload bytes, so C# and Python never need to agree on JSON
canonicalisation.

CLI (run from server/ with the venv):

    python -m revit_mcp.auth init
    python -m revit_mcp.auth issue --sub "alice/claude-desktop" --scopes model:read --ttl 8h
    python -m revit_mcp.auth list
    python -m revit_mcp.auth rotate --grace 15m
    python -m revit_mcp.auth revoke <jti>
    python -m revit_mcp.auth policy --session-token off
    python -m revit_mcp.auth inspect <token>
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

PREFIX = "rmcp1"

READ = "model:read"
WRITE = "model:write"
ALL_SCOPES = (READ, WRITE)

# Wire method -> required scope. MUST mirror addin/src/Auth/Scopes.cs.
# Anything not listed requires WRITE (fail closed).
METHOD_SCOPES: dict[str, str] = {
    "health.check": READ,
    "model.summary": READ,
    "levels.list": READ,
    "grids.list": READ,
    "types.list": READ,
    "families.search": READ,
    "elements.query": READ,
    "context.get": READ,
    "plan.preview": READ,  # read-only validation; opens no transaction
    "plan.commit": WRITE,
    "plan.undo": WRITE,
}


def required_scope(method: str) -> str:
    return METHOD_SCOPES.get(method, WRITE)


# --------------------------------------------------------------------------- #
# Policy / key file
# --------------------------------------------------------------------------- #

def auth_path() -> Path:
    override = os.environ.get("REVIT_MCP_AUTH")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "RevitMCP" / "auth.json"


def _now() -> int:
    return int(time.time())


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def new_policy() -> dict:
    return {
        "version": 1,
        # Accept the per-Revit-session token from session.json as a full-access
        # (read+write) legacy credential. Turn off once clients use scoped tokens.
        "allow_session_token": True,
        "keys": [_new_key()],
        "issued": [],
        "revoked_jti": [],
    }


def _new_key() -> dict:
    return {
        "kid": "k" + time.strftime("%Y%m%d%H%M%S", time.gmtime()) + secrets.token_hex(2),
        "secret": _b64e(secrets.token_bytes(32)),
        "created": _now(),
        "retire_after": None,  # unix seconds; after this, tokens signed by it are refused
    }


def load_policy(path: Path | None = None) -> dict | None:
    p = path or auth_path()
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8-sig"))


def save_policy(policy: dict, path: Path | None = None) -> Path:
    p = path or auth_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(policy, indent=2), encoding="utf-8")
    os.replace(tmp, p)  # atomic swap; the add-in re-reads on mtime change
    _restrict_to_current_user(p)
    return p


def _restrict_to_current_user(p: Path) -> None:
    """Best-effort: owner-only ACL (the file holds signing secrets)."""
    if os.name != "nt":
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
        return
    user = os.environ.get("USERNAME")
    if not user:
        return
    try:
        subprocess.run(["icacls", str(p), "/inheritance:r", "/grant:r", f"{user}:F"],
                       capture_output=True, check=False, timeout=10)
    except Exception:  # noqa: BLE001 — non-fatal
        pass


def active_key(policy: dict) -> dict:
    """Newest key that is not scheduled for retirement."""
    live = [k for k in policy["keys"] if not k.get("retire_after")]
    if not live:
        raise ValueError("No active signing key — run `python -m revit_mcp.auth rotate`.")
    return max(live, key=lambda k: k["created"])


# --------------------------------------------------------------------------- #
# Mint / decode / verify
# --------------------------------------------------------------------------- #

_TTL_RE = re.compile(r"^(\d+)([smhd])$")


def parse_ttl(s: str) -> int:
    m = _TTL_RE.match(s.strip().lower())
    if not m:
        raise ValueError(f"Bad duration '{s}' (use e.g. 90s, 15m, 8h, 30d).")
    n, unit = int(m.group(1)), m.group(2)
    return n * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]


def mint(policy: dict, sub: str, scopes: list[str], ttl_s: int, now: int | None = None) -> tuple[str, dict]:
    for s in scopes:
        if s not in ALL_SCOPES:
            raise ValueError(f"Unknown scope '{s}'. Valid: {', '.join(ALL_SCOPES)}")
    now = _now() if now is None else now
    key = active_key(policy)
    claims = {
        "v": 1,
        "kid": key["kid"],
        "sub": sub,
        "scopes": sorted(set(scopes)),
        "iat": now,
        "exp": now + ttl_s,
        "jti": "tok_" + secrets.token_hex(6),
    }
    payload_b64 = _b64e(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(_b64d(key["secret"]), f"{PREFIX}.{payload_b64}".encode("ascii"), hashlib.sha256).digest()
    return f"{PREFIX}.{payload_b64}.{_b64e(sig)}", claims


def is_scoped_token(token: str | None) -> bool:
    return bool(token) and token.startswith(PREFIX + ".") and token.count(".") == 2


def decode_unverified(token: str) -> dict | None:
    """Read claims WITHOUT checking the signature (UX only — never for auth)."""
    if not is_scoped_token(token):
        return None
    try:
        return json.loads(_b64d(token.split(".")[1]))
    except Exception:  # noqa: BLE001
        return None


class AuthError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass
class Principal:
    kind: str                       # "scoped" | "session"
    sub: str
    scopes: list[str] = field(default_factory=list)
    jti: str | None = None
    exp: int | None = None

    def can(self, scope: str) -> bool:
        return scope in self.scopes


def verify(token: str | None, policy: dict | None, session_token: str | None,
           now: int | None = None) -> Principal:
    """Mirror of addin/src/Auth/TokenValidator.cs. Raises AuthError."""
    now = _now() if now is None else now
    if not token:
        raise AuthError("BAD_TOKEN", "Missing token.")

    if not is_scoped_token(token):
        allow = policy is None or policy.get("allow_session_token", True)
        if session_token and hmac.compare_digest(token.encode(), session_token.encode()):
            if not allow:
                raise AuthError("BAD_TOKEN", "Session token disabled by policy; use a scoped token.")
            return Principal(kind="session", sub="session", scopes=list(ALL_SCOPES))
        raise AuthError("BAD_TOKEN", "Invalid token.")

    if policy is None:
        raise AuthError("BAD_TOKEN", "Scoped token presented but no auth.json is configured.")
    _, payload_b64, sig_b64 = token.split(".")
    try:
        claims = json.loads(_b64d(payload_b64))
        sig = _b64d(sig_b64)
    except Exception as e:  # noqa: BLE001
        raise AuthError("BAD_TOKEN", "Malformed token.") from e

    key = next((k for k in policy.get("keys", []) if k["kid"] == claims.get("kid")), None)
    if key is None:
        raise AuthError("BAD_TOKEN", "Token signed by an unknown key (rotated out?).")
    expect = hmac.new(_b64d(key["secret"]), f"{PREFIX}.{payload_b64}".encode("ascii"), hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expect):
        raise AuthError("BAD_TOKEN", "Bad token signature.")
    if key.get("retire_after") and now > key["retire_after"]:
        raise AuthError("TOKEN_EXPIRED", "Token's signing key was rotated out; issue a new token.")
    if now >= int(claims.get("exp", 0)):
        raise AuthError("TOKEN_EXPIRED", "Token has expired; issue a new one.")
    if claims.get("jti") in set(policy.get("revoked_jti", [])):
        raise AuthError("TOKEN_REVOKED", "Token has been revoked.")
    return Principal(kind="scoped", sub=str(claims.get("sub", "?")),
                     scopes=list(claims.get("scopes", [])), jti=claims.get("jti"),
                     exp=int(claims["exp"]))


def rotate(policy: dict, grace_s: int, now: int | None = None) -> dict:
    """Add a fresh signing key; schedule every older key to retire after grace."""
    now = _now() if now is None else now
    for k in policy["keys"]:
        if not k.get("retire_after") or k["retire_after"] > now + grace_s:
            k["retire_after"] = now + grace_s
    # Drop keys retired more than a day ago — their tokens are dead anyway.
    policy["keys"] = [k for k in policy["keys"]
                      if not k.get("retire_after") or k["retire_after"] > now - 86400]
    new = _new_key()
    policy["keys"].append(new)
    return new


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _fmt_ts(t: int | None) -> str:
    return "-" if not t else time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))


def _require_policy() -> dict:
    pol = load_policy()
    if pol is None:
        sys.exit(f"No auth file at {auth_path()}. Run: python -m revit_mcp.auth init")
    return pol


def main(argv: list[str] | None = None, prog: str = "python -m revit_mcp.auth") -> None:
    ap = argparse.ArgumentParser(prog=prog, description="Manage Revit MCP access tokens.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="create auth.json with a fresh signing key")
    p_issue = sub.add_parser("issue", help="mint a scoped token")
    p_issue.add_argument("--sub", required=True, help="who/what holds it, e.g. 'alice/claude-desktop'")
    p_issue.add_argument("--scopes", default=READ, help=f"comma list: {', '.join(ALL_SCOPES)}")
    p_issue.add_argument("--ttl", default="8h", help="lifetime, e.g. 15m, 8h, 30d")
    sub.add_parser("list", help="show keys, issued tokens, policy")
    p_rot = sub.add_parser("rotate", help="new signing key; old keys retire after --grace")
    p_rot.add_argument("--grace", default="0s", help="how long old tokens keep working (default 0s)")
    p_rev = sub.add_parser("revoke", help="revoke one token by jti")
    p_rev.add_argument("jti")
    p_pol = sub.add_parser("policy", help="change policy")
    p_pol.add_argument("--session-token", choices=["on", "off"], required=True,
                       help="accept the legacy full-access session token")
    p_ins = sub.add_parser("inspect", help="decode a token and check it against auth.json")
    p_ins.add_argument("token")
    a = ap.parse_args(argv)

    if a.cmd == "init":
        if auth_path().exists():
            sys.exit(f"{auth_path()} already exists (use rotate to replace keys).")
        print(f"Created {save_policy(new_policy())}")
        return

    pol = _require_policy()

    if a.cmd == "issue":
        scopes = [s.strip() for s in a.scopes.split(",") if s.strip()]
        token, claims = mint(pol, a.sub, scopes, parse_ttl(a.ttl))
        pol["issued"].append({k: claims[k] for k in ("jti", "sub", "scopes", "iat", "exp", "kid")})
        save_policy(pol)
        print(f"# jti={claims['jti']} sub={claims['sub']} scopes={','.join(claims['scopes'])} "
              f"expires={_fmt_ts(claims['exp'])}", file=sys.stderr)
        print(token)
    elif a.cmd == "list":
        print(f"file: {auth_path()}")
        print(f"allow_session_token: {pol.get('allow_session_token', True)}")
        print("keys:")
        for k in pol["keys"]:
            state = "active" if not k.get("retire_after") else f"retires {_fmt_ts(k['retire_after'])}"
            print(f"  {k['kid']}  created {_fmt_ts(k['created'])}  {state}")
        revoked = set(pol.get("revoked_jti", []))
        kids = {k["kid"] for k in pol["keys"]}
        now = _now()
        print("issued tokens:")
        for t in pol.get("issued", []):
            state = ("revoked" if t["jti"] in revoked else "expired" if now >= t["exp"]
                     else "key rotated out" if t["kid"] not in kids else "valid")
            print(f"  {t['jti']}  {t['sub']:<28} {','.join(t['scopes']):<24} "
                  f"exp {_fmt_ts(t['exp'])}  [{state}]")
    elif a.cmd == "rotate":
        new = rotate(pol, parse_ttl(a.grace))
        save_policy(pol)
        print(f"New signing key {new['kid']}. Older keys retire in {a.grace}. Re-issue tokens.")
    elif a.cmd == "revoke":
        if a.jti not in pol.setdefault("revoked_jti", []):
            pol["revoked_jti"].append(a.jti)
        save_policy(pol)
        print(f"Revoked {a.jti}.")
    elif a.cmd == "policy":
        pol["allow_session_token"] = a.session_token == "on"
        save_policy(pol)
        print(f"allow_session_token = {pol['allow_session_token']}")
    elif a.cmd == "inspect":
        claims = decode_unverified(a.token)
        print(json.dumps(claims, indent=2) if claims else "Not a scoped token.")
        try:
            pr = verify(a.token, pol, session_token=None)
            print(f"VALID: sub={pr.sub} scopes={pr.scopes} expires={_fmt_ts(pr.exp)}")
        except AuthError as e:
            print(f"INVALID: {e.code} — {e.message}")


if __name__ == "__main__":
    main()
