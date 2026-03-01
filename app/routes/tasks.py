from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from datetime import datetime
from bson import ObjectId

from app.schemas.Schemas import TaskCreate, TaskUpdate, TaskResponse
from app.middleware.auth import get_current_user, require_leader
from app.database.connection import get_database

router = APIRouter(prefix="/tasks", tags=["Tasks"])


def fmt_task(task: dict, issue=None, assignee=None) -> dict:
    task["id"] = str(task.pop("_id"))
    task["issue_id"] = str(task.get("issue_id", ""))
    task["assigned_to"] = str(task.get("assigned_to", ""))
    task["issue_title"] = issue["title"] if issue else None
    task["assignee_name"] = assignee["name"] if assignee else None
    return task


@router.post("", status_code=201)
async def create_task(data: TaskCreate, current_user: dict = Depends(require_leader)):
    db = get_database()
    
    # Validate issue
    try:
        issue = await db.issues.find_one({"_id": ObjectId(data.issue_id)})
    except Exception:
        raise HTTPException(400, "Invalid issue ID")
    if not issue:
        raise HTTPException(404, "Issue not found")
    
    # Validate assignee
    try:
        assignee = await db.users.find_one({"_id": ObjectId(data.assigned_to)})
    except Exception:
        raise HTTPException(400, "Invalid assignee ID")
    if not assignee:
        raise HTTPException(404, "Assignee not found")
    
    task_doc = {
        "issue_id": ObjectId(data.issue_id),
        "assigned_to": ObjectId(data.assigned_to),
        "deadline": data.deadline,
        "description": data.description,
        "status": "pending",
        "created_by": current_user["_id"],
        "created_at": datetime.utcnow()
    }
    result = await db.tasks.insert_one(task_doc)
    
    return {"message": "Task created", "task_id": str(result.inserted_id)}


@router.get("", response_model=List[dict])
async def get_tasks(
    status: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    db = get_database()
    query = {}
    
    if current_user["role"] == "leader":
        query["created_by"] = current_user["_id"]
    elif current_user["role"] == "citizen":
        # Citizens see tasks on their issues
        citizen_issues = await db.issues.find(
            {"user_id": current_user["_id"]}
        ).to_list(length=500)
        issue_ids = [i["_id"] for i in citizen_issues]
        query["issue_id"] = {"$in": issue_ids}
    
    if status:
        query["status"] = status
    
    tasks = await db.tasks.find(query).sort("created_at", -1).to_list(200)
    result = []
    for task in tasks:
        issue = await db.issues.find_one({"_id": task.get("issue_id")})
        assignee = await db.users.find_one({"_id": task.get("assigned_to")})
        task["id"] = str(task.pop("_id"))
        task["issue_id"] = str(task.get("issue_id", ""))
        task["assigned_to"] = str(task.get("assigned_to", ""))
        task["created_by"] = str(task.get("created_by", ""))
        task["issue_title"] = issue["title"] if issue else None
        task["assignee_name"] = assignee["name"] if assignee else None
        result.append(task)
    return result


@router.get("/{task_id}")
async def get_task(task_id: str, current_user: dict = Depends(get_current_user)):
    db = get_database()
    try:
        task = await db.tasks.find_one({"_id": ObjectId(task_id)})
    except Exception:
        raise HTTPException(400, "Invalid task ID")
    if not task:
        raise HTTPException(404, "Task not found")
    
    issue = await db.issues.find_one({"_id": task.get("issue_id")})
    assignee = await db.users.find_one({"_id": task.get("assigned_to")})
    task["id"] = str(task.pop("_id"))
    task["issue_id"] = str(task.get("issue_id", ""))
    task["assigned_to"] = str(task.get("assigned_to", ""))
    task["created_by"] = str(task.get("created_by", ""))
    task["issue_title"] = issue["title"] if issue else None
    task["assignee_name"] = assignee["name"] if assignee else None
    return task


@router.put("/{task_id}")
async def update_task(
    task_id: str,
    data: TaskUpdate,
    current_user: dict = Depends(require_leader)
):
    db = get_database()
    try:
        task = await db.tasks.find_one({"_id": ObjectId(task_id)})
    except Exception:
        raise HTTPException(400, "Invalid task ID")
    if not task:
        raise HTTPException(404, "Task not found")
    
    update = {k: v for k, v in data.dict().items() if v is not None}
    if "assigned_to" in update:
        try:
            update["assigned_to"] = ObjectId(update["assigned_to"])
        except Exception:
            raise HTTPException(400, "Invalid assignee ID")
    
    if not update:
        raise HTTPException(400, "No fields to update")
    
    update["updated_at"] = datetime.utcnow()
    await db.tasks.update_one({"_id": ObjectId(task_id)}, {"$set": update})
    return {"message": "Task updated successfully"}


@router.delete("/{task_id}")
async def delete_task(task_id: str, current_user: dict = Depends(require_leader)):
    db = get_database()
    try:
        result = await db.tasks.delete_one({"_id": ObjectId(task_id)})
    except Exception:
        raise HTTPException(400, "Invalid task ID")
    if result.deleted_count == 0:
        raise HTTPException(404, "Task not found")
    return {"message": "Task deleted"}