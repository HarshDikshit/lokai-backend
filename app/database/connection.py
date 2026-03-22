"""
app/database/connection.py
MongoDB connection + idempotent index creation.

Uses create_index() without explicit names so MongoDB matches on key pattern,
never on name — this avoids IndexOptionsConflict on re-runs.
"""

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING, DESCENDING, TEXT
import os
from dotenv import load_dotenv

# pymongo 4.x renamed GEO2DSPHERE → GEOSPHERE
try:
    from pymongo import GEOSPHERE
except ImportError:
    GEOSPHERE = "2dsphere"

load_dotenv()

MONGODB_URL   = os.getenv("MONGODB_URL")
DATABASE_NAME = os.getenv("DATABASE_NAME", "lokai_db")

client:   AsyncIOMotorClient = None
database = None


async def connect_to_mongo():
    global client, database
    client   = AsyncIOMotorClient(MONGODB_URL)
    database = client[DATABASE_NAME]
    await create_indexes()
    print(f"Connected to MongoDB: {DATABASE_NAME}")


async def close_mongo_connection():
    global client
    if client:
        client.close()
        print("Disconnected from MongoDB")


async def _safe(coro):
    """Run an index creation; silently ignore 'already exists' conflicts."""
    try:
        await coro
    except Exception as e:
        msg = str(e)
        # 85 = IndexOptionsConflict, 86 = IndexKeySpecsConflict
        if "already exists" in msg or "code: 85" in msg or "code: 86" in msg:
            pass   # index is already there — that's fine
        else:
            raise


async def create_indexes():
    db = database

    # ── users ──────────────────────────────────────────────────────────────
    await _safe(db.users.create_index([("email", ASCENDING)], unique=True))
    await _safe(db.users.create_index([("role",  ASCENDING)]))

    # ── issues ─────────────────────────────────────────────────────────────
    await _safe(db.issues.create_index([("user_id",          ASCENDING)]))
    await _safe(db.issues.create_index([("leader_id",        ASCENDING)]))
    await _safe(db.issues.create_index([("status",           ASCENDING)]))
    await _safe(db.issues.create_index([("created_at",       DESCENDING)]))
    await _safe(db.issues.create_index([("priority_score",   DESCENDING)]))
    await _safe(db.issues.create_index([("category",  ASCENDING), ("status", ASCENDING)]))

    # ── tasks ──────────────────────────────────────────────────────────────
    await _safe(db.tasks.create_index([("issue_id",    ASCENDING)]))
    await _safe(db.tasks.create_index([("assigned_to", ASCENDING)]))
    await _safe(db.tasks.create_index([("status",      ASCENDING)]))

    # ── verifications ──────────────────────────────────────────────────────
    await _safe(db.verifications.create_index([("task_id", ASCENDING)]))

    # ── sentiments ─────────────────────────────────────────────────────────
    await _safe(db.sentiments.create_index([("issue_id", ASCENDING)]))

    print("Database indexes created")


def get_database():
    return database