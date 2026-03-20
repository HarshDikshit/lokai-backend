from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime
from bson import ObjectId
from typing import List, Optional

from app.middleware.auth import get_current_user, require_admin, require_leader
from app.database.connection import get_database
from models_analyze_complaint.ml_service import analyze_sentiment

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/leader")
async def leader_dashboard(current_user: dict = Depends(require_leader)):
    db = get_database()
    leader_id = current_user["_id"]
    
    total_issues = await db.issues.count_documents({"leader_id": leader_id})
    
    # Task metrics
    all_tasks = await db.tasks.find({"created_by": leader_id}).to_list(length=1000)
    # completed_tasks = sum(1 for t in all_tasks if t["status"] == "completed")
    # pending_tasks = sum(1 for t in all_tasks if t["status"] in ("pending", "in_progress"))
    
    completed_tasks = await db.issues.count_documents({"leader_id": leader_id, "status": "CLOSED"})
    pending_tasks = await db.issues.count_documents({"leader_id": leader_id, "status": ["RESOLVED_L1", "RESOLVED_L2"]})
    escalated = await db.issues.count_documents({"leader_id": leader_id, "status": "ESCALATED"})
    failed_cases = current_user.get("failed_cases", 0)
    active = await db.issues.count_documents({"leader_id": leader_id, "status": "OPEN"})
    
    # Category distribution
    pipeline = [
        {"$match": {"leader_id": leader_id}},
        {"$group": {"_id": "$category", "count": {"$sum": 1}}}
    ]
    categories = await db.issues.aggregate(pipeline).to_list(length=20)
    
    # Monthly resolution trend (last 6 months)
    from datetime import timedelta
    monthly = []
    for i in range(5, -1, -1):
        start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0) - timedelta(days=30 * i)
        end = start.replace(day=28) + timedelta(days=4)
        end = end.replace(day=1)
        count = await db.issues.count_documents({
            "leader_id": leader_id,
            "status": "CLOSED",
            "created_at": {"$gte": start, "$lt": end}
        })
        monthly.append({
            "month": start.strftime("%b %Y"),
            "resolved": count
        })
    
    return {
        "metrics": {
            "total_issues": total_issues,
            "completed_tasks": completed_tasks,
            "pending_tasks": pending_tasks,
            "escalated_cases": escalated,
            "failed_cases": failed_cases,
            "active_problems": active
        },
        "category_distribution": [{"category": c["_id"] or "Unknown", "count": c["count"]} for c in categories],
        "monthly_resolution": monthly
    }


@router.get("/admin")
async def admin_dashboard(current_user: dict = Depends(require_admin)):
    db = get_database()
    
    total_citizens = await db.users.count_documents({"role": "citizen"})
    total_leaders = await db.users.count_documents({"role": "leader"})
    total_issues = await db.issues.count_documents({})
    open_issues = await db.issues.count_documents({"status": "OPEN"})
    resolved = await db.issues.count_documents({"status": "CLOSED"})
    escalated = await db.issues.count_documents({"status": "ESCALATED"})
    
    # Leader rankings by failed_cases
    leaders = await db.users.find({"role": "leader"}).sort("failed_cases", -1).to_list(50)
    rankings = []
    for ldr in leaders:
        total = await db.issues.count_documents({"leader_id": ldr["_id"]})
        res = await db.issues.count_documents({"leader_id": ldr["_id"], "status": "CLOSED"})
        rankings.append({
            "leader_id": str(ldr["_id"]),
            "name": ldr["name"],
            "email": ldr["email"],
            "failed_cases": ldr.get("failed_cases", 0),
            "total_issues": total,
            "resolved_issues": res
        })
    
    return {
        "stats": {
            "total_citizens": total_citizens,
            "total_leaders": total_leaders,
            "total_issues": total_issues,
            "open_issues": open_issues,
            "resolved_issues": resolved,
            "escalated_issues": escalated
        },
        "leader_rankings": rankings
    }



