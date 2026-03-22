"""
app/routes/issues.py

Duplicate detection is now done with simple text/location matching.
No transformer models needed.

New endpoints:
  GET /issues/check-duplicate   — citizen submit screen pre-check
  GET /issues/{id}/similar      — leader "Show Similar Issues" button
"""

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form, Query
from typing import List, Optional
from datetime import datetime
from bson import ObjectId
import json

from app.schemas.Schemas import (
    IssueResolveRequest,
    CitizenVerificationRequest,
    LocationSchema,
)
from app.middleware.auth import get_current_user, require_leader
from app.database.connection import get_database
from utils.cloudinary_utils import (
    upload_image_file,
    upload_audio_file,
    delete_issue_files,
)
from app.services.leader_assignment import assign_best_leader

try:
    from models_analyze_complaint.ai_pipeline import run_pipeline
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
    print("[WARN] ML pipeline not found — category/priority will use defaults")

try:
    from model_duplicate_issue_detection.simple_duplicate_check import (
        check_exact_duplicate,
        find_similar_issues_for_leader,
    )
    DEDUP_AVAILABLE = True
    print("[INFO] Simple duplicate check loaded ✓")
except ImportError as e:
    DEDUP_AVAILABLE = False
    print(f"[WARN] Duplicate check not available: {e}")


router = APIRouter(prefix="/issues", tags=["Issues"])


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _str_id(v) -> Optional[str]:
    return str(v) if v else None


async def _enrich(issue: dict, db) -> dict:
    citizen   = await db.users.find_one({"_id": issue.get("user_id")})
    leader    = await db.users.find_one({"_id": issue.get("leader_id")}) if issue.get("leader_id") else None
    issue_oid = issue.get("_id")

    issue["id"]            = str(issue.pop("_id"))
    issue["user_id"]       = _str_id(issue.get("user_id"))
    issue["leader_id"]     = _str_id(issue.get("leader_id"))
    issue["citizen_name"]  = citizen["name"]         if citizen else "Anonymous"
    issue["citizen_phone"] = citizen.get("phone")    if citizen else None
    issue["leader_name"]   = leader["name"]          if leader  else None
    issue["leader_phone"]  = leader.get("phone")     if leader  else None

    issue_oid = ObjectId(issue["id"])
    verifications = await db.verifications.find(
        {"task_id": issue_oid}
    ).sort("timestamp", 1).to_list(length=10)

    issue["verifications"] = [
        {
            "attempt":          i + 1,
            "before_image_url": v.get("before_image_url"),
            "after_image_url":  v.get("after_image_url"),
            "latitude":         v.get("latitude"),
            "longitude":        v.get("longitude"),
            "timestamp":        v["timestamp"].isoformat() if v.get("timestamp") else None,
        }
        for i, v in enumerate(verifications)
    ]

    for key, val in list(issue.items()):
        if isinstance(val, ObjectId):
            issue[key] = str(val)

    # Strip heavy fields never needed by client
    issue.pop("text_embedding",  None)
    issue.pop("image_embedding", None)

    return issue


def _run_ml(description: str) -> dict:
    if not ML_AVAILABLE:
        return {
            "category":        "General",
            "priority_score":  0.5,
            "urgency_score":   0.5,
            "sentiment_score": 0.0,
        }
    try:
        result = run_pipeline(description) or {}
        result.setdefault("urgency_score",   0.5)
        result.setdefault("sentiment_score", 0.0)
        return result
    except Exception as e:
        print(f"[ML] pipeline error: {e}")
        return {
            "category":        "General",
            "priority_score":  0.5,
            "urgency_score":   0.5,
            "sentiment_score": 0.0,
        }


