"""Phase 5: close the not-yet-live-verified ops — window, standalone floor, room.

    python -m tools.test_phase5_ops

  W) wall + hosted window (with sill) in one plan
  F) standalone floor from a boundary
  R) 4 walls forming an enclosure + a room placed inside (proves enclosure works
     at commit, since the walls are created before the room in the same plan)

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
    return r["data"]["count"]


def expect(cond: bool, msg: str) -> None:
    print(("  PASS " if cond else "  FAIL ") + msg)
    if not cond:
        raise SystemExit(f"FAILED: {msg}")


async def run(intent: str, actions: list[dict]) -> str:
    staged = await stage_plan({"intent": intent, "actions": actions})
    expect(staged["ok"], f"stage ok ({intent})")
    pid, token = staged["data"]["plan_id"], staged["data"]["confirmation_token"]
    prev = await preview_plan(pid)
    expect(prev["ok"] and prev["data"]["overall"] in ("ok", "warnings"),
           f"preview overall={prev['data'].get('overall')} :: {prev['data'].get('actions')}")
    com = await commit_plan(pid, token)
    expect(com["ok"], f"commit ok :: {com.get('error')}")
    print("  ", com["data"].get("summary"))
    return pid


async def main() -> int:
    hc = await health_check()
    if not hc.get("ok"):
        print("Revit not reachable — open a project and retry.")
        return 1
    print(f"Revit {hc['data']['revit_version']} | doc: {hc['data']['document_title']}")

    level = (await get_model_summary())["data"]["levels"][0]["name"]
    wt = (await list_types("walls"))["data"]["types"][0]["id"]
    ft = (await list_types("floors"))["data"]["types"][0]["id"]
    wins = (await list_types("windows"))["data"]["types"]
    expect(bool(wins), "window types available")
    wnt = wins[0]["id"]
    print(f"level='{level}' wall={wt} floor={ft} window={wnt}")

    # W) wall + hosted window
    print("\n[W] wall + hosted window (sill 0.9 m)")
    w0, n0 = await count("walls"), await count("windows")
    # Wall must be tall enough for whatever window type[0] is (some are ~98" tall),
    # so use a 6 m wall + a modest sill — the point is to verify the code path.
    pid = await run("window on a wall", [
        {"op": "place_wall", "handle": "$w1", "params": {
            "start": [m(0), m(0)], "end": [m(4), m(0)], "level": {"level_name": level},
            "type": {"id": wt}, "height": m(6)}},
        {"op": "place_window", "params": {
            "host": {"handle": "$w1"}, "type": {"id": wnt}, "distance_along": m(2), "sill_height": m(0.9)}},
    ])
    expect(await count("windows") == n0 + 1, "one window added")
    await undo_plan(pid)
    expect(await count("walls") == w0 and await count("windows") == n0, "window+wall removed")

    # F) standalone floor
    print("\n[F] standalone floor")
    f0 = await count("floors")
    pid = await run("a floor", [{"op": "place_floor", "params": {
        "boundary": [[m(0), m(0)], [m(4), m(0)], [m(4), m(3)], [m(0), m(3)]],
        "level": {"level_name": level}, "type": {"id": ft}}}])
    expect(await count("floors") == f0 + 1, "one floor added")
    await undo_plan(pid)
    expect(await count("floors") == f0, "floor removed")

    # R) enclosed room (4 walls + room inside, one plan)
    print("\n[R] 4 walls + an enclosed room inside")
    w0, r0 = await count("walls"), await count("rooms")
    corners = [(0, 0), (4, 0), (4, 3), (0, 3)]
    actions = [{"op": "place_wall", "handle": f"$w{i+1}", "params": {
        "start": [m(a[0]), m(a[1])], "end": [m(b[0]), m(b[1])],
        "level": {"level_name": level}, "type": {"id": wt}, "height": m(3)}}
        for i, (a, b) in enumerate(zip(corners, corners[1:] + corners[:1]))]
    actions.append({"op": "place_room", "params": {
        "point": [m(2), m(1.5)], "level": {"level_name": level}, "name": "MCP Room", "number": "MCP-1"}})
    pid = await run("a room enclosed by four walls", actions)
    expect(await count("rooms") == r0 + 1, "one room added")
    await undo_plan(pid)
    expect(await count("walls") == w0 and await count("rooms") == r0, "room + walls removed")

    print("\nALL PHASE 5 OPS CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
