"""
routes/clusters.py
FastAPI router for:
  – Creating issues with duplicate detection
  – Querying clusters
  – Pre-check "similar exists" endpoint
  – Citizen support action
  – Higher-authority review queue
"""

from __future__ import annotations

from typing import List, Optional
from datetime import datetime
from bson import ObjectId
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form, Query

from app.middleware.auth import get_current_user, require_leader
from app.database.connection import get_database
from utils.cloudinary_utils import upload_image_file, upload_audio_file

from model_duplicate_issue_detection.clustering_service import (
    process_new_complaint,
    check_similar_issues,
    support_existing_cluster,
)
from model_duplicate_issue_detection.review_service import get_review_queue, resolve_review
from app.services.leader_assignment import assign_best_leader

try:
    from models_analyze_complaint.ai_pipeline import run_pipeline as _run_ml_pipeline
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False


router = APIRouter(prefix="/clusters", tags=["Issue Clusters"])


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _run_ml(description: str) -> dict:
    if not ML_AVAILABLE:
        return {"category": "General", "priority_score": 0.5,
                "urgency_score": 0.5, "sentiment_score": 0.0}
    try:
        result = _run_ml_pipeline(description) or {}
        return result
    except Exception as e:
        print(f"[ML] error: {e}")
        return {"category": "General", "priority_score": 0.5,
                "urgency_score": 0.5, "sentiment_score": 0.0}


def _serialize(doc: dict) -> dict:
    """Recursively stringify ObjectIds for JSON serialisation."""
    out = {}
    for k, v in doc.items():
        if isinstance(v, ObjectId):
            out[k] = str(v)
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, dict):
            out[k] = _serialize(v)
        elif isinstance(v, list):
            out[k] = [
                _serialize(i) if isinstance(i, dict)
                else str(i) if isinstance(i, ObjectId)
                else i
                for i in v
            ]
        else:
            out[k] = v
    return out


def _parse_location(location_str: str) -> dict:
    import json
    try:
        raw = json.loads(location_str)
        lon = float(raw["longitude"])
        lat = float(raw["latitude"])
        return {
            "type":        "Point",
            "coordinates": [lon, lat],
            "state":       raw.get("state", ""),
            "city":        raw.get("city", ""),
            "town":        raw.get("town", ""),
        }
    except Exception as e:
        raise HTTPException(400, f"Invalid location JSON: {e}. "
                                 "Expected: {{\"longitude\":...,\"latitude\":...,\"city\":...,\"town\":...}}")


# ─── POST /clusters/issues  ───────────────────────────────────────────────────
# Create a raw complaint + run duplicate detection pipeline

@router.post("/issues", status_code=201)
async def create_issue_with_clustering(
    description:  str                  = Form(...),
    location:     str                  = Form(...),
    category:     Optional[str]        = Form(None),
    image:        Optional[UploadFile] = File(None),
    audio:        Optional[UploadFile] = File(None),
    current_user: dict                 = Depends(get_current_user),
):
    """
    Full pipeline:
    1. Upload media → Cloudinary
    2. Run ML (category, urgency, sentiment)
    3. Insert raw complaint into `issues`
    4. Run duplicate detection → attach to cluster or create new
    5. Return routing result + cluster_id
    """
    db = get_database()

    loc = _parse_location(location)

    # Upload media
    image_result = await upload_image_file(image, folder="lokai/issues") if image else None
    audio_result = await upload_audio_file(audio, folder="lokai/audio")  if audio else None

    # ML
    ml = _run_ml(description)
    resolved_category = category or ml.get("category", "General")

    # Leader assignment (reuse existing service)
    leader_id = await assign_best_leader(
        db,
        location={"city": loc.get("city"), "town": loc.get("town")},
        category=resolved_category,
    )

    # Insert raw complaint
    now = datetime.utcnow()
    issue_doc = {
        "user_id":          current_user["_id"],
        "description":      description,
        "category":         resolved_category,
        "location":         loc,
        "image_url":        image_result["url"]       if image_result else None,
        "image_public_id":  image_result["public_id"] if image_result else None,
        "audio_url":        audio_result["url"]       if audio_result else None,
        "audio_public_id":  audio_result["public_id"] if audio_result else None,
        "image_embedding":  None,   # populated later if CLIP is enabled
        "text_embedding":   None,   # set by clustering service
        "priority_score":   float(ml.get("priority_score", 0.5)),
        "status":           "OPEN",
        "source_type":      "citizen",
        "issue_cluster_id": None,
        "match_status":     None,
        "duplicate_score":  None,
        "leader_id":        leader_id,
        "resolution_attempts": 0,
        "resolution_notes": [],
        "created_at":       now,
        "updated_at":       now,
    }

    insert_result = await db.issues.insert_one(issue_doc)
    issue_doc["_id"] = insert_result.inserted_id

    # Duplicate detection pipeline
    routing = await process_new_complaint(db, issue_doc, ml)

    return {
        "message":         "Complaint received",
        "issue_id":        str(insert_result.inserted_id),
        "cluster_id":      routing["cluster_id"],
        "match_status":    routing["match_status"],
        "category":        resolved_category,
        "priority_score":  round(float(ml.get("priority_score", 0.5)), 3),
        "duplicate_score": routing.get("score"),
        "score_breakdown": routing.get("score_breakdown"),
    }


