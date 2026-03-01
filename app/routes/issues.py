from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from typing import List, Optional
from datetime import datetime
from bson import ObjectId
import json

from app.schemas.Schemas import (
    IssueCreate, IssueResponse, IssueResolveRequest,
    CitizenVerificationRequest, LocationSchema
)
from app.middleware.auth import get_current_user, require_leader, require_citizen, require_any
from app.database.connection import get_database
from app.services.ml_service import analyze_issue, analyze_sentiment, score_to_urgency
from app.services.file_service import save_image, save_audio

router = APIRouter(prefix="/issues", tags=["Issues"])


def format_issue(issue: dict, citizen=None, leader=None) -> dict:
    issue["id"] = str(issue.pop("_id"))
    issue["user_id"] = str(issue.get("user_id", ""))
    issue["leader_id"] = str(issue.get("leader_id", "")) if issue.get("leader_id") else None
    issue["citizen_name"] = citizen["name"] if citizen else None
    issue["leader_name"] = leader["name"] if leader else None
    return issue


async def assign_leader(db, location: dict) -> Optional[ObjectId]:
    """Assign the leader with fewest open issues."""
    leaders = await db.users.find({"role": "leader"}).to_list(length=100)
    if not leaders:
        return None
    
    best_leader = None
    min_issues = float("inf")
    
    for leader in leaders:
        count = await db.issues.count_documents({
            "leader_id": leader["_id"],
            "status": {"$in": ["OPEN", "RESOLVED_L1", "RESOLVED_L2"]}
        })
        if count < min_issues:
            min_issues = count
            best_leader = leader
    
    return best_leader["_id"] if best_leader else None


# ─── POST /issues ─────────────────────────────────────────────────────────────
@router.post("", status_code=201)
async def create_issue(
    title: str = Form(...),
    description: str = Form(...),
    location: str = Form(...),  # JSON string
    category: Optional[str] = Form(None),
    images: List[UploadFile] = File(default=[]),
    audio: Optional[UploadFile] = File(default=None),
    current_user: dict = Depends(get_current_user)
):
    db = get_database()
    
    try:
        loc_data = json.loads(location)
        loc = LocationSchema(**loc_data)
    except Exception:
        raise HTTPException(400, "Invalid location format")
    
    # Save files
    image_urls = []
    for img in images:
        if img.filename:
            url = await save_image(img)
            image_urls.append(url)
    
    audio_url = None
    if audio and audio.filename:
        audio_url = await save_audio(audio)
    
    # Call ML API
    ml_result = await analyze_issue(title, description)
    
    # Auto-assign leader
    leader_id = await assign_leader(db, loc.dict())
    
    issue_doc = {
        "title": title,
        "description": description,
        "category": category or ml_result.get("category", "General"),
        "priority_score": ml_result.get("priority_score", 0.5),
        "urgency_level": score_to_urgency(ml_result.get("urgency_score", 0.5)),
        "location": loc.dict(),
        "user_id": current_user["_id"],
        "leader_id": leader_id,
        "resolution_attempts": 0,
        "status": "OPEN",
        "image_urls": image_urls,
        "audio_url": audio_url,
        "resolution_notes": [],
        "created_at": datetime.utcnow()
    }
    
    result = await db.issues.insert_one(issue_doc)
    issue_doc["id"] = str(result.inserted_id)
    issue_doc["user_id"] = str(current_user["_id"])
    issue_doc["leader_id"] = str(leader_id) if leader_id else None
    
    return {"message": "Issue reported successfully", "issue_id": issue_doc["id"]}


