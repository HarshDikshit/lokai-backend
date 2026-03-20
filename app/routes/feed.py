"""
app/routes/feed.py
Leader-only posting; citizens can like, comment, reply, share.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from bson import ObjectId

from app.middleware.auth import get_current_user, require_leader
from app.database.connection import get_database

router = APIRouter(prefix="/feed", tags=["Feed"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class PostCreate(BaseModel):
    content:   str
    image_url: Optional[str] = None
    tag:       Optional[str] = None   # e.g. "Update", "Alert", "Achievement"

class CommentCreate(BaseModel):
    text:       str
    parent_id:  Optional[str] = None  # set for sub-comments


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _sid(v) -> Optional[str]:
    return str(v) if v else None


def _clean(doc: dict) -> dict:
    """Stringify all ObjectId fields recursively."""
    if isinstance(doc, dict):
        return {k: _clean(v) for k, v in doc.items()}
    if isinstance(doc, list):
        return [_clean(v) for v in doc]
    if isinstance(doc, ObjectId):
        return str(doc)
    if isinstance(doc, datetime):
        return doc.isoformat()
    return doc


async def _enrich_post(post: dict, db, current_user_id: str) -> dict:
    leader = await db.users.find_one({"_id": post.get("leader_id")})
    post["id"]          = str(post.pop("_id"))
    post["leader_id"]   = _sid(post.get("leader_id"))
    post["leader_name"] = leader["name"]  if leader else "Unknown Leader"
    post["leader_dept"] = leader.get("department", "Local Government") if leader else ""
    post["liked"]       = current_user_id in [str(x) for x in post.get("likes", [])]
    post["like_count"]  = len(post.get("likes", []))
    post["likes"]       = []   # don't send full array to client
    post["share_count"] = post.get("share_count", 0)
    # Enrich comments
    comments = post.get("comments", [])
    enriched = []
    for c in comments:
        author = await db.users.find_one({"_id": c.get("author_id")})
        c["author_id"]   = _sid(c.get("author_id"))
        c["author_name"] = author["name"] if author else "Citizen"
        c["author_role"] = author.get("role", "citizen") if author else "citizen"
        c["liked"]       = current_user_id in [str(x) for x in c.get("likes", [])]
        c["like_count"]  = len(c.get("likes", []))
        c["likes"]       = []
        # sub-comments
        subs = c.get("replies", [])
        enriched_subs = []
        for s in subs:
            sub_author = await db.users.find_one({"_id": s.get("author_id")})
            s["author_id"]   = _sid(s.get("author_id"))
            s["author_name"] = sub_author["name"] if sub_author else "Citizen"
            s["author_role"] = sub_author.get("role", "citizen") if sub_author else "citizen"
            s["liked"]       = current_user_id in [str(x) for x in s.get("likes", [])]
            s["like_count"]  = len(s.get("likes", []))
            s["likes"]       = []
            enriched_subs.append(_clean(s))
        c["replies"] = enriched_subs
        enriched.append(_clean(c))
    post["comments"]       = enriched
    post["comment_count"]  = len(enriched)
    return _clean(post)


# ─── GET /feed ────────────────────────────────────────────────────────────────

@router.get("")
async def get_feed(
    skip: int = 0,
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
):
    db = get_database()
    uid = str(current_user["_id"])
    posts = await db.feed_posts.find({}).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    return [await _enrich_post(p, db, uid) for p in posts]


# ─── POST /feed ───────────────────────────────────────────────────────────────

@router.post("", status_code=201)
async def create_post(
    data: PostCreate,
    current_user: dict = Depends(require_leader),
):
    db = get_database()
    doc = {
        "leader_id":  current_user["_id"],
        "content":    data.content.strip(),
        "image_url":  data.image_url,
        "tag":        data.tag or "Update",
        "likes":      [],
        "share_count": 0,
        "comments":   [],
        "created_at": datetime.utcnow(),
    }
    result = await db.feed_posts.insert_one(doc)
    doc["_id"] = result.inserted_id
    uid = str(current_user["_id"])
    return await _enrich_post(doc, db, uid)


# ─── POST /feed/{id}/like ─────────────────────────────────────────────────────

@router.post("/{post_id}/like")
async def toggle_like(post_id: str, current_user: dict = Depends(get_current_user)):
    db  = get_database()
    uid = current_user["_id"]
    try:
        post = await db.feed_posts.find_one({"_id": ObjectId(post_id)})
    except Exception:
        raise HTTPException(400, "Invalid post ID")
    if not post:
        raise HTTPException(404, "Post not found")

    likes = post.get("likes", [])
    if uid in likes:
        await db.feed_posts.update_one({"_id": ObjectId(post_id)}, {"$pull": {"likes": uid}})
        return {"liked": False, "like_count": len(likes) - 1}
    else:
        await db.feed_posts.update_one({"_id": ObjectId(post_id)}, {"$addToSet": {"likes": uid}})
        return {"liked": True, "like_count": len(likes) + 1}


# ─── POST /feed/{id}/share ────────────────────────────────────────────────────

@router.post("/{post_id}/share")
async def share_post(post_id: str, current_user: dict = Depends(get_current_user)):
    db = get_database()
    try:
        await db.feed_posts.update_one(
            {"_id": ObjectId(post_id)},
            {"$inc": {"share_count": 1}}
        )
    except Exception:
        raise HTTPException(400, "Invalid post ID")
    return {"shared": True}


# ─── POST /feed/{id}/comments ─────────────────────────────────────────────────

@router.post("/{post_id}/comments", status_code=201)
async def add_comment(
    post_id: str,
    data: CommentCreate,
    current_user: dict = Depends(get_current_user),
):
    db = get_database()
    try:
        post = await db.feed_posts.find_one({"_id": ObjectId(post_id)})
    except Exception:
        raise HTTPException(400, "Invalid post ID")
    if not post:
        raise HTTPException(404, "Post not found")

    comment_doc = {
        "id":        str(ObjectId()),   # client-side id
        "author_id": current_user["_id"],
        "text":      data.text.strip(),
        "likes":     [],
        "replies":   [],
        "created_at": datetime.utcnow().isoformat(),
    }

    if data.parent_id:
        # Sub-comment: push into the matching comment's replies array
        await db.feed_posts.update_one(
            {"_id": ObjectId(post_id), "comments.id": data.parent_id},
            {"$push": {"comments.$.replies": comment_doc}},
        )
    else:
        await db.feed_posts.update_one(
            {"_id": ObjectId(post_id)},
            {"$push": {"comments": comment_doc}},
        )

    # Return updated post
    updated = await db.feed_posts.find_one({"_id": ObjectId(post_id)})
    uid = str(current_user["_id"])
    return await _enrich_post(updated, db, uid)


# ─── POST /feed/{id}/comments/{cid}/like ─────────────────────────────────────

@router.post("/{post_id}/comments/{comment_id}/like")
async def like_comment(
    post_id: str, comment_id: str,
    current_user: dict = Depends(get_current_user),
):
    db  = get_database()
    uid = current_user["_id"]
    try:
        post = await db.feed_posts.find_one({"_id": ObjectId(post_id)})
    except Exception:
        raise HTTPException(400, "Invalid post ID")
    if not post:
        raise HTTPException(404, "Post not found")

    comments = post.get("comments", [])
    for c in comments:
        if c.get("id") == comment_id:
            if uid in c.get("likes", []):
                await db.feed_posts.update_one(
                    {"_id": ObjectId(post_id), "comments.id": comment_id},
                    {"$pull": {"comments.$.likes": uid}},
                )
                return {"liked": False, "like_count": len(c.get("likes", [])) - 1}
            else:
                await db.feed_posts.update_one(
                    {"_id": ObjectId(post_id), "comments.id": comment_id},
                    {"$addToSet": {"comments.$.likes": uid}},
                )
                return {"liked": True, "like_count": len(c.get("likes", [])) + 1}

    raise HTTPException(404, "Comment not found")