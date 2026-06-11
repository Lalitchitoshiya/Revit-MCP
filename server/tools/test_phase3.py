"""Phase 3 verification: hosted elements + intra-plan handles + atomic multi-undo.

    python -m tools.test_phase3

Part A — wall + hosted door in ONE plan:
  the door's host is the wall's plan-local handle ($w1), so the wall must be
  created first and the door hosted on it, all in one transaction group; one undo
  removes BOTH (AC-M1).
Part B — create_level then undo.

Cleans up after itself. Exits non-zero on any failed check.
"""

from __future__ import annotations

import asyncio

from revit_mcp.server import (
    commit_plan,
    get_model_summary,
    health_check,
    list_types,
    preview_plan,
    query_elements,
    stage_plan,
    undo_plan,
)

m = lambda v: {"value": v, "unit": "m"}  # noqa: E731


async def count(category: str) -> int:
    r = await query_elements(category=category, limit=100000)
    assert r["ok"], r
    assert not r["data"]["truncated"], f"{category} count truncated"
    return r["data"]["count"]


def expect(cond: bool, msg: str) -> None:
    print(("  PASS " if cond else "  FAIL ") + msg)
    if not cond:
        raise SystemExit(f"FAILED: {msg}")


async def run_plan(intent: str, actions: list[dict]) -> dict:
    staged = await stage_plan({"intent": intent, "actions": actions})
    expect(staged["ok"], f"stage ok ({intent})")
    pid, token = staged["data"]["plan_id"], staged["data"]["confirmation_token"]
    prev = await preview_plan(pid)
    expect(prev["ok"], "preview ok")
    expect(prev["data"]["overall"] in ("ok", "warnings"),
           f"preview overall={prev['data']['overall']} :: {prev['data']['actions']}")
    print("  summary:", prev["data"]["summary"])
    com = await commit_plan(pid, token)
    expect(com["ok"], f"commit ok :: {com.get('error')}")
    return {"plan_id": pid, "created": com["data"]["created"]}


async def main() -> int:
    hc = await health_check()
    if not hc.get("ok"):
        print("Revit not reachable — open a project and retry.")
        return 1
    print(f"Revit {hc['data']['revit_version']} | doc: {hc['data']['document_title']}")

    summary = await get_model_summary()
    level_name = summary["data"]["levels"][0]["name"]
    walls = await list_types("walls")
    doors = await list_types("doors")
    expect(walls["ok"] and walls["data"]["types"], "wall types available")
    expect(doors["ok"] and doors["data"]["types"], "door types available")
    wall_type_id = walls["data"]["types"][0]["id"]
    door_type_id = doors["data"]["types"][0]["id"]
    print(f"level='{level_name}', wall_type_id={wall_type_id}, door_type_id={door_type_id}")

    # ---- Part A: wall + hosted door in one plan ----
    print("\n[A] wall + hosted door (one plan, handle host)")
    w0, d0 = await count("walls"), await count("doors")
    actions = [
        {"op": "place_wall", "handle": "$w1", "params": {
            "start": [m(0), m(0)], "end": [m(4), m(0)],
            "level": {"level_name": level_name}, "type": {"id": wall_type_id}, "height": m(3)}},
        {"op": "place_door", "handle": "$d1", "params": {
            "host": {"handle": "$w1"}, "type": {"id": door_type_id}, "distance_along": m(2)}},
    ]
    res = await run_plan("Phase 3: wall with hosted door", actions)
    expect(await count("walls") == w0 + 1, "one wall added")
    expect(await count("doors") == d0 + 1, "one door added (hosted on the new wall)")

    print("\n[A] undo removes BOTH (atomic)")
    undo = await undo_plan(res["plan_id"])
    expect(undo["ok"], "undo ok")
    expect(await count("walls") == w0 and await count("doors") == d0, "wall AND door removed")

    # ---- Part B: create_level ----
    print("\n[B] create_level")
    l0 = await count("levels")
    res2 = await run_plan("Phase 3: new level", [
        {"op": "create_level", "handle": "$L", "params": {"elevation": m(9), "name": "MCP Test Level"}},
    ])
    expect(await count("levels") == l0 + 1, "one level added")
    undo2 = await undo_plan(res2["plan_id"])
    expect(undo2["ok"] and await count("levels") == l0, "level removed on undo")

    print("\nALL PHASE 3 CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
