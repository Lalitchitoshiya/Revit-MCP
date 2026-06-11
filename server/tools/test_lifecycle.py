"""End-to-end Phase 2 verification: the stage -> preview -> commit -> undo spine.

    python -m tools.test_lifecycle

Against the live add-in it:
  1. grounds itself (model summary + a real wall type + a real level),
  2. stages a one-wall plan and previews it (read-only),
  3. proves commit is REFUSED with a wrong confirmation token (safety),
  4. counts walls, commits with the right token, counts again (+1),
  5. undoes the plan, counts again (back to baseline).

Exits non-zero on any check failure. It cleans up after itself (the undo).
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


async def wall_count() -> int:
    r = await query_elements(category="walls", limit=100000)
    assert r["ok"], r
    assert not r["data"]["truncated"], "wall count was truncated — raise the limit"
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
    print(f"Revit {hc['data']['revit_version']} | doc: {hc['data']['document_title']} | units: {hc['data']['units']['length']}")

    summary = await get_model_summary()
    expect(summary["ok"], "get_model_summary ok")
    level_name = summary["data"]["levels"][0]["name"]

    types = await list_types("walls")
    expect(types["ok"] and types["data"]["types"], "list_types(walls) returned types")
    wall_type = types["data"]["types"][0]["type_name"]
    print(f"Using level='{level_name}', wall type='{wall_type}'")

    # Express dimensions in explicit metric units so the test is a sensible
    # ~3 m wall regardless of the model's display units (this model is in feet).
    m = lambda v: {"value": v, "unit": "m"}  # noqa: E731
    plan = {
        "intent": "Phase 2 lifecycle test wall",
        "actions": [{
            "op": "place_wall",
            "handle": "$w1",
            "params": {
                "start": [m(0), m(0)],
                "end": [m(3), m(0)],
                "level": {"level_name": level_name},
                "type": {"type_name": wall_type, "category": "walls"},
                "height": m(3),
            },
        }],
    }

    print("\n[1] stage_plan")
    staged = await stage_plan(plan)
    expect(staged["ok"], "stage_plan ok")
    plan_id = staged["data"]["plan_id"]
    token = staged["data"]["confirmation_token"]
    expect(not [d for d in staged["data"]["shape_diagnostics"] if d["severity"] == "error"],
           "no shape errors")

    print("\n[2] preview_plan (read-only)")
    base = await wall_count()
    prev = await preview_plan(plan_id)
    expect(prev["ok"], "preview ok")
    expect(prev["data"]["overall"] in ("ok", "warnings"), f"preview overall={prev['data']['overall']}")
    print("  summary:", prev["data"]["summary"])
    expect(await wall_count() == base, "preview did NOT modify the model")

    print("\n[3] safety: commit with WRONG token must be refused")
    bad = await commit_plan(plan_id, "cft_wrong")
    expect(not bad["ok"] and bad["error"]["code"] == "CONFIRMATION_REQUIRED", "wrong token refused")
    expect(await wall_count() == base, "refused commit did NOT modify the model")

    print("\n[4] commit with correct token")
    com = await commit_plan(plan_id, token)
    expect(com["ok"], "commit ok")
    created = com["data"]["created"]
    print("  created:", created)
    expect(await wall_count() == base + 1, "exactly one wall added")

    print("\n[5] undo_plan")
    undo = await undo_plan(plan_id)
    expect(undo["ok"], "undo ok")
    expect(await wall_count() == base, "wall removed; back to baseline")

    print("\nALL PHASE 2 CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
