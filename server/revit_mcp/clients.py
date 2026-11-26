"""Register / unregister this MCP server with the Claude apps on this PC.

    revit-mcp-server setup register      # Claude Desktop + Claude Code (installer runs this)
    revit-mcp-server setup unregister    # (uninstaller runs this)
    revit-mcp-server setup status
    (developer: python -m revit_mcp setup ...)

Claude Desktop: adds/removes the "revit-mcp" entry in claude_desktop_config.json
(the classic %APPDATA%\\Claude location and the Microsoft Store package
location), leaving every other entry untouched. A one-time backup of the
original file is kept next to it (claude_desktop_config.json.revitmcp.bak).

Claude Code: uses its own CLI (`claude mcp add/remove --scope user`), so its
config file is never edited behind its back. If the CLI isn't found, the exact
command to run is printed instead.

Nothing is configured that the server doesn't already default to: with no
REVIT_MCP_TOKEN the server uses the session token, and with no
REVIT_MCP_APPROVAL it prompts the human whenever the client supports it.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SERVER_NAME = "revit-mcp"
BACKUP_SUFFIX = ".revitmcp.bak"


@dataclass
class Outcome:
    target: str
    ok: bool
    detail: str


def server_command() -> tuple[str, list[str]]:
    """How a Claude app should start this server."""
    if getattr(sys, "frozen", False):  # PyInstaller build: the exe itself
        return sys.executable, []
    return sys.executable, ["-m", "revit_mcp"]


def _roaming() -> Path:
    return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")


def _local() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")


CONFIG_NAME = "claude_desktop_config.json"


def _classic_config() -> Path:
    return _roaming() / "Claude" / CONFIG_NAME


def _store_configs() -> list[Path]:
    """Config paths of Microsoft Store (MSIX) installs: the app's AppData is
    virtualized into its package folder, which exists as soon as it's installed."""
    packages = _local() / "Packages"
    if not packages.is_dir():
        return []
    return sorted(p / "LocalCache" / "Roaming" / "Claude" / CONFIG_NAME
                  for p in packages.glob("Claude_*") if p.is_dir())


def _data_configs() -> list[Path]:
    """Config paths under %LOCALAPPDATA%\\Claude-Data\\<package family>\\, where some
    MSIX installs keep their config instead (seen on a test PC running 6.28899:
    Settings > Desktop app > Edit config opened this file, the other two were unused)."""
    root = _local() / "Claude-Data"
    if not root.is_dir():
        return []
    found = [root / CONFIG_NAME] if (root / CONFIG_NAME).exists() else []
    return found + sorted(d / CONFIG_NAME for d in root.iterdir() if d.is_dir())


def desktop_installed() -> bool:
    return (_classic_config().parent.is_dir() or (_local() / "AnthropicClaude").is_dir()
            or bool(_store_configs()) or bool(_data_configs()))


def desktop_config_paths() -> list[Path]:
    """Where Claude Desktop may read its config on this PC.

    Its config folder only appears after Claude Desktop has been opened, so an
    installed app counts even without it. Which file a given install reads
    varies (classic %APPDATA%\\Claude, the MSIX package's LocalCache, or
    %LOCALAPPDATA%\\Claude-Data\\<family>), so every candidate is written;
    an unused copy is harmless.
    """
    if not desktop_installed():
        return []
    return [_classic_config(), *_store_configs(), *_data_configs()]


def _is_revit_mcp(entry: object) -> bool:
    """Does this mcpServers entry start Revit MCP (any copy: installed exe, a dev venv, system Python)?"""
    if not isinstance(entry, dict):
        return False
    command = str(entry.get("command", "")).replace("\\", "/").lower()
    args = [str(a).lower() for a in entry.get("args") or []]
    return command.endswith("/revit-mcp-server.exe") or command == "revit-mcp-server.exe" or \
        any(a == "-m" and nxt in ("revit_mcp", "revit_mcp.server") for a, nxt in zip(args, args[1:]))


def _stale_entries(servers: dict) -> dict:
    """Other entries that also start Revit MCP: copied dev configs, old names.
    They compete for the add-in's single connection or fail outright."""
    return {name: e for name, e in servers.items() if name != SERVER_NAME and _is_revit_mcp(e)}


