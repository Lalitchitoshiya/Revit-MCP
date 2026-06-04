"""Entry point: run the MCP server over stdio (the transport Claude hosts use)."""

from __future__ import annotations

from .server import mcp


def main() -> None:
    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