@router.get("/authority")
async def authority_dashboard(current_user: dict = Depends(get_current_user)):
    if current_user["role"] not in ("higher_authority", "admin"):
        raise HTTPException(403, "Access denied")

    db = get_database()

    # ── Platform-wide counts ─────────────────────────────────────────────────
    total_issues    = await db.issues.count_documents({})
    open_issues     = await db.issues.count_documents({"status": "OPEN"})
    closed_issues   = await db.issues.count_documents({"status": "CLOSED"})
    escalated_count = await db.issues.count_documents({"status": "ESCALATED"})
    awaiting_count  = await db.issues.count_documents(
        {"status": {"$in": ["RESOLVED_L1", "RESOLVED_L2"]}}
    )

    # ── Leader performance table ──────────────────────────────────────────────
    leaders = await db.users.find({"role": "leader"}).to_list(length=200)
    leader_stats = []
    for ldr in leaders:
        lid          = ldr["_id"]
        total        = await db.issues.count_documents({"leader_id": lid})
        closed       = await db.issues.count_documents({"leader_id": lid, "status": "CLOSED"})
        open_c       = await db.issues.count_documents({"leader_id": lid, "status": "OPEN"})
        escalated    = await db.issues.count_documents({"leader_id": lid, "status": "ESCALATED"})
        awaiting     = await db.issues.count_documents(
            {"leader_id": lid, "status": {"$in": ["RESOLVED_L1", "RESOLVED_L2"]}}
        )
        failed       = ldr.get("failed_cases", 0)
        rate         = round(closed / total * 100, 1) if total > 0 else 0.0
        leader_stats.append({
            "leader_id":       str(lid),
            "name":            ldr["name"],
            "email":           ldr.get("email", ""),
            "phone":           ldr.get("phone"),
            "leader_location": ldr.get("leader_location"),
            "total_issues":    total,
            "closed_issues":   closed,
            "open_issues":     open_c,
            "escalated":       escalated,
            "awaiting_review": awaiting,
            "failed_cases":    failed,
            "resolution_rate": rate,
        })

    # Sort: highest failed first, then lowest resolution rate
    leader_stats.sort(key=lambda x: (-x["failed_cases"], x["resolution_rate"]))

    # ── Escalated issues with leader info ─────────────────────────────────────
    esc_issues = await db.issues.find({"status": "ESCALATED"}).sort("escalated_at", -1).to_list(50)
    escalated_list = []
    for iss in esc_issues:
        leader = await db.users.find_one({"_id": iss.get("leader_id")}) if iss.get("leader_id") else None
        citizen = await db.users.find_one({"_id": iss.get("user_id")}) if iss.get("user_id") else None
        escalated_list.append({
            "issue_id":       str(iss["_id"]),
            "title":          iss.get("title", ""),
            "description":    iss.get("description", ""),
            "category":       iss.get("category"),
            "priority_score": iss.get("priority_score"),
            "leader_id":      str(iss["leader_id"]) if iss.get("leader_id") else None,
            "leader_name":    leader["name"] if leader else None,
            "citizen_name":   citizen["name"] if citizen else None,
            "escalated_at":   iss["escalated_at"].isoformat() if iss.get("escalated_at") else None,
            "created_at":     iss["created_at"].isoformat() if iss.get("created_at") else None,
            "resolution_attempts": iss.get("resolution_attempts", 0),
        })

    return {
        "overview": {
            "total_issues":    total_issues,
            "open_issues":     open_issues,
            "closed_issues":   closed_issues,
            "escalated":       escalated_count,
            "awaiting_review": awaiting_count,
        },
        "leader_stats":   leader_stats,
        "escalated_list": escalated_list,
    }


@router.get("/citizen")
async def citizen_dashboard(current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "citizen":
        raise HTTPException(403, "Access denied")
    
    db = get_database()
    uid = current_user["_id"]
    
    total = await db.issues.count_documents({"user_id": uid})
    open_c = await db.issues.count_documents({"user_id": uid, "status": "OPEN"})
    resolved = await db.issues.count_documents({"user_id": uid, "status": "CLOSED"})
    pending_verify = await db.issues.count_documents({
        "user_id": uid, "status": {"$in": ["RESOLVED_L1", "RESOLVED_L2"]}
    })
    escalated = await db.issues.count_documents({"user_id": uid, "status": "ESCALATED"})
    
    return {
        "total_issues": total,
        "open_issues": open_c,
        "resolved_issues": resolved,
        "pending_verification": pending_verify,
        "escalated": escalated
    }


# Sentiment analysis endpoint
@router.post("/issues/{issue_id}/sentiment")
async def run_sentiment(issue_id: str, comments: List[str], current_user: dict = Depends(get_current_user)):
    db = get_database()
    
    ml_result = await analyze_sentiment(comments)
    
    sentiment_doc = {
        "issue_id": ObjectId(issue_id),
        "positive": ml_result.get("positive", 0.33),
        "negative": ml_result.get("negative", 0.33),
        "neutral": ml_result.get("neutral", 0.34),
        "created_at": datetime.utcnow()
    }
    result = await db.sentiments.insert_one(sentiment_doc)
    sentiment_doc["id"] = str(result.inserted_id)
    sentiment_doc["issue_id"] = issue_id
    return sentiment_doc


# Users list (admin/leader)
@router.get("/users")
async def list_users(role: Optional[str] = None, current_user: dict = Depends(require_leader)):
    db = get_database()
    query = {}
    if role:
        query["role"] = role
    
    users = await db.users.find(query).to_list(length=200)
    return [{
        "id": str(u["_id"]),
        "name": u["name"],
        "email": u["email"],
        "role": u["role"],
        "failed_cases": u.get("failed_cases", 0),
        "created_at": u.get("created_at")
    } for u in users]