# ─── GET /issues ──────────────────────────────────────────────────────────────
@router.get("", response_model=List[dict])
async def get_issues(
    status: Optional[str] = None,
    category: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    db = get_database()
    query = {}
    
    role = current_user["role"]
    if role == "citizen":
        query["user_id"] = current_user["_id"]
    elif role == "leader":
        query["leader_id"] = current_user["_id"]
    elif role in ("admin", "higher_authority"):
        pass  # see all
    
    if status:
        query["status"] = status
    if category:
        query["category"] = category
    
    issues = await db.issues.find(query).sort("created_at", -1).to_list(length=200)
    result = []
    for issue in issues:
        citizen = await db.users.find_one({"_id": issue.get("user_id")})
        leader = await db.users.find_one({"_id": issue.get("leader_id")}) if issue.get("leader_id") else None
        issue["id"] = str(issue.pop("_id"))
        issue["user_id"] = str(issue.get("user_id", ""))
        issue["leader_id"] = str(issue["leader_id"]) if issue.get("leader_id") else None
        issue["citizen_name"] = citizen["name"] if citizen else None
        issue["leader_name"] = leader["name"] if leader else None
        result.append(issue)
    
    return result


# ─── GET /issues/{id} ────────────────────────────────────────────────────────
@router.get("/{issue_id}")
async def get_issue(issue_id: str, current_user: dict = Depends(get_current_user)):
    db = get_database()
    
    try:
        issue = await db.issues.find_one({"_id": ObjectId(issue_id)})
    except Exception:
        raise HTTPException(400, "Invalid issue ID")
    
    if not issue:
        raise HTTPException(404, "Issue not found")
    
    citizen = await db.users.find_one({"_id": issue.get("user_id")})
    leader = await db.users.find_one({"_id": issue.get("leader_id")}) if issue.get("leader_id") else None
    
    issue["id"] = str(issue.pop("_id"))
    issue["user_id"] = str(issue.get("user_id", ""))
    issue["leader_id"] = str(issue["leader_id"]) if issue.get("leader_id") else None
    issue["citizen_name"] = citizen["name"] if citizen else None
    issue["leader_name"] = leader["name"] if leader else None
    
    return issue


# ─── POST /issues/{id}/resolve ────────────────────────────────────────────────
@router.post("/{issue_id}/resolve")
async def resolve_issue(
    issue_id: str,
    data: IssueResolveRequest,
    current_user: dict = Depends(require_leader)
):
    db = get_database()
    
    try:
        issue = await db.issues.find_one({"_id": ObjectId(issue_id)})
    except Exception:
        raise HTTPException(400, "Invalid issue ID")
    
    if not issue:
        raise HTTPException(404, "Issue not found")
    
    # Only assigned leader or admin
    if current_user["role"] == "leader" and str(issue.get("leader_id")) != str(current_user["_id"]):
        raise HTTPException(403, "Not assigned to this issue")
    
    current_status = issue.get("status")
    attempts = issue.get("resolution_attempts", 0)
    
    if current_status not in ("OPEN", "RESOLVED_L1"):
        raise HTTPException(400, f"Cannot resolve issue with status: {current_status}")
    
    new_attempts = attempts + 1
    new_status = "RESOLVED_L1" if new_attempts == 1 else "RESOLVED_L2"
    
    notes = issue.get("resolution_notes", [])
    notes.append({
        "attempt": new_attempts,
        "notes": data.resolution_notes,
        "resolved_by": str(current_user["_id"]),
        "resolved_at": datetime.utcnow().isoformat()
    })
    
    await db.issues.update_one(
        {"_id": ObjectId(issue_id)},
        {"$set": {
            "resolution_attempts": new_attempts,
            "status": new_status,
            "resolution_notes": notes
        }}
    )
    
    return {
        "message": f"Issue marked as {new_status}",
        "status": new_status,
        "resolution_attempts": new_attempts
    }


# ─── POST /issues/{id}/verify ─────────────────────────────────────────────────
@router.post("/{issue_id}/verify")
async def verify_resolution(
    issue_id: str,
    data: CitizenVerificationRequest,
    current_user: dict = Depends(get_current_user)
):
    db = get_database()
    
    try:
        issue = await db.issues.find_one({"_id": ObjectId(issue_id)})
    except Exception:
        raise HTTPException(400, "Invalid issue ID")
    
    if not issue:
        raise HTTPException(404, "Issue not found")
    
    # Only the issue owner can verify
    if str(issue["user_id"]) != str(current_user["_id"]) and current_user["role"] != "admin":
        raise HTTPException(403, "Only the issue reporter can verify resolution")
    
    current_status = issue.get("status")
    if current_status not in ("RESOLVED_L1", "RESOLVED_L2"):
        raise HTTPException(400, f"Issue not pending verification (status: {current_status})")
    
    if data.approved:
        # Close the issue
        await db.issues.update_one(
            {"_id": ObjectId(issue_id)},
            {"$set": {"status": "CLOSED"}}
        )
        return {"message": "Issue closed successfully", "status": "CLOSED"}
    else:
        # Rejection logic
        attempts = issue.get("resolution_attempts", 0)
        
        if current_status == "RESOLVED_L1":
            # First rejection — reopen for second attempt
            await db.issues.update_one(
                {"_id": ObjectId(issue_id)},
                {"$set": {"status": "OPEN"}}
            )
            return {"message": "Resolution rejected. Leader must make second attempt.", "status": "OPEN"}
        
        elif current_status == "RESOLVED_L2":
            # Second rejection — ESCALATE
            leader_id = issue.get("leader_id")
            
            # Find higher authority
            authority = await db.users.find_one({"role": "higher_authority"})
            
            update_data = {
                "status": "ESCALATED",
                "escalated_at": datetime.utcnow()
            }
            if authority:
                update_data["higher_authority_id"] = authority["_id"]
            
            await db.issues.update_one({"_id": ObjectId(issue_id)}, {"$set": update_data})
            
            # Increment leader failed_cases
            if leader_id:
                await db.users.update_one(
                    {"_id": leader_id},
                    {"$inc": {"failed_cases": 1}}
                )
            
            return {
                "message": "Issue escalated to Higher Authority. Leader has been flagged.",
                "status": "ESCALATED"
            }


# ─── POST /issues/{id}/override ──────────────────────────────────────────────
@router.post("/{issue_id}/override")
async def override_issue(
    issue_id: str,
    action: str,  # "close" | "reassign"
    new_leader_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
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
            {"$set": {"status": "CLOSED", "closed_by_authority": True}}
        )
        return {"message": "Issue closed by Higher Authority", "status": "CLOSED"}
    
    elif action == "reassign":
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
                "leader_id": new_lid,
                "status": "OPEN",
                "resolution_attempts": 0
            }}
        )
        return {"message": f"Issue reassigned to {new_leader['name']}", "status": "OPEN"}
    
    raise HTTPException(400, "Invalid action")


# ─── GET /issues/escalated ───────────────────────────────────────────────────
@router.get("/escalated/list")
async def get_escalated_issues(current_user: dict = Depends(get_current_user)):
    if current_user["role"] not in ("higher_authority", "admin"):
        raise HTTPException(403, "Access denied")
    
    db = get_database()
    issues = await db.issues.find({"status": "ESCALATED"}).sort("created_at", -1).to_list(200)
    
    result = []
    for issue in issues:
        citizen = await db.users.find_one({"_id": issue.get("user_id")})
        leader = await db.users.find_one({"_id": issue.get("leader_id")}) if issue.get("leader_id") else None
        issue["id"] = str(issue.pop("_id"))
        issue["user_id"] = str(issue.get("user_id", ""))
        issue["leader_id"] = str(issue["leader_id"]) if issue.get("leader_id") else None
        issue["citizen_name"] = citizen["name"] if citizen else None
        issue["leader_name"] = leader["name"] if leader else None
        result.append(issue)
    
    return result