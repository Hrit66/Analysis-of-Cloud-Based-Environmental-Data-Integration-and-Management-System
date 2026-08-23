from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.config import get_settings


class Database:
    client: AsyncIOMotorClient = None
    db: AsyncIOMotorDatabase = None


db = Database()


async def connect_to_mongo():
    settings = get_settings()
    db.client = AsyncIOMotorClient(settings.MONGO_URI)
    db.db = db.client[settings.DB_NAME]
    await db.db.command("ping")
    await create_indexes()


async def close_mongo_connection():
    if db.client:
        db.client.close()


async def create_indexes():
    await db.db.datasets.create_index("status")
    await db.db.datasets.create_index("created_at")
    await db.db.air_quality.create_index([("dataset_id", 1), ("timestamp", 1)])
    await db.db.air_quality.create_index("location")