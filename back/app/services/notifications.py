from datetime import datetime, timedelta, timezone
from typing import Optional, List
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

from app.services.email import send_email
from app.config import get_settings


NOTIFICATION_TYPES = {
    # User events
    "upload_completed": {"default_severity": "info", "email": False},
    "upload_failed": {"default_severity": "warning", "email": True},
    "reprocess_completed": {"default_severity": "info", "email": False},
    "reprocess_failed": {"default_severity": "warning", "email": True},
    "forecast_unavailable": {"default_severity": "warning", "email": True},
    "dataset_shared": {"default_severity": "info", "email": False},
    "publish_request_approved": {"default_severity": "info", "email": True},
    "publish_request_declined": {"default_severity": "warning", "email": True},
    "account_approved": {"default_severity": "info", "email": True},
    "account_rejected": {"default_severity": "warning", "email": True},
    "password_changed": {"default_severity": "info", "email": True},
    "mfa_changed": {"default_severity": "info", "email": True},
    "new_device_login": {"default_severity": "warning", "email": True},
    # Org admin events
    "staff_invite_accepted": {"default_severity": "info", "email": False},
    "member_removed": {"default_severity": "warning", "email": True},
    "org_application_decision": {"default_severity": "info", "email": True},
    # Platform admin events
    "new_signup_pending": {"default_severity": "info", "email": False},
    "org_application_pending": {"default_severity": "info", "email": False},
    "refresh_reuse_spike": {"default_severity": "warning", "email": False},
    "storage_at_80_percent": {"default_severity": "warning", "email": False},
    "backup_missing_or_stale": {"default_severity": "warning", "email": False},
    "admin_without_mfa": {"default_severity": "warning", "email": False},
    "failed_background_job": {"default_severity": "warning", "email": False},
    # Opt-in
    "anomaly_detected": {"default_severity": "warning", "email": False},
    "daily_digest": {"default_severity": "info", "email": False},
}


async def ensure_notification_indexes(db: AsyncIOMotorDatabase) -> None:
    """Create indexes and TTL on notifications collection."""
    await db.notifications.create_index(
        [("user_id", 1), ("read_at", 1), ("created_at", -1)],
        name="user_read_created",
    )
    await db.notifications.create_index(
        "dedupe_key",
        unique=True,
        sparse=True,
        name="dedupe_key_unique",
    )
    # TTL: delete after 90 days
    await db.notifications.create_index(
        "created_at",
        expireAfterSeconds=90 * 24 * 3600,
        name="ttl_90_days",
    )


async def notify(
    db: AsyncIOMotorDatabase,
    user_ids: List[str],
    notif_type: str,
    title: str,
    body: str,
    link: str = "",
    severity: str = "info",
    dedupe_key: Optional[str] = None,
) -> List[str]:
    """
    Create in-app notifications for one or more users.
    Returns list of created notification IDs.
    """
    if not user_ids:
        return []

    # Validate type
    type_config = NOTIFICATION_TYPES.get(notif_type, {"default_severity": severity, "email": False})
    if severity == "info":
        severity = type_config.get("default_severity", "info")
    should_email = type_config.get("email", False)

    # Only allow internal paths to prevent open redirects from stored links.
    if link and (not link.startswith("/") or link.startswith("//") or "://" in link):
        link = ""

    created_ids = []
    now = datetime.now(timezone.utc)

    for uid in user_ids:
        uid = str(uid)
        # Respect per-user preferences
        prefs = await _preferences_for(db, uid)
        type_prefs = prefs.get(notif_type, {})
        in_app_enabled = type_prefs.get("in_app", True)
        email_enabled = should_email and type_prefs.get("email", should_email)
        if not in_app_enabled and not email_enabled:
            continue

        # Dedupe check
        if dedupe_key:
            full_dedupe = f"{notif_type}:{uid}:{dedupe_key}"
            existing = await db.notifications.find_one({"dedupe_key": full_dedupe})
            if existing:
                continue
        else:
            full_dedupe = None

        if in_app_enabled:
            notif_doc = {
                "user_id": uid,
                "type": notif_type,
                "severity": severity,
                "title": title,
                "body": body,
                "link": link,
                "dedupe_key": full_dedupe,
                "created_at": now,
                "read_at": None,
            }
            try:
                result = await db.notifications.insert_one(notif_doc)
            except DuplicateKeyError:
                # Another worker created the same deduped notification first.
                continue
            created_ids.append(str(result.inserted_id))

        # Send email if configured, preferred, and user has email
        if email_enabled:
            try:
                user = await db.users.find_one({"_id": ObjectId(uid)}, {"email": 1})
                if user and user.get("email"):
                    await send_email(
                        user["email"],
                        title,
                        f"{body}\n\n{link if link else ''}",
                    )
            except Exception:
                pass  # Log but don't fail notification

    return created_ids


async def notify_user(
    db: AsyncIOMotorDatabase,
    user_id: str,
    notif_type: str,
    title: str,
    body: str,
    link: str = "",
    severity: str = "info",
    dedupe_key: Optional[str] = None,
) -> Optional[str]:
    """Convenience: notify a single user, return notification ID or None."""
    ids = await notify(db, [user_id], notif_type, title, body, link, severity, dedupe_key)
    return ids[0] if ids else None


