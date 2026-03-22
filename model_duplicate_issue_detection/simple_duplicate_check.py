"""
model_duplicate_issue_detection/simple_duplicate_check.py

Replaces the transformer/embedding pipeline with a simple, reliable
exact-duplicate check based on:
  1. User ID — same citizen
  2. Description similarity — basic text overlap (no ML model needed)
  3. Location — same city/town

No sentence-transformers, no numpy, no BERT. Zero dependencies beyond what
you already have.

This module exports two functions used by issues.py:
  - check_exact_duplicate(db, user_id, description, location) → dict | None
  - find_similar_issues_for_leader(db, issue_id) → List[dict]
"""

from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta  # timedelta kept for find_similar_issues_for_leader
from typing import Optional, List
from bson import ObjectId


# ─── Text normalisation ───────────────────────────────────────────────────────

def _normalise(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text


def _word_overlap(a: str, b: str) -> float:
    """
    Jaccard similarity on word sets.
    Returns 0.0–1.0.  1.0 = identical word sets.
    """
    wa = set(_normalise(a).split())
    wb = set(_normalise(b).split())
    if not wa or not wb:
        return 0.0
    intersection = wa & wb
    union        = wa | wb
    return len(intersection) / len(union)


# ─── Exact duplicate check (citizen submit screen) ───────────────────────────

async def check_exact_duplicate(
    db,
    user_id:     ObjectId,
    description: str,
    location:    dict,
) -> Optional[dict]:
    """
    Block duplicate submission only when the citizen still has an unresolved
    issue with similar text from the same location.

    Returns the existing issue dict if found, None otherwise.

    Criteria (ALL must be true):
      - Same user_id
      - Same city + town (from location)
      - Word overlap >= 0.70 (70% of words match)
      - Status is OPEN, RESOLVED_L1, or RESOLVED_L2
        (CLOSED and ESCALATED issues are excluded — citizen can re-report freely)

    No time limit applied. If an issue is still open from months ago it is
    still a duplicate. Once the issue is CLOSED the citizen can re-report.
    """
    city = (location.get("city") or "").strip().lower()
    town = (location.get("town") or "").strip().lower()

    # Only look at actively unresolved issues
    query = {
        "user_id": user_id,
        "status":  {"$in": ["OPEN", "RESOLVED_L1", "RESOLVED_L2"]},
    }
    if city:
        query["location.city"] = {"$regex": f"^{re.escape(city)}$", "$options": "i"}

    candidates = await db.issues.find(query).sort("created_at", -1).to_list(20)

    for issue in candidates:
        # Town check (soft — if either is blank, skip town check)
        issue_town = (
            (issue.get("location") or {}).get("town") or ""
        ).strip().lower()
        if town and issue_town and town != issue_town:
            continue

        overlap = _word_overlap(description, issue.get("description", ""))
        if overlap >= 0.70:
            return issue

    return None


# ─── Similar issues for leader view ──────────────────────────────────────────

async def find_similar_issues_for_leader(
    db,
    issue_id: str,
    limit:    int = 10,
) -> List[dict]:
    """
    Given an issue_id, find other OPEN issues:
      - Same category
      - Same city + town
      - Word overlap >= 0.40 with this issue's description
      - Different issue_id
      - Created within last 60 days

    Returns a list of simplified issue dicts for the leader's "Similar Issues" screen.
    """
    try:
        oid = ObjectId(issue_id)
    except Exception:
        return []

    source = await db.issues.find_one({"_id": oid})
    if not source:
        return []

    category = source.get("category", "")
    loc      = source.get("location") or {}
    city     = (loc.get("city") or "").strip().lower()
    town     = (loc.get("town") or "").strip().lower()
    desc     = source.get("description", "")
    since    = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=60)

    query: dict = {
        "_id":        {"$ne": oid},
        "status":     {"$in": ["OPEN", "RESOLVED_L1", "RESOLVED_L2"]},
        "created_at": {"$gte": since},
    }
    if category:
        query["category"] = category
    if city:
        query["location.city"] = {"$regex": f"^{re.escape(city)}$", "$options": "i"}

    candidates = await db.issues.find(query).sort("created_at", -1).to_list(50)

    results = []
    for issue in candidates:
        # Soft town filter
        issue_town = (
            (issue.get("location") or {}).get("town") or ""
        ).strip().lower()
        if town and issue_town and town != issue_town:
            continue

        overlap = _word_overlap(desc, issue.get("description", ""))
        if overlap >= 0.40:
            results.append({
                "id":            str(issue["_id"]),
                "description":   issue.get("description", "")[:120],
                "status":        issue.get("status", "OPEN"),
                "category":      issue.get("category", ""),
                "priority_score": issue.get("priority_score", 0.5),
                "citizen_name":   issue.get("citizen_name", ""),
                "created_at":    issue["created_at"].isoformat()
                                 if issue.get("created_at") else None,
                "overlap_score": round(overlap, 2),
                "location":      issue.get("location", {}),
            })

    # Sort by overlap descending
    results.sort(key=lambda x: x["overlap_score"], reverse=True)
    return results[:limit]