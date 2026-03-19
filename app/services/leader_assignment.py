"""
app/services/leader_assignment.py

Assigns the best leader for a reported issue.

Algorithm
─────────
1. Fetch all leaders from DB.
2. Score each by location match (state / city / town — any one is enough).
3. Keep only location-matching leaders; fallback to ALL leaders if none match.
4. For each candidate compute a weighted composite score:
     • category_resolution_rate  (issues in same category resolved / total)  weight 40
     • overall_resolution_rate   (all closed / all assigned)                  weight 30
     • new_leader_bonus          (1.0 if they have never been assigned)       weight 20
     • location_score            (0–3 how closely location matches)           weight 10
     • open_issue_penalty        subtracted based on current workload
     • failed_cases_penalty      subtracted per escalated failure
     • random jitter             small noise so new leaders get fair rotation
5. Return the ObjectId of the highest-scoring leader, or None.
"""

import random
from typing import Optional
from bson import ObjectId


def _norm(v) -> str:
    return (v or "").strip().lower()


def _location_score(leader: dict, location: dict) -> int:
    """0–3: how many of state/city/town match between leader and issue."""
    l_loc = leader.get("leader_location") or {}
    score = 0
    for field in ("state", "city", "town"):
        iv = _norm(location.get(field))
        lv = _norm(l_loc.get(field))
        if iv and lv and iv == lv:
            score += 1
    return score


async def assign_best_leader(
    db,
    location: Optional[dict] = None,
    category: Optional[str] = None,
) -> Optional[ObjectId]:
    """
    Returns the ObjectId of the best available leader, or None if no leaders exist.
    """
    all_leaders = await db.users.find({"role": "leader"}).to_list(length=500)
    if not all_leaders:
        return None

    loc = location or {}

    # ── Step 1: score by location ────────────────────────────────────────────
    with_loc = [(ldr, _location_score(ldr, loc)) for ldr in all_leaders]
    matched  = [(ldr, s) for ldr, s in with_loc if s >= 1]

    # Fallback: no location match → use all leaders (score = 0)
    candidates = matched if matched else with_loc

    # ── Step 2: compute performance composite ────────────────────────────────
    best_id    = None
    best_score = float("-inf")

    for leader, loc_score in candidates:
        lid = leader["_id"]

        # ── Overall stats ────────────────────────────────────────────────────
        overall_total  = await db.issues.count_documents({"leader_id": lid})
        overall_closed = await db.issues.count_documents({"leader_id": lid, "status": "CLOSED"})
        overall_rate   = (overall_closed / overall_total) if overall_total > 0 else 0.0
        is_new         = overall_total == 0

        # ── Category-specific stats ──────────────────────────────────────────
        cat_rate = 0.0
        if category:
            cat_total  = await db.issues.count_documents({"leader_id": lid, "category": category})
            cat_closed = await db.issues.count_documents({"leader_id": lid, "category": category, "status": "CLOSED"})
            # If leader has NO cases in this category treat same as new (neutral)
            cat_rate = (cat_closed / cat_total) if cat_total > 0 else overall_rate

        # ── Workload & failures ──────────────────────────────────────────────
        open_issues  = await db.issues.count_documents({
            "leader_id": lid,
            "status": {"$in": ["OPEN", "RESOLVED_L1", "RESOLVED_L2"]},
        })
        failed_cases = leader.get("failed_cases", 0)

        # ── Composite ────────────────────────────────────────────────────────
        composite = (
            loc_score                * 50
            + cat_rate               * 20
            + overall_rate           * 15   # new leaders get fair exposure
            + (1.0 if is_new else 0.0)  * 10
            - open_issues            * 5
            - failed_cases           * 3
            + random.uniform(0, 2)            # small jitter for rotation
        )

        if composite > best_score:
            best_score = composite
            best_id    = lid

    return best_id