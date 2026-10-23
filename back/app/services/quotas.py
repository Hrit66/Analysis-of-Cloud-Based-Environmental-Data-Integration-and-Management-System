import inspect
from dataclasses import dataclass
from typing import Optional

from bson import ObjectId
from fastapi import HTTPException, UploadFile
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.user import AccountType, PlatformRole, UserInDB


@dataclass(frozen=True)
class Quota:
    datasets: int
    rows: int
    storage_bytes: int
    exports_per_hour: int
    api_keys: int


QUOTAS = {
    AccountType.STUDENT: Quota(10, 250_000, 25 * 1024 * 1024, 5, 0),           # 25 MB
    AccountType.RESEARCHER: Quota(50, 1_000_000, 100 * 1024 * 1024, 15, 3),     # 100 MB
    AccountType.GOVT_AGENCY: Quota(100, 5_000_000, 200 * 1024 * 1024, 30, 10),  # 200 MB
    AccountType.GLOBAL_ORG: Quota(200, 10_000_000, 400 * 1024 * 1024, 60, 20),  # 400 MB
}

# Maximum single-file upload size per account type (bytes)
UPLOAD_SIZE_LIMITS = {
    AccountType.STUDENT: 25 * 1024 * 1024,      # 25 MB
    AccountType.RESEARCHER: 100 * 1024 * 1024,   # 100 MB
    AccountType.GOVT_AGENCY: 100 * 1024 * 1024,  # 100 MB
    AccountType.GLOBAL_ORG: 100 * 1024 * 1024,   # 100 MB
}

DEFAULT_UPLOAD_LIMIT = 25 * 1024 * 1024  # 25 MB for anonymous/unrecognized

# Platform-wide storage cap (512 MB total across all users)
PLATFORM_STORAGE_CAP_BYTES = 512 * 1024 * 1024

async def get_platform_storage_used(db: AsyncIOMotorDatabase) -> int:
    """Total storage used by all non-failed datasets."""
    collection = db.datasets

    # Fake test databases store documents in .docs. Access it without
    # hasattr(), because Motor resolves unknown attributes to subcollections.
    try:
        docs = object.__getattribute__(collection, "docs")
    except AttributeError:
        docs = None
    if isinstance(docs, (list, tuple)):
        return sum(
            doc.get("file_size_bytes") or 0
            for doc in docs
            if doc.get("status") != "failed"
        )

    # Real MongoDB: aggregate the total in one query.
    try:
        pipeline = [
            {"$match": {"status": {"$ne": "failed"}}},
            {"$group": {"_id": None, "total": {"$sum": {"$ifNull": ["$file_size_bytes", 0]}}}},
        ]
        cursor = collection.aggregate(pipeline)
        if inspect.iscoroutine(cursor):
            cursor.close()
            raise TypeError("aggregate() is not awaitable in this database double")
        result = await cursor.to_list(length=1)
        return result[0].get("total", 0) if result else 0
    except Exception:
        pass

    # Last resort for simple database doubles that expose find().
    total = 0
    cursor = collection.find({"status": {"$ne": "failed"}}, {"file_size_bytes": 1})
    if inspect.iscoroutine(cursor):
        cursor.close()
        return 0
    if hasattr(cursor, "__aiter__"):
        async for doc in cursor:
            total += doc.get("file_size_bytes") or 0
    else:
        for doc in cursor:
            total += doc.get("file_size_bytes") or 0
    return total


def upload_limit_for(user) -> int:
    if user is None:
        return DEFAULT_UPLOAD_LIMIT
    account_type = getattr(user, "account_type", AccountType.STUDENT)
    if getattr(user, "platform_role", None) == PlatformRole.PLATFORM_ADMIN:
        return UPLOAD_SIZE_LIMITS[AccountType.GLOBAL_ORG]
    return UPLOAD_SIZE_LIMITS.get(account_type, DEFAULT_UPLOAD_LIMIT)