# ─── GET /clusters/similar  ───────────────────────────────────────────────────
# Pre-check before submitting — returns similar active clusters

@router.get("/similar")
async def find_similar_issues(
    description: str   = Query(...),
    longitude:   float = Query(...),
    latitude:    float = Query(...),
    category:    str   = Query("General"),
    current_user: dict = Depends(get_current_user),
):
    """
    Call this BEFORE creating a complaint.
    Returns up to 3 similar active clusters with similarity scores.
    The frontend can show "A similar issue already exists — do you want to
    support it?" before the citizen submits a duplicate.
    """
    db = get_database()
    similar = await check_similar_issues(db, description, longitude, latitude, category)
    return {"similar_clusters": similar, "count": len(similar)}


# ─── POST /clusters/{cluster_id}/support  ────────────────────────────────────
# Citizen supports an existing cluster (no new complaint)

@router.post("/{cluster_id}/support")
async def support_cluster(
    cluster_id:   str,
    current_user: dict = Depends(get_current_user),
):
    """
    Register a citizen's support for an existing cluster.
    Increments counts and recalculates priority without creating a new complaint.
    """
    db     = get_database()
    result = await support_existing_cluster(db, cluster_id, current_user["_id"])
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


# ─── GET /clusters  ──────────────────────────────────────────────────────────
# List clusters (filterable)

@router.get("", response_model=List[dict])
async def list_clusters(
    status:   Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    city:     Optional[str] = Query(None),
    town:     Optional[str] = Query(None),
    current_user: dict      = Depends(get_current_user),
):
    db    = get_database()
    query: dict = {}

    # Leaders only see clusters assigned to them
    if current_user["role"] == "leader":
        query["assigned_leader_id"] = current_user["_id"]

    if status:
        query["status"] = status
    if category:
        query["category"] = category
    if city:
        query["location.city"] = city
    if town:
        query["location.town"] = town

    clusters = await db.issue_clusters.find(query).sort(
        "priority_score", -1
    ).to_list(length=200)

    return [_serialize(c) for c in clusters]


# ─── GET /clusters/{cluster_id}  ─────────────────────────────────────────────

@router.get("/{cluster_id}")
async def get_cluster(
    cluster_id:   str,
    current_user: dict = Depends(get_current_user),
):
    db = get_database()
    try:
        cid = ObjectId(cluster_id)
    except Exception:
        raise HTTPException(400, "Invalid cluster_id")

    cluster = await db.issue_clusters.find_one({"_id": cid})
    if not cluster:
        raise HTTPException(404, "Cluster not found")

    return _serialize(cluster)


# ─── GET /clusters/review/queue  ─────────────────────────────────────────────
# Higher-authority review queue

@router.get("/review/queue")
async def review_queue(
    status:       str  = Query("PENDING"),
    current_user: dict = Depends(get_current_user),
):
    if current_user["role"] not in ("higher_authority", "admin"):
        raise HTTPException(403, "Access denied")

    db    = get_database()
    items = await get_review_queue(db, status)
    return {"items": items, "count": len(items)}


# ─── POST /clusters/review/{review_id}/decide  ───────────────────────────────
# Higher-authority merges or rejects a pending review

@router.post("/review/{review_id}/decide")
async def decide_review(
    review_id:    str,
    decision:     str  = Query(..., regex="^(merge|reject)$"),
    current_user: dict = Depends(get_current_user),
):
    if current_user["role"] not in ("higher_authority", "admin"):
        raise HTTPException(403, "Access denied")

    db     = get_database()
    result = await resolve_review(db, review_id, decision, current_user["_id"])
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result