def _load(path: Path) -> dict:
    if not path.exists() or not path.read_text(encoding="utf-8-sig").strip():
        return {}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("top level is not a JSON object")
    return data


def _save(path: Path, data: dict) -> None:
    if path.exists():
        backup = path.with_name(path.name + BACKUP_SUFFIX)
        if not backup.exists():
            shutil.copy2(path, backup)
    tmp = path.with_name(path.name + ".revitmcp.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def register_desktop(dry_run: bool = False, create: bool = False) -> list[Outcome]:
    paths = desktop_config_paths()
    if not paths and create:
        paths = [_classic_config()]
    if not paths:
        return [Outcome("Claude Desktop", False,
                        "not found on this PC (install it from claude.ai/download, open it once, "
                        "then click Revit MCP > Connect Claude in Revit)")]
    command, args = server_command()
    out = []
    for path in paths:
        try:
            data = _load(path)
            servers = data.setdefault("mcpServers", {})
            if not isinstance(servers, dict):
                raise ValueError('"mcpServers" is not an object')
            entry = {"command": command, "args": args}
            stale = _stale_entries(servers)
            if servers.get(SERVER_NAME) == entry and not stale:
                out.append(Outcome("Claude Desktop", True, f"already registered ({path})"))
                continue
            for name, old in stale.items():
                del servers[name]
                out.append(Outcome("Claude Desktop", True,
                                   f"{'would replace' if dry_run else 'replaced'} old entry \"{name}\" "
                                   f"({json.dumps(old)}) in {path}"))
            servers[SERVER_NAME] = entry
            if not dry_run:
                path.parent.mkdir(parents=True, exist_ok=True)
                _save(path, data)
            verb = "would register in" if dry_run else "registered in"
            out.append(Outcome("Claude Desktop", True, f"{verb} {path} (restart Claude Desktop)"))
        except (OSError, ValueError) as e:  # never overwrite a file we can't parse
            out.append(Outcome("Claude Desktop", False, f"left unchanged, could not update {path}: {e}"))
    return out


def unregister_desktop(dry_run: bool = False) -> list[Outcome]:
    out = []
    for path in desktop_config_paths():
        if not path.exists():
            continue
        try:
            data = _load(path)
            servers = data.get("mcpServers")
            if isinstance(servers, dict) and SERVER_NAME in servers:
                del servers[SERVER_NAME]
                if not dry_run:
                    _save(path, data)
                out.append(Outcome("Claude Desktop", True, f"{'would remove' if dry_run else 'removed'} from {path}"))
            else:
                out.append(Outcome("Claude Desktop", True, f"not registered ({path})"))
        except (OSError, ValueError) as e:
            out.append(Outcome("Claude Desktop", False, f"could not update {path}: {e}"))
    return out or [Outcome("Claude Desktop", True, "not installed")]


def find_claude_cli() -> str | None:
    found = shutil.which("claude")
    if found:
        return found
    home = Path.home()
    for candidate in (home / ".local" / "bin" / "claude.exe", _roaming() / "npm" / "claude.cmd"):
        if candidate.exists():
            return str(candidate)
    return None


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return -1, str(e)


def _code_add_command(cli: str) -> list[str]:
    command, args = server_command()
    return [cli, "mcp", "add", "--scope", "user", SERVER_NAME, "--", command, *args]


def register_code(dry_run: bool = False) -> Outcome:
    cli = find_claude_cli()
    manual = " ".join(f'"{c}"' if " " in c else c for c in _code_add_command("claude"))
    if cli is None:
        return Outcome("Claude Code", False, f"CLI not found; if you use Claude Code, run:  {manual}")
    if dry_run:
        return Outcome("Claude Code", True, f"would run: {manual}")
    _run([cli, "mcp", "remove", "--scope", "user", SERVER_NAME])  # idempotent re-register
    code, text = _run(_code_add_command(cli))
    if code == 0:
        return Outcome("Claude Code", True, "registered for your user (new Claude Code sessions)")
    return Outcome("Claude Code", False, f"`claude mcp add` failed ({text or code}); run manually:  {manual}")


def unregister_code(dry_run: bool = False) -> Outcome:
    cli = find_claude_cli()
    if cli is None:
        return Outcome("Claude Code", True, "CLI not found; nothing to remove")
    if dry_run:
        return Outcome("Claude Code", True, f"would run: claude mcp remove --scope user {SERVER_NAME}")
    code, text = _run([cli, "mcp", "remove", "--scope", "user", SERVER_NAME])
    return Outcome("Claude Code", True, "removed" if code == 0 else "was not registered")


def status() -> list[Outcome]:
    out = []
    for path in desktop_config_paths():
        try:
            servers = _load(path).get("mcpServers") or {}
            entry = servers.get(SERVER_NAME)
            out.append(Outcome("Claude Desktop", entry is not None,
                               f"{'registered' if entry else 'not registered'} ({path})"
                               + (f" -> {entry.get('command')}" if entry else "")))
            for name, old in _stale_entries(servers).items():
                out.append(Outcome("Claude Desktop", False,
                                   f"old entry \"{name}\" also starts Revit MCP ({old.get('command')} "
                                   f"{' '.join(map(str, old.get('args') or []))}); `setup register` replaces it"))
        except (OSError, ValueError) as e:
            out.append(Outcome("Claude Desktop", False, f"unreadable {path}: {e}"))
    if not out:
        out.append(Outcome("Claude Desktop", False, "not installed"))
    cli = find_claude_cli()
    if cli is None:
        out.append(Outcome("Claude Code", False, "CLI not found"))
    else:
        code, text = _run([cli, "mcp", "get", SERVER_NAME])
        out.append(Outcome("Claude Code", code == 0, "registered" if code == 0 else "not registered"))
    return out


def _print(outcomes: list[Outcome], log_title: str | None = None) -> bool:
    lines = [f"[{'ok' if o.ok else '--'}] {o.target}: {o.detail}" for o in outcomes]
    for line in lines:
        print(line)
    if log_title:
        _log(log_title, lines)
    return any(o.ok for o in outcomes)


def _log(title: str, lines: list[str]) -> None:
    """Append to %LOCALAPPDATA%\\RevitMCP\\logs\\setup.log: the installer runs setup
    silently, so this is the only record of what it did. Never fails the command."""
    try:
        from datetime import datetime
        log = _local() / "RevitMCP" / "logs" / "setup.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {title}\n" + "".join(f"  {l}\n" for l in lines))
    except OSError:
        pass


