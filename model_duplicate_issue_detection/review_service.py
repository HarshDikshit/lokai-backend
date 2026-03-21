"""
services/review_service.py
Higher-authority review of uncertain duplicate matches.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, List
from bson import ObjectId

from model_duplicate_issue_detection.clustering_service import (
    _update_cluster_on_merge,
    _create_new_cluster,
    _utcnow,
)
from model_duplicate_issue_detection.embeddings import get_text_embedding


async def get_review_queue(db, status: str = "PENDING") -> List[dict]:
    """Return pending review items, enriched with issue + cluster info."""
    items = await db.cluster_review_queue.find(
        {"status": status}
    ).sort("created_at", -1).to_list(length=100)

    enriched = []
    for item in items:
        issue   = await db.issues.find_one({"_id": item["issue_id"]})
        cluster = await db.issue_clusters.find_one({"_id": item["cluster_id"]})

        enriched.append({
            "review_id":       str(item["_id"]),
            "issue_id":        str(item["issue_id"]),
            "cluster_id":      str(item["cluster_id"]),
            "score":           item["score"],
            "score_breakdown": item.get("score_breakdown"),
            "reason":          item.get("reason"),
            "status":          item["status"],
            "created_at":      item["created_at"].isoformat() if item.get("created_at") else None,
            # Summaries for the reviewer
            "issue_description":    issue["description"] if issue else None,
            "issue_category":       issue["category"] if issue else None,
            "cluster_title":        cluster.get("normalized_title") if cluster else None,
            "cluster_complaint_count": cluster.get("complaint_count") if cluster else None,
        })

    return enriched


async def resolve_review(
    db,
    review_id:   str,
    decision:    str,        # "merge" | "reject"
    reviewer_id: ObjectId,
    ml_result:   Optional[dict] = None,
) -> dict:
    """
    Process a reviewer's decision:
      "merge"  → attach the complaint to the candidate cluster
      "reject" → create a brand-new cluster for the complaint
    """
    try:
        rid = ObjectId(review_id)
    except Exception:
        return {"error": "Invalid review_id"}

    review = await db.cluster_review_queue.find_one({"_id": rid, "status": "PENDING"})
    if not review:
        return {"error": "Review item not found or already resolved"}

    issue   = await db.issues.find_one({"_id": review["issue_id"]})
    cluster = await db.issue_clusters.find_one({"_id": review["cluster_id"]})

    if not issue:
        return {"error": "Original complaint not found"}

    now      = _utcnow()
    text_emb = get_text_embedding(issue["description"])

    if decision == "merge" and cluster:
        await _update_cluster_on_merge(
            db, cluster["_id"], cluster, issue, text_emb
        )
        await db.issues.update_one(
            {"_id": issue["_id"]},
            {"$set": {
                "issue_cluster_id": cluster["_id"],
                "match_status":     "auto_merged",
                "updated_at":       now,
            }},
        )
        result_cluster_id = str(cluster["_id"])
        outcome = "merged"

    else:
        # reject → new cluster
        ml = ml_result or {"urgency_score": 0.5, "sentiment_score": 0.0}
        new_cid = await _create_new_cluster(db, issue, text_emb, ml)
        await db.issues.update_one(
            {"_id": issue["_id"]},
            {"$set": {
                "issue_cluster_id": new_cid,
                "match_status":     "new_cluster",
                "updated_at":       now,
            }},
        )
        result_cluster_id = str(new_cid)
        outcome = "new_cluster_created"

    # Mark review as done
    await db.cluster_review_queue.update_one(
        {"_id": rid},
        {"$set": {
            "status":      "MERGED" if decision == "merge" else "REJECTED",
            "reviewed_by": reviewer_id,
            "reviewed_at": now,
        }},
    )

    return {
        "outcome":    outcome,
        "cluster_id": result_cluster_id,
    }