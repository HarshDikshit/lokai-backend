from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import IndexModel, ASCENDING, DESCENDING
import os
from dotenv import load_dotenv
import urllib.parse

load_dotenv()

MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
DATABASE_NAME = os.getenv("DATABASE_NAME", "lokai_db")

client: AsyncIOMotorClient = None
database = None


async def connect_to_mongo():
    global client, database
    client = AsyncIOMotorClient(MONGODB_URL)
    database = client[DATABASE_NAME]
    await create_indexes()
    print(f"Connected to MongoDB: {DATABASE_NAME}")


async def close_mongo_connection():
    global client
    if client:
        client.close()
        print("Disconnected from MongoDB")


async def create_indexes():
    # Users
    await database.users.create_index([("email", ASCENDING)], unique=True)
    await database.users.create_index([("role", ASCENDING)])

    # Issues
    await database.issues.create_index([("user_id", ASCENDING)])
    await database.issues.create_index([("leader_id", ASCENDING)])
    await database.issues.create_index([("status", ASCENDING)])
    await database.issues.create_index([("created_at", DESCENDING)])
    await database.issues.create_index([("priority_score", DESCENDING)])

    # Tasks
    await database.tasks.create_index([("issue_id", ASCENDING)])
    await database.tasks.create_index([("assigned_to", ASCENDING)])
    await database.tasks.create_index([("status", ASCENDING)])

    # Verifications
    await database.verifications.create_index([("task_id", ASCENDING)])

    # Sentiments
    await database.sentiments.create_index([("issue_id", ASCENDING)])

    print("Database indexes created")


def get_database():
    return database