def main(argv: list[str] | None = None, prog: str = "python -m revit_mcp setup") -> int:
    ap = argparse.ArgumentParser(prog=prog, description="Register Revit MCP with Claude Desktop / Claude Code.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("register", "unregister"):
        p = sub.add_parser(name)
        p.add_argument("--dry-run", action="store_true", help="show what would change, change nothing")
        p.add_argument("--desktop-only", action="store_true")
        p.add_argument("--code-only", action="store_true")
        if name == "register":
            p.add_argument("--create", action="store_true",
                           help="create the Claude Desktop config even if Claude Desktop isn't installed yet")
    sub.add_parser("status")
    a = ap.parse_args(argv)

    command, args = server_command()
    print(f"Revit MCP server: {' '.join([command, *args])}")
    if a.cmd == "status":
        _print(status())
        return 0
    results: list[Outcome] = []
    if a.cmd == "register":
        if not a.code_only:
            results += register_desktop(a.dry_run, a.create)
        if not a.desktop_only:
            results.append(register_code(a.dry_run))
    else:
        if not a.code_only:
            results += unregister_desktop(a.dry_run)
        if not a.desktop_only:
            results.append(unregister_code(a.dry_run))
    # Success if at least one client was handled; "not installed" isn't an install failure.
    title = f"setup {' '.join(argv if argv is not None else sys.argv[1:])} (server {command} {' '.join(args)})".rstrip()
    return 0 if _print(results, None if a.dry_run else title) else 1


if __name__ == "__main__":
    raise SystemExit(main())
