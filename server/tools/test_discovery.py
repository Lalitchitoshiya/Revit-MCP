"""Exercise every Phase 1 discovery method against the live add-in (or stub).

    python -m tools.test_discovery

Runs each read-only call and prints a compact result, so the whole discovery
surface can be verified in one shot after a Revit restart. Read-only — it never
modifies the model.
"""

from __future__ import annotations

import asyncio
import json

from revit_mcp.server import (
    get_context,
    get_model_summary,
    health_check,
    list_grids,
    list_levels,
    list_types,
    query_elements,
    search_families,
)


def show(title: str, result: dict, *, brief: bool = True) -> None:
    ok = result.get("ok")
    print(f"\n=== {title} === ok={ok}")
    if not ok:
        print(json.dumps(result.get("error"), indent=2))
        return
    data = result.get("data", {})
    text = json.dumps(data, indent=2)
    if brief and len(text) > 1400:
        text = text[:1400] + "\n... (truncated)"
    print(text)


async def main() -> int:
    hc = await health_check()
    show("health_check", hc)
    if not hc.get("ok"):
        print("\nRevit not reachable — start Revit with a project open, then retry.")
        return 1

    show("get_model_summary", await get_model_summary())
    show("list_levels", await list_levels())
    show("list_grids", await list_grids())
    show("list_types(walls)", await list_types("walls"))
    show("list_types(doors)", await list_types("doors"))
    show("search_families('door')", await search_families("door", limit=5))
    show("query_elements(category=walls, limit=5)", await query_elements(category="walls", limit=5))
    show("get_context", await get_context())
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