async def enforce_upload_size_limit(file: UploadFile, limit: int) -> None:
    """Stream the upload and abort with 413 if limit exceeded."""
    CHUNK = 1024 * 1024  # 1 MB chunks
    total = 0
    while True:
        chunk = await file.read(CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(
                status_code=413,
                detail=f"File size exceeds {limit // (1024*1024)} MB limit for your account type",
            )
    # Reset stream position for downstream readers
    await file.seek(0)


def quota_for(user) -> Quota:
    if user is None:
        return QUOTAS[AccountType.STUDENT]
    account_type = getattr(user, "account_type", AccountType.STUDENT)
    if getattr(user, "platform_role", None) == PlatformRole.PLATFORM_ADMIN:
        return QUOTAS[AccountType.GLOBAL_ORG]
    return QUOTAS.get(account_type, QUOTAS[AccountType.STUDENT])


def quota_public(user) -> dict:
    return _quota_dict(quota_for(user))


def _quota_dict(quota: Quota) -> dict:
    return {
        "datasets": quota.datasets,
        "rows": quota.rows,
        "storage_bytes": quota.storage_bytes,
        "exports_per_hour": quota.exports_per_hour,
        "api_keys": quota.api_keys,
    }


async def effective_quota(db: AsyncIOMotorDatabase, user) -> Quota:
    from app.services.system_settings import get_system_settings

    base = quota_for(user)
    settings = await get_system_settings(db)
    overrides = settings.get("quota_overrides") or {}
    account_type = getattr(user, "account_type", AccountType.STUDENT)
    key = account_type.value if hasattr(account_type, "value") else str(account_type)
    values = overrides.get(key) if isinstance(overrides, dict) else None
    data = _quota_dict(base)
    if isinstance(values, dict):
        for field in data:
            if field in values and isinstance(values[field], int) and values[field] >= 0:
                data[field] = values[field]
    user_values = getattr(user, "quota_overrides", None)
    if isinstance(user_values, dict):
        for field in data:
            if field in user_values and isinstance(user_values[field], int) and user_values[field] >= 0:
                data[field] = user_values[field]
    return Quota(**data)


async def quota_public_for(db: AsyncIOMotorDatabase, user) -> dict:
    return _quota_dict(await effective_quota(db, user))


async def usage_for_user(db: AsyncIOMotorDatabase, user: UserInDB) -> dict:
    query = {"user_id": str(user.id), "status": {"$ne": "failed"}}
    cursor = db.datasets.find(query, {"row_count": 1, "file_size_bytes": 1})
    datasets = 0
    rows = 0
    storage = 0
    async for doc in cursor:
        datasets += 1
        rows += int(doc.get("row_count") or 0)
        storage += int(doc.get("file_size_bytes") or 0)
    return {"datasets": datasets, "rows": rows, "storage_bytes": storage}


async def enforce_upload_quota(
    db: AsyncIOMotorDatabase,
    user: Optional[UserInDB],
    content_bytes: int,
) -> None:
    """Check storage quota only (called after upload)."""
    # Platform-wide cap check (applies to all users including anonymous)
    platform_used = await get_platform_storage_used(db)
    if platform_used + content_bytes > PLATFORM_STORAGE_CAP_BYTES:
        raise HTTPException(
            status_code=429,
            detail=f"Platform storage limit reached ({platform_used / 1024 / 1024:.1f} MB / 512 MB). Cannot accept more data.",
        )

    if user is None:
        return
    quota = await effective_quota(db, user)
    usage = await usage_for_user(db, user)
    if usage["datasets"] >= quota.datasets:
        raise HTTPException(status_code=429, detail="Dataset quota reached for this account type")
    if usage["rows"] >= quota.rows:
        raise HTTPException(status_code=429, detail="Row quota reached for this account type")
    if usage["storage_bytes"] + content_bytes > quota.storage_bytes:
        raise HTTPException(status_code=429, detail="Storage quota reached for this account type")


def estimate_rows_from_bytes(content: bytes, dataset_type: str = "") -> int:
    """Rough row estimate from file size (used for pre-check)."""
    if not content:
        return 0
    # Heuristic: average bytes per row varies by format
    # CSV: ~100-200 bytes/row, JSON: ~200-500, Excel similar to CSV
    # Conservative: assume 100 bytes/row for CSV, 200 for JSON, 150 for Excel
    if dataset_type in ("air_quality", "water_quality", "temperature", "rainfall"):
        return max(1, len(content) // 150)
    return max(1, len(content) // 200)


async def precheck_quotas(
    db: AsyncIOMotorDatabase,
    user: Optional[UserInDB],
    estimated_rows: int,
    content_bytes: int,
) -> None:
    """Pre-check quotas BEFORE processing — reject early with clear message."""
    if user is None:
        return
    quota = await effective_quota(db, user)
    usage = await usage_for_user(db, user)

    if usage["datasets"] >= quota.datasets:
        raise HTTPException(status_code=429, detail=f"Dataset quota reached ({usage['datasets']}/{quota.datasets})")

    projected_rows = usage["rows"] + estimated_rows
    if projected_rows > quota.rows:
        raise HTTPException(
            status_code=429,
            detail=f"This upload would exceed your row quota: {projected_rows:,} > {quota.rows:,} (current: {usage['rows']:,})",
        )

    if usage["storage_bytes"] + content_bytes > quota.storage_bytes:
        raise HTTPException(
            status_code=429,
            detail=f"This upload would exceed your storage quota: {(usage['storage_bytes'] + content_bytes) / 1024 / 1024:.1f} MB > {quota.storage_bytes / 1024 / 1024:.1f} MB",
        )
