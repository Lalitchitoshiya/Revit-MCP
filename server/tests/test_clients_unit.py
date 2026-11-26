"""Client registration (revit_mcp.clients) against temp config folders only."""

from __future__ import annotations

import json

import pytest

from revit_mcp import clients


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setattr(clients, "find_claude_cli", lambda: None)
    return tmp_path


def _desktop(home):
    d = home / "Roaming" / "Claude"
    d.mkdir(parents=True)
    return d / "claude_desktop_config.json"


def test_not_installed_reports_without_creating(home):
    out = clients.register_desktop()
    assert not out[0].ok and "not found" in out[0].detail
    assert not (home / "Roaming" / "Claude").exists()


def test_register_preserves_other_entries_and_backs_up(home):
    cfg = _desktop(home)
    cfg.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}), encoding="utf-8")
    out = clients.register_desktop()
    assert out[0].ok
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["theme"] == "dark" and data["mcpServers"]["other"] == {"command": "x"}
    cmd, args = clients.server_command()
    assert data["mcpServers"][clients.SERVER_NAME] == {"command": cmd, "args": args}
    assert (cfg.parent / (cfg.name + clients.BACKUP_SUFFIX)).exists()
    assert "already registered" in clients.register_desktop()[0].detail  # idempotent


def test_register_creates_config_when_claude_folder_exists(home):
    cfg = _desktop(home)
    assert clients.register_desktop()[0].ok
    assert clients.SERVER_NAME in json.loads(cfg.read_text(encoding="utf-8"))["mcpServers"]


def test_invalid_json_is_left_untouched(home):
    cfg = _desktop(home)
    cfg.write_text("{ not json", encoding="utf-8")
    out = clients.register_desktop()
    assert not out[0].ok and cfg.read_text(encoding="utf-8") == "{ not json"


def test_store_package_location(home):
    pkg = home / "Local" / "Packages" / "Claude_abc123" / "LocalCache" / "Roaming" / "Claude"
    pkg.mkdir(parents=True)
    out = clients.register_desktop()
    assert out[0].ok and (pkg / "claude_desktop_config.json").exists()


def test_store_install_before_first_launch(home):
    # Store app installed but never opened: only the package folder exists.
    # (The case on a tester's PC: registration used to skip Claude Desktop silently.)
    pkg = home / "Local" / "Packages" / "Claude_pzs8sxrjxfjjc"
    pkg.mkdir(parents=True)
    out = clients.register_desktop()
    assert all(o.ok for o in out)
    store_cfg = pkg / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json"
    assert clients.SERVER_NAME in json.loads(store_cfg.read_text(encoding="utf-8"))["mcpServers"]
    classic = home / "Roaming" / "Claude" / "claude_desktop_config.json"
    assert classic.exists()  # covers Store builds whose AppData isn't virtualized


def test_claude_data_location_keeps_claude_settings(home):
    # Tester PC: Claude's real config lived in %LOCALAPPDATA%\Claude-Data\claude_<id>\,
    # next to unused copies in the classic and package folders.
    (home / "Local" / "Packages" / "Claude_pzs8sxrjxfjjc").mkdir(parents=True)
    data = home / "Local" / "Claude-Data" / "claude_pzs8sxrjxfjjc"
    data.mkdir(parents=True)
    real = data / "claude_desktop_config.json"
    real.write_text(json.dumps({"coworkUserFilesPath": "C:\\x", "preferences": {"sidebarMode": "chat"}}),
                    encoding="utf-8")
    out = clients.register_desktop()
    assert all(o.ok for o in out) and any(str(real) in o.detail for o in out)
    cfg = json.loads(real.read_text(encoding="utf-8"))
    assert cfg["preferences"] == {"sidebarMode": "chat"} and cfg["coworkUserFilesPath"] == "C:\\x"
    assert clients.SERVER_NAME in cfg["mcpServers"]
    assert any(str(real) in o.detail and o.ok for o in clients.status())


def test_classic_install_before_first_launch(home):
    (home / "Local" / "AnthropicClaude").mkdir(parents=True)
    assert clients.register_desktop()[0].ok
    assert (home / "Roaming" / "Claude" / "claude_desktop_config.json").exists()


def test_stale_copies_of_our_server_are_replaced(home):
    cfg = _desktop(home)
    cfg.write_text(json.dumps({"mcpServers": {
        "revit": {"command": r"C:\Users\x\AppData\Local\Programs\Python\Python314\python.exe", "args": ["-m", "revit_mcp"]},
        "revit-old": {"command": r"C:\old\RevitMCP.bundle\Contents\Server\revit-mcp-server.exe", "args": []},
        "revit-other": {"command": "node", "args": ["revit-tools.js"]},  # someone else's: keep
    }}), encoding="utf-8")
    stale = [o for o in clients.status() if "old entry" in o.detail]
    assert len(stale) == 2 and not any(o.ok for o in stale)
    out = clients.register_desktop()
    assert sum("replaced old entry" in o.detail for o in out) == 2
    servers = json.loads(cfg.read_text(encoding="utf-8"))["mcpServers"]
    assert set(servers) == {"revit-other", clients.SERVER_NAME}
    assert "already registered" in clients.register_desktop()[0].detail


def test_setup_is_logged(home):
    _desktop(home)
    clients.main(["register"])
    log = home / "Local" / "RevitMCP" / "logs" / "setup.log"
    assert "setup register" in log.read_text(encoding="utf-8")
    assert "[ok] Claude Desktop: registered in" in log.read_text(encoding="utf-8")


def test_dry_run_changes_nothing(home):
    cfg = _desktop(home)
    cfg.write_text("{}", encoding="utf-8")
    assert "would register" in clients.register_desktop(dry_run=True)[0].detail
    assert cfg.read_text(encoding="utf-8") == "{}"


def test_unregister_removes_only_ours(home):
    cfg = _desktop(home)
    cfg.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}), encoding="utf-8")
    clients.register_desktop()
    clients.unregister_desktop()
    assert json.loads(cfg.read_text(encoding="utf-8"))["mcpServers"] == {"other": {"command": "x"}}


def test_claude_code_missing_prints_manual_command(home):
    out = clients.register_code()
    assert not out.ok and "claude mcp add --scope user revit-mcp --" in out.detail


def test_main_exit_codes(home, capsys):
    assert clients.main(["register"]) == 1            # neither Claude app present
    _desktop(home)
    assert clients.main(["register"]) == 0            # Desktop handled
    assert clients.main(["unregister"]) == 0
