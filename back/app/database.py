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
    # Ensure notification indexes
    from app.services.notifications import ensure_notification_indexes
    await ensure_notification_indexes(db.db)
    
    specs = [
        ("datasets", "status", {}),
        ("datasets", "created_at", {}),
        ("air_quality", [("dataset_id", 1), ("timestamp", 1)], {}),
        ("air_quality", "location", {}),
        ("water_quality", [("dataset_id", 1), ("timestamp", 1)], {}),
        ("water_quality", "location", {}),
        ("users", "email", {"unique": True}),
        ("users", "org_id", {}),
        ("users", "status", {}),
        ("organizations", "status", {}),
        ("organizations", "domains", {}),
        ("organizations", "contact_email", {}),
        ("refresh_tokens", "token_hash", {"unique": True}),
        ("refresh_tokens", "user_id", {}),
        ("refresh_tokens", "expires_at", {"expireAfterSeconds": 0}),
        ("one_time_tokens", "token_hash", {"unique": True}),
        ("one_time_tokens", "kind", {}),
        ("one_time_tokens", "expires_at", {"expireAfterSeconds": 0}),
        ("audit_log", [("org_id", 1), ("created_at", -1)], {}),
        ("audit_log", "created_at", {}),
        ("audit_log", "action", {}),
        ("audit_log", "actor_email", {}),
        ("audit_log", "result", {}),
        ("upload_rate_counters", "created_at", {"expireAfterSeconds": 3600}),
    ]
    for collection_name, spec, options in specs:
        try:
            await getattr(db.db, collection_name).create_index(spec, **options)
        except Exception as exc:
            print(f"Warning: failed to create index on {collection_name} {spec}: {exc}")