"""Entry point.

    revit-mcp-server                     run the MCP server over stdio (what Claude starts)
    revit-mcp-server setup register      register with Claude Desktop / Claude Code
    revit-mcp-server doctor              check the whole setup on this PC (read-only)
    revit-mcp-server auth  ...           manage scoped access tokens (revit_mcp.auth)
    revit-mcp-server audit ...           read / verify the approval audit log (revit_mcp.audit)
    revit-mcp-server --version

The same commands work in development as `python -m revit_mcp <command>`.
"""

from __future__ import annotations

import sys

from . import __version__


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    prog = "revit-mcp-server" if getattr(sys, "frozen", False) else "python -m revit_mcp"
    cmd = argv[0] if argv else None

    if cmd in ("--version", "-V", "version"):
        print(f"Revit MCP server {__version__}")
        return
    if cmd in ("-h", "--help", "help"):
        print(__doc__.replace("revit-mcp-server", prog))
        return
    if cmd == "setup":
        from . import clients
        raise SystemExit(clients.main(argv[1:], prog=f"{prog} setup"))
    if cmd == "doctor":
        from . import doctor
        raise SystemExit(doctor.main(argv[1:], prog=f"{prog} doctor"))
    if cmd == "auth":
        from . import auth
        auth.main(argv[1:], prog=f"{prog} auth")
        return
    if cmd == "audit":
        from . import audit
        audit.main(argv[1:], prog=f"{prog} audit")
        return
    if cmd is not None:
        sys.exit(f"Unknown command {cmd!r}. Run `{prog} --help`.")

    from .server import mcp
    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
