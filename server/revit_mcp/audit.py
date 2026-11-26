"""Approval audit log: read, verify, and (for the stub/tests only) append.

The Revit add-in is the single writer in production — it is the component that
actually changes the model, so it records every commit/undo (and every auth
denial) with the approval metadata this server forwards.

    %LOCALAPPDATA%\\RevitMCP\\audit\\audit.jsonl     (override: REVIT_MCP_AUDIT)

One JSON object per line, hash-chained for tamper evidence:

    {"seq":1,"ts":"...","prev_hash":"000…",  …record…  ,"hash":"<sha256 hex>"}

hash = sha256(the exact line bytes with the trailing `,"hash":"…"` removed).
Verifying needs no JSON canonicalisation, so C# and Python always agree. Editing,
deleting or reordering any line breaks the chain from that point on.

CLI:
    python -m revit_mcp.audit tail [-n 20]
    python -m revit_mcp.audit verify
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

GENESIS = "0" * 64
_LINE_RE = re.compile(r'^(.*),"hash":"([0-9a-f]{64})"\}$')


def audit_path() -> Path:
    override = os.environ.get("REVIT_MCP_AUDIT")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "RevitMCP" / "audit" / "audit.jsonl"


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def read_records(path: Path | None = None) -> list[dict]:
    p = path or audit_path()
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def tail(n: int = 20, path: Path | None = None) -> list[dict]:
    return read_records(path)[-n:]


def verify(path: Path | None = None) -> tuple[bool, int, str]:
    """Check the whole chain. Returns (ok, records_checked, message)."""
    p = path or audit_path()
    if not p.exists():
        return True, 0, f"No audit log yet at {p}."
    prev, n = GENESIS, 0
    for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        m = _LINE_RE.match(line)
        if not m:
            return False, n, f"line {lineno}: no trailing hash field (edited or truncated)."
        body, claimed = m.group(1) + "}", m.group(2)
        if _sha(body) != claimed:
            return False, n, f"line {lineno}: content does not match its hash (edited)."
        rec = json.loads(body)
        if rec.get("prev_hash") != prev:
            return False, n, f"line {lineno}: chain broken (a record before it was removed or reordered)."
        prev, n = claimed, n + 1
    return True, n, f"OK — {n} record(s), chain intact."


def append(record: dict, path: Path | None = None) -> dict:
    """Append one record in the add-in's exact format. Stub/tests only."""
    p = path or audit_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    records = read_records(p)
    prev = GENESIS
    seq = 1
    if records:
        last_line = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()][-1]
        prev = _LINE_RE.match(last_line).group(2)  # type: ignore[union-attr]
        seq = int(records[-1]["seq"]) + 1
    head = {"seq": seq, "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "prev_hash": prev}
    body = json.dumps({**head, **record}, separators=(",", ":"), ensure_ascii=False)
    h = _sha(body)
    with p.open("a", encoding="utf-8", newline="\n") as f:
        f.write(body[:-1] + f',"hash":"{h}"}}' + "\n")
    return {**head, **record, "hash": h}


def summarize(rec: dict) -> str:
    """One human line per record, for CLI / chat display."""
    ts = rec.get("ts", "?")
    ev, outcome = rec.get("event", "?"), rec.get("outcome", "?")
    who = rec.get("principal", {}).get("sub", "?")
    if ev.startswith("plan."):
        ap = rec.get("approval") or {}
        approver = ap.get("approved_by") or "-"
        verified = "human-verified" if ap.get("human_verified") else "NOT human-verified"
        what = rec.get("summary") or rec.get("intent") or ""
        return (f"#{rec.get('seq')} {ts} {ev} {outcome}: {what} | plan {rec.get('plan_id')} | "
                f"approved by {approver} ({ap.get('method', 'none')}, {verified}) | token {who} | "
                f"doc {rec.get('document', {}).get('title', '?')}")
    return f"#{rec.get('seq')} {ts} {ev} {outcome}: {rec.get('method', '')} {rec.get('reason', '')} | token {who}"


def main(argv: list[str] | None = None, prog: str = "python -m revit_mcp.audit") -> None:
    ap = argparse.ArgumentParser(prog=prog, description="Read/verify the approval audit log.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tail")
    t.add_argument("-n", type=int, default=20)
    t.add_argument("--json", action="store_true")
    sub.add_parser("verify")
    a = ap.parse_args(argv)
    if a.cmd == "tail":
        for rec in tail(a.n):
            print(json.dumps(rec) if a.json else summarize(rec))
    else:
        ok, _, msg = verify()
        print(msg)
        sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
