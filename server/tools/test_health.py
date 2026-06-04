"""Round-trip check: drive the MCP server's health_check logic against whatever
add-in is currently published in session.json (the stub or the real Revit add-in).

    # terminal 1
    python -m tools.stub_addin
    # terminal 2
    python -m tools.test_health

Prints the structured result and exits non-zero if it isn't ok.
"""

from __future__ import annotations

import asyncio
import json
import sys

from revit_mcp.server import health_check


async def main() -> int:
    result = await health_check()
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