async def notify_admins(
    db: AsyncIOMotorDatabase,
    notif_type: str,
    title: str,
    body: str,
    link: str = "",
    severity: str = "warning",
    dedupe_key: Optional[str] = None,
) -> List[str]:
    """Notify all active platform admins."""
    # Handle both real MongoDB (with projection) and fake DB (without projection)
    try:
        admins = await db.users.find(
            {"platform_role": "platform_admin", "status": "active", "is_active": True},
            {"_id": 1},
        ).to_list(length=None)
    except TypeError:
        # Fake DB doesn't support projection param
        admins = await db.users.find(
            {"platform_role": "platform_admin", "status": "active", "is_active": True}
        ).to_list(length=None)
    admin_ids = [str(a["_id"]) for a in admins]
    return await notify(db, admin_ids, notif_type, title, body, link, severity, dedupe_key)


async def notify_org_admins(
    db: AsyncIOMotorDatabase,
    org_id: str,
    notif_type: str,
    title: str,
    body: str,
    link: str = "",
    severity: str = "info",
    dedupe_key: Optional[str] = None,
) -> List[str]:
    """Notify active org admins of a specific organization."""
    from app.models.user import OrgRole, UserStatus

    query = {
        "org_id": str(org_id),
        "org_role": OrgRole.ORG_ADMIN.value,
        "status": UserStatus.ACTIVE.value,
    }
    try:
        admins = await db.users.find(query, {"_id": 1}).to_list(length=None)
    except TypeError:
        admins = await db.users.find(query).to_list(length=None)
    return await notify(
        db, [str(a["_id"]) for a in admins], notif_type, title, body, link, severity, dedupe_key
    )


# ---- User-facing helpers ----

async def get_unread_count(db: AsyncIOMotorDatabase, user_id: str) -> int:
    return await db.notifications.count_documents({"user_id": user_id, "read_at": None})


async def list_notifications(
    db: AsyncIOMotorDatabase,
    user_id: str,
    unread_only: bool = False,
    cursor: Optional[str] = None,
    limit: int = 20,
) -> dict:
    query = {"user_id": user_id}
    if unread_only:
        query["read_at"] = None
    if cursor:
        try:
            query["_id"] = {"$lt": ObjectId(cursor)}
        except Exception:
            pass

    items = await db.notifications.find(query).sort("created_at", -1).limit(limit + 1).to_list(length=limit + 1)
    has_more = len(items) > limit
    if has_more:
        items = items[:limit]

    for item in items:
        item["id"] = str(item.pop("_id"))
    return {"items": items, "has_more": has_more, "next_cursor": str(items[-1]["id"]) if items and has_more else None}


async def mark_read(db: AsyncIOMotorDatabase, user_id: str, notification_id: str) -> bool:
    from bson import ObjectId
    result = await db.notifications.update_one(
        {"_id": ObjectId(notification_id), "user_id": user_id, "read_at": None},
        {"$set": {"read_at": datetime.now(timezone.utc)}},
    )
    return result.modified_count == 1


async def mark_all_read(db: AsyncIOMotorDatabase, user_id: str) -> int:
    result = await db.notifications.update_many(
        {"user_id": user_id, "read_at": None},
        {"$set": {"read_at": datetime.now(timezone.utc)}},
    )
    return result.modified_count


async def delete_notification(db: AsyncIOMotorDatabase, user_id: str, notification_id: str) -> bool:
    from bson import ObjectId
    result = await db.notifications.delete_one({"_id": ObjectId(notification_id), "user_id": user_id})
    return result.deleted_count == 1


# ---- Preferences ----

DEFAULT_PREFERENCES = {
    t: {"in_app": True, "email": cfg.get("email", False)}
    for t, cfg in NOTIFICATION_TYPES.items()
}


def _default_preferences() -> dict:
    return {t: dict(cfg) for t, cfg in DEFAULT_PREFERENCES.items()}


async def _preferences_for(db: AsyncIOMotorDatabase, user_id: str) -> dict:
    try:
        return await get_preferences(db, user_id)
    except AttributeError:
        return _default_preferences()


async def get_preferences(db: AsyncIOMotorDatabase, user_id: str) -> dict:
    merged = _default_preferences()
    doc = await db.notification_preferences.find_one({"_id": user_id})
    if not doc:
        return merged
    for notif_type, values in (doc.get("preferences") or {}).items():
        if isinstance(values, dict):
            merged.setdefault(notif_type, {}).update(values)
    return merged


async def update_preferences(
    db: AsyncIOMotorDatabase,
    user_id: str,
    updates: dict,
) -> dict:
    current = await get_preferences(db, user_id)
    for notif_type, values in updates.items():
        if isinstance(values, dict):
            current.setdefault(notif_type, {}).update(values)
    await db.notification_preferences.update_one(
        {"_id": user_id},
        {"$set": {"preferences": current, "updated_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    return current
