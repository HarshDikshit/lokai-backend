"""
services/clustering_service.py
Core business logic for the duplicate-reduction pipeline.

Responsibilities
────────────────
1. Ingest a new raw complaint.
2. Generate its text embedding.
3. Fetch candidate clusters (geo + category filter).
4. Score against each candidate.
5. Route to: auto-merge | review queue | new cluster.
6. Update cluster stats (counts, centroid, priority).
7. Expose "similar exists" pre-check for the frontend.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from bson import ObjectId

from model_duplicate_issue_detection.embeddings import (
    get_text_embedding,
    update_centroid,
    normalize_text,
)
from model_duplicate_issue_detection.duplicate_scorer import (
    compute_duplicate_score,
    classify_match,
    AUTO_MERGE_THRESHOLD,
    REVIEW_THRESHOLD,
)
from model_duplicate_issue_detection.priority_engine import (
    calculate_cluster_priority,
    derive_severity_from_ml,
    CATEGORY_CRITICALITY,
)


# ─── Constants ────────────────────────────────────────────────────────────────

GEO_SEARCH_RADIUS_M  = 3000    # metres – MongoDB $nearSphere radius
MAX_CANDIDATES       = 20      # max clusters to score per request
SPIKE_WINDOW_HOURS   = 24


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _count_evidence(issue_doc: dict) -> int:
    count = 0
    if issue_doc.get("image_url"):
        count += 1
    if issue_doc.get("audio_url"):
        count += 1
    return count


def _auto_title(description: str, category: str) -> str:
    """Generate a short normalised title from first ~60 chars of description."""
    snippet = normalize_text(description)[:60].strip()
    return f"[{category}] {snippet}…" if len(snippet) >= 60 else f"[{category}] {snippet}"


# ─── Candidate fetcher ────────────────────────────────────────────────────────

async def _fetch_candidate_clusters(
    db,
    lon: float,
    lat: float,
    category: str,
    max_results: int = MAX_CANDIDATES,
) -> List[dict]:
    """
    Return ACTIVE clusters within GEO_SEARCH_RADIUS_M whose category either
    matches exactly or is a related category (handled by scorer weight).
    Uses MongoDB 2dsphere $nearSphere for efficient geo-filter.
    """
    related_categories = _get_related_categories(category)

    cursor = db.issue_clusters.find(
        {
            "status":   "ACTIVE",
            "category": {"$in": related_categories},
            "location": {
                "$nearSphere": {
                    "$geometry": {"type": "Point", "coordinates": [lon, lat]},
                    "$maxDistance": GEO_SEARCH_RADIUS_M,
                }
            },
        }
    ).limit(max_results)

    return await cursor.to_list(length=max_results)


def _get_related_categories(category: str) -> List[str]:
    """Return the input category plus any strongly related ones."""
    relations = {
        "Infrastructure & Roads": ["Transportation"],
        "Transportation":         ["Infrastructure & Roads"],
        "Sanitation & Waste":     ["Environment"],
        "Environment":            ["Sanitation & Waste"],
    }
    return [category] + relations.get(category, [])


# ─── Cluster stats updater ────────────────────────────────────────────────────

async def _update_cluster_on_merge(
    db,
    cluster_id: ObjectId,
    cluster:    dict,
    issue_doc:  dict,
    new_text_emb: List[float],
) -> None:
    """
    After attaching a complaint to a cluster:
    – update counts / timestamps
    – recompute centroid embedding
    – recompute priority score
    """
    now = _utcnow()

    old_count       = cluster.get("complaint_count", 0)
    old_centroid    = cluster.get("centroid_embedding") or new_text_emb
    old_unique      = cluster.get("unique_reporter_count", 0)
    old_evidence    = cluster.get("evidence_count", 0)

    # Unique reporters — only count if user not already in complaint_ids list
    existing_reporters = set(str(cid) for cid in cluster.get("complaint_ids", []))
    new_reporter_id    = str(issue_doc["user_id"])
    is_new_reporter    = new_reporter_id not in existing_reporters

    new_count    = old_count + 1
    new_unique   = old_unique + (1 if is_new_reporter else 0)
    new_evidence = old_evidence + _count_evidence(issue_doc)
    new_centroid = update_centroid(old_centroid, new_text_emb, old_count)

    # Spike count: complaints in last SPIKE_WINDOW_HOURS
    spike_cutoff = now - timedelta(hours=SPIKE_WINDOW_HOURS)
    spike_count  = await db.issues.count_documents({
        "issue_cluster_id": cluster_id,
        "created_at": {"$gte": spike_cutoff},
    })
    spike_count += 1  # include the one we're about to merge

    # Re-derive severity / urgency
    severity = cluster.get("severity_score", 0.5)
    urgency  = cluster.get("urgency_score",  0.5)

    priority_data = calculate_cluster_priority(
        severity_score   = severity,
        urgency_score    = urgency,
        unique_reporters = new_unique,
        spike_count      = spike_count,
        evidence_count   = new_evidence,
        category         = cluster["category"],
    )

    await db.issue_clusters.update_one(
        {"_id": cluster_id},
        {
            "$set": {
                "centroid_embedding":    new_centroid,
                "complaint_count":       new_count,
                "unique_reporter_count": new_unique,
                "evidence_count":        new_evidence,
                "last_reported_at":      now,
                "updated_at":            now,
                "spike_count":           spike_count,
                **{k: v for k, v in priority_data.items()},
            },
            "$push": {"complaint_ids": issue_doc["_id"]},
            "$addToSet": {
                "evidence_urls": {
                    "$each": [u for u in [
                        issue_doc.get("image_url"),
                        issue_doc.get("audio_url"),
                    ] if u]
                }
            },
        },
    )


# ─── New cluster creator ──────────────────────────────────────────────────────

async def _create_new_cluster(
    db,
    issue_doc:    dict,
    text_emb:     List[float],
    ml_result:    dict,
) -> ObjectId:
    """
    Spin up a brand-new cluster from the given issue.
    """
    now      = _utcnow()
    category = issue_doc["category"]
    loc      = issue_doc["location"]

    severity = derive_severity_from_ml(
        ml_urgency_score = ml_result.get("urgency_score", 0.5),
        sentiment_score  = ml_result.get("sentiment_score", 0.0),
    )
    urgency = float(ml_result.get("urgency_score", 0.5))

    priority_data = calculate_cluster_priority(
        severity_score   = severity,
        urgency_score    = urgency,
        unique_reporters = 1,
        spike_count      = 1,
        evidence_count   = _count_evidence(issue_doc),
        category         = category,
    )

    cluster_doc = {
        "normalized_title":    _auto_title(issue_doc["description"], category),
        "normalized_summary":  normalize_text(issue_doc["description"])[:300],
        "category":            category,
        "location":            loc,   # GeoJSON Point (centroid = first complaint)
        "centroid_embedding":  text_emb,
        "complaint_ids":       [issue_doc["_id"]],
        "supporter_ids":       [],
        "complaint_count":     1,
        "unique_reporter_count": 1,
        "evidence_count":      _count_evidence(issue_doc),
        "evidence_urls":       [u for u in [
            issue_doc.get("image_url"),
            issue_doc.get("audio_url"),
        ] if u],
        "severity_score":      severity,
        "urgency_score":       urgency,
        "category_criticality": CATEGORY_CRITICALITY.get(category, 0.3),
        "assigned_leader_id":  issue_doc.get("leader_id"),
        "status":              "ACTIVE",
        "review_candidates":   [],
        "spike_count":         1,
        "created_at":          now,
        "last_reported_at":    now,
        "updated_at":          now,
        **priority_data,
    }

    result = await db.issue_clusters.insert_one(cluster_doc)
    return result.inserted_id


# ─── Review queue writer ──────────────────────────────────────────────────────

async def _enqueue_for_review(
    db,
    issue_id:   ObjectId,
    cluster_id: ObjectId,
    score_obj,               # DuplicateScore dataclass
    reason:     str,
) -> None:
    await db.cluster_review_queue.insert_one({
        "issue_id":        issue_id,
        "cluster_id":      cluster_id,
        "score":           score_obj.total,
        "score_breakdown": score_obj.to_dict(),
        "reason":          reason,
        "status":          "PENDING",
        "reviewed_by":     None,
        "reviewed_at":     None,
        "created_at":      _utcnow(),
    })

    # Also flag cluster as needing review
    await db.issue_clusters.update_one(
        {"_id": cluster_id},
        {"$push": {
            "review_candidates": {
                "issue_id": issue_id,
                "score":    score_obj.total,
                "reason":   reason,
                "reviewed": False,
            }
        }},
    )


# ─── Main pipeline entry ──────────────────────────────────────────────────────

async def process_new_complaint(
    db,
    issue_doc: dict,     # freshly inserted issue document (with _id)
    ml_result: dict,     # output from your existing run_pipeline / analyze_issue
) -> dict:
    """
    Full duplicate-detection pipeline for one new complaint.

    Returns a routing result:
    {
        "match_status":  "auto_merged" | "pending_review" | "new_cluster",
        "cluster_id":    str,
        "score":         float | None,
        "score_breakdown": dict | None,
    }
    """
    issue_id = issue_doc["_id"]
    loc      = issue_doc["location"]
    lon, lat = loc["coordinates"]       # GeoJSON: [longitude, latitude]
    category = issue_doc["category"]
    now      = _utcnow()

    # 1. Generate embedding
    text_emb = get_text_embedding(issue_doc["description"])

    # 2. Fetch candidate clusters
    candidates = await _fetch_candidate_clusters(db, lon, lat, category)

    best_score  = None
    best_cluster = None
    best_score_obj = None

    # 3. Score against each candidate
    for cluster in candidates:
        cloc = cluster["location"]
        clon, clat = cloc["coordinates"]

        score_obj = compute_duplicate_score(
            new_text_emb     = text_emb,
            new_lon          = lon,
            new_lat          = lat,
            new_time         = now,
            new_category     = category,
            new_img_emb      = issue_doc.get("image_embedding"),

            cluster_text_emb  = cluster.get("centroid_embedding", text_emb),
            cluster_lon       = clon,
            cluster_lat       = clat,
            cluster_time      = cluster.get("last_reported_at", now),
            cluster_category  = cluster["category"],
            cluster_img_emb   = None,   # clusters don't store img centroid currently
        )

        if best_score is None or score_obj.total > best_score:
            best_score     = score_obj.total
            best_cluster   = cluster
            best_score_obj = score_obj

    # 4. Route based on best score
    if best_score is None:
        match_status = "new_cluster"
    else:
        match_status = classify_match(best_score)

    # ── Auto-merge ────────────────────────────────────────────────────────────
    if match_status == "auto_merged":
        cluster_id = best_cluster["_id"]

        await _update_cluster_on_merge(db, cluster_id, best_cluster, issue_doc, text_emb)

        await db.issues.update_one(
            {"_id": issue_id},
            {"$set": {
                "issue_cluster_id": cluster_id,
                "text_embedding":   text_emb,
                "match_status":     "auto_merged",
                "duplicate_score":  best_score,
                "updated_at":       now,
            }},
        )

        return {
            "match_status":    "auto_merged",
            "cluster_id":      str(cluster_id),
            "score":           round(best_score, 4),
            "score_breakdown": best_score_obj.to_dict(),
        }

    # ── Pending review ────────────────────────────────────────────────────────
    if match_status == "pending_review":
        cluster_id = best_cluster["_id"]

        reason = (
            f"Score {best_score:.2f} is between review threshold "
            f"({REVIEW_THRESHOLD}) and auto-merge threshold ({AUTO_MERGE_THRESHOLD}). "
            f"Components: text={best_score_obj.text_sim:.2f}, "
            f"geo={best_score_obj.geo_sim:.2f}, "
            f"time={best_score_obj.time_sim:.2f}."
        )

        await _enqueue_for_review(db, issue_id, cluster_id, best_score_obj, reason)

        # Mark the issue as pending review; no cluster link yet
        await db.issues.update_one(
            {"_id": issue_id},
            {"$set": {
                "text_embedding":   text_emb,
                "match_status":     "pending_review",
                "duplicate_score":  best_score,
                "updated_at":       now,
            }},
        )

        return {
            "match_status":    "pending_review",
            "cluster_id":      str(cluster_id),
            "score":           round(best_score, 4),
            "score_breakdown": best_score_obj.to_dict(),
        }

    # ── New cluster ───────────────────────────────────────────────────────────
    new_cluster_id = await _create_new_cluster(db, issue_doc, text_emb, ml_result)

    await db.issues.update_one(
        {"_id": issue_id},
        {"$set": {
            "issue_cluster_id": new_cluster_id,
            "text_embedding":   text_emb,
            "match_status":     "new_cluster",
            "duplicate_score":  None,
            "updated_at":       now,
        }},
    )

    return {
        "match_status":    "new_cluster",
        "cluster_id":      str(new_cluster_id),
        "score":           None,
        "score_breakdown": None,
    }


# ─── "Similar exists" pre-check (for frontend) ───────────────────────────────

async def check_similar_issues(
    db,
    description: str,
    lon:         float,
    lat:         float,
    category:    str,
) -> List[dict]:
    """
    Lightweight similarity pre-check.
    Returns top-3 candidate clusters (if any) with scores > REVIEW_THRESHOLD.
    Used by the frontend to show "similar issue already exists — do you want
    to support it instead of creating a new complaint?"
    """
    text_emb   = get_text_embedding(description)
    candidates = await _fetch_candidate_clusters(db, lon, lat, category, max_results=10)
    now        = _utcnow()

    results = []
    for cluster in candidates:
        cloc       = cluster["location"]
        clon, clat = cloc["coordinates"]

        score_obj = compute_duplicate_score(
            new_text_emb      = text_emb,
            new_lon           = lon,
            new_lat           = lat,
            new_time          = now,
            new_category      = category,
            new_img_emb       = None,
            cluster_text_emb  = cluster.get("centroid_embedding", text_emb),
            cluster_lon       = clon,
            cluster_lat       = clat,
            cluster_time      = cluster.get("last_reported_at", now),
            cluster_category  = cluster["category"],
        )

        if score_obj.total >= REVIEW_THRESHOLD:
            results.append({
                "cluster_id":        str(cluster["_id"]),
                "normalized_title":  cluster.get("normalized_title", ""),
                "category":          cluster["category"],
                "complaint_count":   cluster.get("complaint_count", 0),
                "priority_score":    cluster.get("priority_score", 0),
                "similarity_score":  round(score_obj.total, 4),
                "last_reported_at":  (
                    cluster["last_reported_at"].isoformat()
                    if cluster.get("last_reported_at") else None
                ),
            })

    results.sort(key=lambda x: x["similarity_score"], reverse=True)
    return results[:3]


# ─── Support action (citizen supports an existing cluster) ───────────────────

async def support_existing_cluster(
    db,
    cluster_id: str,
    user_id:    ObjectId,
) -> dict:
    """
    Link a user to an existing cluster as a "supporter" without creating a
    duplicate issue.  Increments complaint_count and unique_reporter_count.
    """
    try:
        cid = ObjectId(cluster_id)
    except Exception:
        return {"error": "Invalid cluster_id"}

    cluster = await db.issue_clusters.find_one({"_id": cid, "status": "ACTIVE"})
    if not cluster:
        return {"error": "Cluster not found or not active"}

    already_supporter = user_id in [s for s in cluster.get("supporter_ids", [])]
    if already_supporter:
        return {"message": "Already supporting this issue", "cluster_id": cluster_id}

    now           = _utcnow()
    old_count     = cluster.get("complaint_count", 0)
    old_unique    = cluster.get("unique_reporter_count", 0)
    old_evidence  = cluster.get("evidence_count", 0)

    # Recalculate priority with one more reporter
    priority_data = calculate_cluster_priority(
        severity_score   = cluster.get("severity_score", 0.5),
        urgency_score    = cluster.get("urgency_score",  0.5),
        unique_reporters = old_unique + 1,
        spike_count      = cluster.get("spike_count", 0),
        evidence_count   = old_evidence,
        category         = cluster["category"],
    )

    await db.issue_clusters.update_one(
        {"_id": cid},
        {
            "$addToSet": {"supporter_ids": user_id},
            "$inc": {
                "complaint_count":       1,
                "unique_reporter_count": 1,
            },
            "$set": {
                "last_reported_at": now,
                "updated_at":       now,
                **priority_data,
            },
        },
    )

    return {
        "message":    "Support registered",
        "cluster_id": cluster_id,
        "new_count":  old_count + 1,
    }