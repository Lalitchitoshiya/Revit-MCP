"""Phase 4 verification: multi-element composition, atomic undo, ambiguity surfacing.

    python -m tools.test_phase4

Part A — a "room" as ONE plan: 4 walls (rectangle) + a floor + a door hosted on
  one of the walls, committed atomically; the commit returns a human summary; one
  undo removes everything (AC-C2, FR-C3/C4).
Part B — ambiguity: if the model has a wall type_name shared by >1 family, a
  by-name reference must fail preview with AMBIGUOUS_REF listing candidate ids
  (FR-C2). Skipped with a note if the model has no duplicate names.

Cleans up after itself. Exits non-zero on any failed check.
"""

from __future__ import annotations

import asyncio
from collections import Counter

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


async def main() -> int:
    hc = await health_check()
    if not hc.get("ok"):
        print("Revit not reachable — open a project and retry.")
        return 1
    print(f"Revit {hc['data']['revit_version']} | doc: {hc['data']['document_title']}")

    summary = await get_model_summary()
    level = summary["data"]["levels"][0]["name"]
    walls = (await list_types("walls"))["data"]["types"]
    floors = (await list_types("floors"))["data"]["types"]
    doors = (await list_types("doors"))["data"]["types"]
    expect(bool(walls and floors and doors), "wall/floor/door types available")
    wt, ft, dt = walls[0]["id"], floors[0]["id"], doors[0]["id"]

    # ---- Part A: a room (4 walls + floor + door) in ONE plan ----
    print("\n[A] room = 4 walls + floor + door, one atomic plan")
    w0, f0, d0 = await count("walls"), await count("floors"), await count("doors")
    corners = [(0, 0), (4, 0), (4, 3), (0, 3)]
    actions = []
    for i, (a, b) in enumerate(zip(corners, corners[1:] + corners[:1])):
        actions.append({"op": "place_wall", "handle": f"$w{i+1}", "params": {
            "start": [m(a[0]), m(a[1])], "end": [m(b[0]), m(b[1])],
            "level": {"level_name": level}, "type": {"id": wt}, "height": m(3)}})
    actions.append({"op": "place_floor", "handle": "$f", "params": {
        "boundary": [[m(x), m(y)] for x, y in corners], "level": {"level_name": level}, "type": {"id": ft}}})
    actions.append({"op": "place_door", "handle": "$d", "params": {
        "host": {"handle": "$w1"}, "type": {"id": dt}, "distance_along": m(2)}})

    staged = await stage_plan({"intent": "A 4x3 m room with a floor and a door", "actions": actions})
    expect(staged["ok"], "stage ok")
    pid, token = staged["data"]["plan_id"], staged["data"]["confirmation_token"]
    prev = await preview_plan(pid)
    expect(prev["ok"] and prev["data"]["overall"] in ("ok", "warnings"),
           f"preview overall={prev['data'].get('overall')}")
    print("  preview summary:", prev["data"]["summary"])
    com = await commit_plan(pid, token)
    expect(com["ok"], f"commit ok :: {com.get('error')}")
    print("  commit summary:", com["data"].get("summary"))
    expect("summary" in com["data"], "commit returned a human summary (FR-C4)")
    expect(await count("walls") == w0 + 4, "4 walls added")
    expect(await count("floors") == f0 + 1, "1 floor added")
    expect(await count("doors") == d0 + 1, "1 door added")

    print("\n[A] one undo removes the whole room")
    undo = await undo_plan(pid)
    expect(undo["ok"], "undo ok")
    print("  undo summary:", undo["data"].get("summary"))
    expect(await count("walls") == w0 and await count("floors") == f0 and await count("doors") == d0,
           "all 6 elements removed atomically")

    # ---- Part B: ambiguity surfacing ----
    print("\n[B] ambiguous type name surfaces candidates")
    names = Counter(t["type_name"] for t in walls)
    dup = next((n for n, c in names.items() if c > 1), None)
    if dup is None:
        print("  SKIP no duplicate wall type names in this model")
    else:
        s2 = await stage_plan({"intent": "ambiguity probe", "actions": [{
            "op": "place_wall", "params": {
                "start": [m(0), m(0)], "end": [m(2), m(0)],
                "level": {"level_name": level}, "type": {"type_name": dup, "category": "walls"}, "height": m(3)}}]})
        p2 = await preview_plan(s2["data"]["plan_id"])
        diags = [d for a in p2["data"]["actions"] for d in a["diagnostics"]]
        amb = next((d for d in diags if d["code"] == "AMBIGUOUS_REF"), None)
        expect(amb is not None, f"ambiguous '{dup}' flagged AMBIGUOUS_REF")
        expect("id " in amb["message"], "ambiguity message lists candidate ids")
        print("  ->", amb["message"][:120])

    print("\nALL PHASE 4 CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