def _parse_location(location_str: str) -> dict:
    try:
        raw = json.loads(location_str)
        if not isinstance(raw, dict):
            raise ValueError("location must be a JSON object")
        lon = float(raw.get("longitude", 0.0))
        lat = float(raw.get("latitude",  0.0))
        return {
            "type":        "Point",
            "coordinates": [lon, lat],
            "state":       raw.get("state",   ""),
            "city":        raw.get("city",    ""),
            "town":        raw.get("town",    ""),
            "address":     raw.get("address", ""),
        }
    except json.JSONDecodeError:
        raise HTTPException(
            400,
            detail=(
                'location must be valid JSON. '
                'Example: {"state":"UP","city":"Kanpur","town":"Civil Lines",'
                '"longitude":80.33,"latitude":26.45}'
            ),
        )
    except Exception as e:
        raise HTTPException(400, detail=f"Invalid location data: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# STATIC ROUTES FIRST — before /{issue_id}
# ═══════════════════════════════════════════════════════════════════════════════

# ─── GET /issues/check-duplicate ─────────────────────────────────────────────
# Called by Flutter submit screen before allowing submission.

@router.get("/check-duplicate")
async def check_duplicate(
    description:  str,
    city:         str   = "",
    town:         str   = "",
    current_user: dict  = Depends(get_current_user),
):
    """
    Check if this citizen already has an open issue with very similar text
    from the same location.

    Returns:
      { "is_duplicate": false }
      { "is_duplicate": true, "existing_issue": { id, description, status, created_at } }
    """
    if not DEDUP_AVAILABLE:
        return {"is_duplicate": False}

    db       = get_database()
    location = {"city": city, "town": town}

    existing = await check_exact_duplicate(
        db,
        user_id=current_user["_id"],
        description=description,
        location=location,
    )

    if existing is None:
        return {"is_duplicate": False}

    return {
        "is_duplicate": True,
        "existing_issue": {
            "id":          str(existing["_id"]),
            "description": existing.get("description", "")[:120],
            "status":      existing.get("status", "OPEN"),
            "created_at":  existing["created_at"].isoformat()
                           if existing.get("created_at") else None,
            "category":    existing.get("category", ""),
        },
    }


# ─── GET /issues/escalated/list ───────────────────────────────────────────────

@router.get("/escalated/list")
async def get_escalated_issues(current_user: dict = Depends(get_current_user)):
    if current_user["role"] not in ("higher_authority", "admin"):
        raise HTTPException(403, "Access denied")
    db     = get_database()
    issues = await db.issues.find({"status": "ESCALATED"}).sort("created_at", -1).to_list(200)
    return [await _enrich(issue, db) for issue in issues]


# ─── GET /issues/review/queue ─────────────────────────────────────────────────

@router.get("/review/queue")
async def get_review_queue_route(current_user: dict = Depends(get_current_user)):
    if current_user["role"] not in ("higher_authority", "admin"):
        raise HTTPException(403, "Access denied")
    # Simple dedup has no review queue — return empty
    return {"items": [], "count": 0}


# ═══════════════════════════════════════════════════════════════════════════════
# COLLECTION-LEVEL ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("", response_model=List[dict])
async def get_issues(
    status:       Optional[str] = None,
    category:     Optional[str] = None,
    current_user: dict          = Depends(get_current_user),
):
    db    = get_database()
    query: dict = {}

    role = current_user["role"]
    if role == "citizen":
        query["user_id"] = current_user["_id"]
    elif role == "leader":
        query["leader_id"] = current_user["_id"]

    if status:
        query["status"] = status
    if category:
        query["category"] = category

    issues = await db.issues.find(query).sort("created_at", -1).to_list(length=200)
    return [await _enrich(issue, db) for issue in issues]


@router.post("", status_code=201)
async def create_issue(
    description:  str                  = Form(...),
    location:     str                  = Form(...),
    category:     Optional[str]        = Form(None),
    image:        Optional[UploadFile] = File(None),
    audio:        Optional[UploadFile] = File(None),
    current_user: dict                 = Depends(get_current_user),
):
    db = get_database()

    loc               = _parse_location(location)
    image_result      = await upload_image_file(image, folder="lokai/issues")
    audio_result      = await upload_audio_file(audio, folder="lokai/audio")
    ml                = _run_ml(description)
    resolved_category = category or ml.get("category", "General")
    priority_score    = float(ml.get("priority_score", 0.5))

    leader_id = await assign_best_leader(
        db,
        location={"city": loc.get("city"), "town": loc.get("town")},
        category=resolved_category,
    )

    now = datetime.utcnow()
    issue_doc = {
        "description":         description,
        "category":            resolved_category,
        "priority_score":      priority_score,
        "location":            loc,
        "user_id":             current_user["_id"],
        "leader_id":           leader_id,
        "resolution_attempts": 0,
        "status":              "OPEN",
        "source_type":         "citizen",
        "image_url":           image_result["url"]       if image_result else None,
        "image_public_id":     image_result["public_id"] if image_result else None,
        "audio_url":           audio_result["url"]       if audio_result else None,
        "audio_public_id":     audio_result["public_id"] if audio_result else None,
        "resolution_notes":    [],
        "created_at":          now,
        "updated_at":          now,
    }

    result = await db.issues.insert_one(issue_doc)

    return {
        "message":        "Issue reported successfully",
        "issue_id":       str(result.inserted_id),
        "leader_id":      _str_id(leader_id),
        "category":       resolved_category,
        "priority_score": priority_score,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# ITEM-LEVEL ROUTES — /{issue_id} MUST come after all static routes
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/{issue_id}")
async def get_issue(
    issue_id:     str,
    current_user: dict = Depends(get_current_user),
):
    db = get_database()
    try:
        issue = await db.issues.find_one({"_id": ObjectId(issue_id)})
    except Exception:
        raise HTTPException(400, "Invalid issue ID")
    if not issue:
        raise HTTPException(404, "Issue not found")
    return await _enrich(issue, db)


# ─── GET /issues/{issue_id}/similar ──────────────────────────────────────────
# Leader taps "Show Similar Issues" button on detail screen.

@router.get("/{issue_id}/similar")
async def get_similar_issues_for_leader(
    issue_id:     str,
    current_user: dict = Depends(get_current_user),
):
    """
    Returns other open issues in the same category + location with similar text.
    Used by the leader to see related complaints and resolve them together.
    """
    if not DEDUP_AVAILABLE:
        return {"similar_issues": [], "count": 0}

    db      = get_database()
    results = await find_similar_issues_for_leader(db, issue_id)
    return {"similar_issues": results, "count": len(results)}


@router.delete("/{issue_id}", status_code=204)
async def delete_issue(
    issue_id:     str,
    current_user: dict = Depends(get_current_user),
):
    db = get_database()
    try:
        issue = await db.issues.find_one({"_id": ObjectId(issue_id)})
    except Exception:
        raise HTTPException(400, "Invalid issue ID")
    if not issue:
        raise HTTPException(404, "Issue not found")

    is_owner = str(issue["user_id"]) == str(current_user["_id"])
    if not is_owner and current_user["role"] != "admin":
        raise HTTPException(403, "Not authorised to delete this issue")

    image_pids = [issue["image_public_id"]] if issue.get("image_public_id") else []
    await delete_issue_files(image_pids, issue.get("audio_public_id"))
    await db.issues.delete_one({"_id": ObjectId(issue_id)})


@router.post("/{issue_id}/resolve")
async def resolve_issue(
    issue_id:     str,
    data:         IssueResolveRequest,
    current_user: dict = Depends(require_leader),
):
    db = get_database()
    try:
        issue = await db.issues.find_one({"_id": ObjectId(issue_id)})
    except Exception:
        raise HTTPException(400, "Invalid issue ID")
    if not issue:
        raise HTTPException(404, "Issue not found")

    if current_user["role"] == "leader" and str(issue.get("leader_id")) != str(current_user["_id"]):
        raise HTTPException(403, "Not assigned to this issue")

    current_status = issue.get("status")
    if current_status not in ("OPEN", "RESOLVED_L1"):
        raise HTTPException(400, f"Cannot resolve issue with status: {current_status}")

    new_attempts = issue.get("resolution_attempts", 0) + 1
    new_status   = "RESOLVED_L1" if new_attempts == 1 else "RESOLVED_L2"

    notes = list(issue.get("resolution_notes", []))
    notes.append({
        "attempt":     new_attempts,
        "notes":       data.resolution_notes,
        "resolved_by": str(current_user["_id"]),
        "resolved_at": datetime.utcnow().isoformat(),
    })

    await db.issues.update_one(
        {"_id": ObjectId(issue_id)},
        {"$set": {
            "resolution_attempts": new_attempts,
            "status":              new_status,
            "resolution_notes":    notes,
            "updated_at":          datetime.utcnow(),
        }},
    )

    return {
        "message":             f"Issue marked as {new_status}",
        "status":              new_status,
        "resolution_attempts": new_attempts,
    }


@router.post("/{issue_id}/verify")
async def verify_resolution(
    issue_id:     str,
    data:         CitizenVerificationRequest,
    current_user: dict = Depends(get_current_user),
):
    db = get_database()
    try:
        issue = await db.issues.find_one({"_id": ObjectId(issue_id)})
    except Exception:
        raise HTTPException(400, "Invalid issue ID")
    if not issue:
        raise HTTPException(404, "Issue not found")

    is_owner = str(issue["user_id"]) == str(current_user["_id"])
    if not is_owner and current_user["role"] != "admin":
        raise HTTPException(403, "Only the issue reporter can verify resolution")

    current_status = issue.get("status")
    if current_status not in ("RESOLVED_L1", "RESOLVED_L2"):
        raise HTTPException(400, f"Issue not pending verification (status: {current_status})")

    if data.approved:
        await db.issues.update_one(
            {"_id": ObjectId(issue_id)},
            {"$set": {
                "status":     "CLOSED",
                "closed_at":  datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }},
        )
        return {"message": "Issue closed successfully", "status": "CLOSED"}

    if current_status == "RESOLVED_L1":
        await db.issues.update_one(
            {"_id": ObjectId(issue_id)},
            {"$set": {"status": "OPEN", "updated_at": datetime.utcnow()}},
        )
        return {"message": "Resolution rejected. Leader must make a second attempt.", "status": "OPEN"}

    # RESOLVED_L2 rejected → ESCALATE
    leader_id = issue.get("leader_id")
    authority = await db.users.find_one({"role": "higher_authority"})

    update = {
        "status":       "ESCALATED",
        "escalated_at": datetime.utcnow(),
        "updated_at":   datetime.utcnow(),
    }
    if authority:
        update["higher_authority_id"] = str(authority["_id"])

    await db.issues.update_one({"_id": ObjectId(issue_id)}, {"$set": update})

    if leader_id:
        lid = leader_id if isinstance(leader_id, ObjectId) else ObjectId(str(leader_id))
        await db.users.update_one({"_id": lid}, {"$inc": {"failed_cases": 1}})

    return {
        "message": "Issue escalated to Higher Authority. Leader has been flagged.",
        "status":  "ESCALATED",
    }


@router.post("/{issue_id}/override")
async def override_issue(
    issue_id:      str,
    action:        str,
    new_leader_id: Optional[str] = None,
    current_user:  dict          = Depends(get_current_user),
):
    if current_user["role"] not in ("higher_authority", "admin"):
        raise HTTPException(403, "Access denied")

    db = get_database()
    try:
        issue = await db.issues.find_one({"_id": ObjectId(issue_id)})
    except Exception:
        raise HTTPException(400, "Invalid issue ID")
    if not issue:
        raise HTTPException(404, "Issue not found")

    if action == "close":
        await db.issues.update_one(
            {"_id": ObjectId(issue_id)},
            {"$set": {
                "status":              "CLOSED",
                "closed_by_authority": True,
                "closed_at":           datetime.utcnow(),
                "updated_at":          datetime.utcnow(),
            }},
        )
        return {"message": "Issue closed by Higher Authority", "status": "CLOSED"}

    if action == "reassign":
        if not new_leader_id:
            raise HTTPException(400, "new_leader_id required for reassign")
        try:
            new_lid = ObjectId(new_leader_id)
        except Exception:
            raise HTTPException(400, "Invalid leader ID")

        new_leader = await db.users.find_one({"_id": new_lid, "role": "leader"})
        if not new_leader:
            raise HTTPException(404, "Leader not found")

        await db.issues.update_one(
            {"_id": ObjectId(issue_id)},
            {"$set": {
                "leader_id":           new_lid,
                "status":              "OPEN",
                "resolution_attempts": 0,
                "reassigned_at":       datetime.utcnow(),
                "updated_at":          datetime.utcnow(),
            }},
        )
        return {"message": f"Issue reassigned to {new_leader['name']}", "status": "OPEN"}

    raise HTTPException(400, "Invalid action. Use 'close' or 'reassign'")