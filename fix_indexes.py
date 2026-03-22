"""
fix_indexes.py
──────────────
Run this ONCE in your Colab/server terminal to create the missing
2dsphere index on issue_clusters (and all other clustering indexes).

Usage:
    python fix_indexes.py

This is safe to run multiple times — MongoDB ignores duplicate index requests.
"""

import asyncio
import os
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING, DESCENDING, GEOSPHERE

load_dotenv()

MONGODB_URL   = os.getenv("MONGODB_URL")
DATABASE_NAME = os.getenv("DATABASE_NAME", "lokai_db")


async def fix():
    print(f"Connecting to {DATABASE_NAME}...")
    client = AsyncIOMotorClient(MONGODB_URL)
    db     = client[DATABASE_NAME]

    print("Creating missing indexes...")

    # ── issue_clusters — THE critical one ─────────────────────────────────────
    await db.issue_clusters.create_index(
        [("location", GEOSPHERE)],
        name="location_2dsphere",
    )
    print("  ✓  issue_clusters.location  (2dsphere)")

    await db.issue_clusters.create_index(
        [("category", ASCENDING), ("status", ASCENDING)],
        name="category_status",
    )
    print("  ✓  issue_clusters.category + status")

    await db.issue_clusters.create_index(
        [("priority_score", DESCENDING)],
        name="priority_score_desc",
    )
    print("  ✓  issue_clusters.priority_score")

    await db.issue_clusters.create_index(
        [("last_reported_at", DESCENDING)],
        name="last_reported_at_desc",
    )
    print("  ✓  issue_clusters.last_reported_at")

    await db.issue_clusters.create_index(
        [("assigned_leader_id", ASCENDING)],
        name="assigned_leader_id",
    )
    print("  ✓  issue_clusters.assigned_leader_id")

    await db.issue_clusters.create_index(
        [("status", ASCENDING)],
        name="status",
    )
    print("  ✓  issue_clusters.status")

    # ── issues — add clustering-related indexes if missing ────────────────────
    await db.issues.create_index(
        [("location", GEOSPHERE)],
        name="location_2dsphere",
    )
    print("  ✓  issues.location  (2dsphere)")

    await db.issues.create_index(
        [("issue_cluster_id", ASCENDING)],
        name="issue_cluster_id",
    )
    print("  ✓  issues.issue_cluster_id")

    await db.issues.create_index(
        [("match_status", ASCENDING)],
        name="match_status",
    )
    print("  ✓  issues.match_status")

    # ── cluster_review_queue ──────────────────────────────────────────────────
    await db.cluster_review_queue.create_index(
        [("status",     ASCENDING)],
        name="status",
    )
    await db.cluster_review_queue.create_index(
        [("issue_id",   ASCENDING)],
        name="issue_id",
    )
    await db.cluster_review_queue.create_index(
        [("cluster_id", ASCENDING)],
        name="cluster_id",
    )
    await db.cluster_review_queue.create_index(
        [("created_at", DESCENDING)],
        name="created_at_desc",
    )
    print("  ✓  cluster_review_queue indexes")

    client.close()
    print("\nAll indexes created. You can restart the server now.")


if __name__ == "__main__":
    asyncio.run(fix())