"""Pure-logic unit tests — no Revit, no socket. Run: python -m pytest tests/

These cover the deterministic helpers so regressions are caught automatically
(NFR-12), independent of a live Revit session.
"""

from __future__ import annotations

import json

import pytest

from revit_mcp import protocol, session
from revit_mcp.server import _shape_diagnostics, _summarize_created


# --- protocol version compatibility (docs/05 §5.8) ---

@pytest.mark.parametrize("server_ver,ok", [
    ("1.0", True), ("1.7", True), ("2.0", False), ("", False),
])
def test_is_compatible(server_ver, ok):
    assert protocol.is_compatible(server_ver) is ok


# --- commit summary (FR-C4) ---

def test_summarize_created_groups_and_pluralizes():
    created = [{"category": "Walls"}, {"category": "Walls"}, {"category": "Doors"}]
    assert _summarize_created(created) == "Created 2 walls, 1 door."


def test_summarize_created_empty():
    assert _summarize_created([]) == "Created nothing."


def test_summarize_created_unknown_category_singularizes():
    assert _summarize_created([{"category": "Ceilings"}]) == "Created 1 ceiling."


# --- staging shape diagnostics (docs/04 §4.2) ---

def test_shape_diagnostics_clean_plan_has_no_errors():
    plan = {"actions": [{"op": "place_wall", "params": {
        "start": [0, 0], "end": [1, 0], "level": {"level_name": "L1"},
        "type": {"id": 1}}}]}
    assert _shape_diagnostics(plan) == []


def test_shape_diagnostics_flags_empty_actions():
    diags = _shape_diagnostics({"actions": []})
    assert any(d["code"] == "MISSING_FIELD" for d in diags)


def test_shape_diagnostics_flags_missing_wall_fields():
    plan = {"actions": [{"op": "place_wall", "params": {"start": [0, 0]}}]}
    codes = {d["code"] for d in _shape_diagnostics(plan)}
    msgs = " ".join(d["message"] for d in _shape_diagnostics(plan))
    assert codes == {"MISSING_FIELD"}
    for missing in ("end", "level", "type"):
        assert missing in msgs


def test_shape_diagnostics_flags_missing_op():
    diags = _shape_diagnostics({"actions": [{"params": {}}]})
    assert any("op" in d["message"] for d in diags)


# --- session file parsing (docs/06 §6.7) incl. BOM tolerance ---

def _write_session(path, *, bom: bool) -> None:
    data = {"port": 1234, "token": "abc", "protocol_version": "1.0",
            "revit_version": "2027", "pid": 1}
    encoding = "utf-8-sig" if bom else "utf-8"
    path.write_text(json.dumps(data), encoding=encoding)


def test_read_session_plain(tmp_path, monkeypatch):
    f = tmp_path / "session.json"
    _write_session(f, bom=False)
    monkeypatch.setenv("REVIT_MCP_SESSION", str(f))
    s = session.read_session()
    assert s.port == 1234 and s.token == "abc" and s.revit_version == "2027"


def test_read_session_tolerates_bom(tmp_path, monkeypatch):
    f = tmp_path / "session.json"
    _write_session(f, bom=True)  # Windows tools often add a BOM
    monkeypatch.setenv("REVIT_MCP_SESSION", str(f))
    assert session.read_session().port == 1234


def test_read_session_missing_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("REVIT_MCP_SESSION", str(tmp_path / "nope.json"))
    with pytest.raises(session.SessionNotFound):
        session.read_session()
