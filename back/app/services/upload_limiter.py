from datetime import datetime, timedelta
from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import HTTPException

from app.models.user import AccountType, PlatformRole
from app.services.quotas import upload_limit_for  # reuse account-type logic

# Uploads per hour per account type
UPLOAD_RATE_LIMITS = {
    AccountType.STUDENT: 10,
    AccountType.RESEARCHER: 30,
    AccountType.GOVT_AGENCY: 30,
    AccountType.GLOBAL_ORG: 30,
}

DEFAULT_UPLOAD_RATE_LIMIT = 10
WINDOW = timedelta(hours=1)


def _rate_limit_for(user) -> int:
    if user is None:
        return DEFAULT_UPLOAD_RATE_LIMIT
    account_type = getattr(user, "account_type", AccountType.STUDENT)
    if getattr(user, "platform_role", None) == PlatformRole.PLATFORM_ADMIN:
        return UPLOAD_RATE_LIMITS[AccountType.GLOBAL_ORG]
    return UPLOAD_RATE_LIMITS.get(account_type, DEFAULT_UPLOAD_RATE_LIMIT)


async def check_upload_rate_limit(
    db: AsyncIOMotorDatabase,
    user_id: str,
    user_obj=None,
) -> None:
    """Raise 429 if user exceeded uploads in the last hour."""
    limit = _rate_limit_for(user_obj)
    since = datetime.utcnow() - WINDOW

    count = await db.upload_rate_counters.count_documents({
        "user_id": user_id,
        "created_at": {"$gte": since},
    })

    if count >= limit:
        retry_after = int((since + WINDOW - datetime.utcnow()).total_seconds())
        raise HTTPException(
            status_code=429,
            detail=f"Upload rate limit exceeded ({limit}/hour). Try again later.",
            headers={"Retry-After": str(max(retry_after, 1))},
        )

    # Record this upload attempt
    await db.upload_rate_counters.insert_one({
        "user_id": user_id,
        "created_at": datetime.utcnow(),
    })


async def ensure_upload_rate_index(db: AsyncIOMotorDatabase) -> None:
    """Create TTL index on upload_rate_counters (call at startup)."""
    await db.upload_rate_counters.create_index(
        "created_at",
        expireAfterSeconds=3600,  # 1 hour
        name="ttl_1_hour",
    )
