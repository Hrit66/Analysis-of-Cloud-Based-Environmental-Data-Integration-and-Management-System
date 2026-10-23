"""Read-only and controlled platform-administration endpoints."""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.api.auth import get_database, require_platform_admin
from app.models.admin import AdminDatasetAction, AdminSettingsUpdate, AdminUserAction
from app.models.user import AccountType, PlatformRole, UserStatus
from app.services.anomaly_detector import purge_dataset_models as purge_anomaly_models
from app.services.auth import (
    _normalize_user_doc,
    bump_token_version,
    create_one_time_token,
    get_user_by_id,
    write_audit,
)
from app.services.email import password_reset_link, send_email
from app.services.notifications import notify_admins
from app.services.dataset_meta import source_tag_for
from app.services.forecaster import purge_dataset_models as purge_forecast_models
from app.services.organizations import normalize_domains
from app.services.quotas import quota_public_for
from app.services.system_settings import get_system_settings, save_system_settings

router = APIRouter(prefix="/api/admin", tags=["admin"])

STORAGE_LIMIT_BYTES = 512 * 1024 * 1024


def _dt(value) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _dataset_owner(doc: dict) -> str:
    return str(doc.get("owner_id") or doc.get("user_id") or "")


async def _resolve_audit_targets(database: AsyncIOMotorDatabase, docs: list[dict]) -> dict:
    """Resolve raw target IDs to readable labels for the audit view."""
    ids = set()
    for doc in docs:
        try:
            ids.add(ObjectId(str(doc.get("target"))))
        except Exception:
            continue
    if not ids:
        return {}

    labels: dict[str, dict] = {}
    lookups = (
        ("users", "user", ("email", "full_name")),
        ("datasets", "dataset", ("filename", "name")),
        ("organizations", "organization", ("name",)),
    )
    for collection_name, target_type, fields in lookups:
        collection = getattr(database, collection_name, None)
        if collection is None:
            continue
        rows = await collection.find({"_id": {"$in": list(ids)}}).to_list(length=None)
        for row in rows:
            label = next((row.get(field) for field in fields if row.get(field)), None)
            if label:
                labels[str(row["_id"])] = {
                    "target_label": label,
                    "target_type": target_type,
                }
    return labels


async def _org_names(database: AsyncIOMotorDatabase) -> dict:
    docs = await database.organizations.find({}, {"name": 1}).to_list(length=None)
    return {str(doc["_id"]): doc.get("name") for doc in docs}


async def _storage_by_owner(database: AsyncIOMotorDatabase) -> dict:
    try:
        rows = await database.datasets.aggregate([
            {"$match": {"status": {"$ne": "failed"}}},
            {"$project": {
                "owner": {"$ifNull": ["$owner_id", "$user_id"]},
                "size": {"$ifNull": ["$file_size_bytes", 0]},
            }},
            {"$group": {
                "_id": "$owner",
                "storage_bytes": {"$sum": "$size"},
                "dataset_count": {"$sum": 1},
            }},
        ]).to_list(length=None)
        return {
            str(row["_id"]): {
                "storage_bytes": int(row.get("storage_bytes") or 0),
                "dataset_count": int(row.get("dataset_count") or 0),
            }
            for row in rows if row.get("_id")
        }
    except Exception:
        docs = await database.datasets.find(
            {}, {"owner_id": 1, "user_id": 1, "file_size_bytes": 1}
        ).to_list(length=None)
        result = {}
        for doc in docs:
            owner = _dataset_owner(doc)
            if not owner:
                continue
            entry = result.setdefault(owner, {"storage_bytes": 0, "dataset_count": 0})
            entry["storage_bytes"] += int(doc.get("file_size_bytes") or 0)
            entry["dataset_count"] += 1
        return result


def _admin_user_row(doc: dict, org_names: dict, storage: dict) -> dict:
    data = _normalize_user_doc(doc)
    user_id = str(data.get("id") or data.get("_id") or "")
    org_id = data.get("org_id")
    usage = storage.get(user_id, {})
    return {
        "id": user_id,
        "email": data.get("email"),
        "full_name": data.get("full_name"),
        "account_type": data.get("account_type"),
        "org_id": org_id,
        "org_name": org_names.get(str(org_id)) if org_id else None,
        "org_role": data.get("org_role"),
        "platform_role": data.get("platform_role"),
        "status": data.get("status"),
        "is_active": bool(data.get("is_active", True)),
        "email_verified": bool(data.get("email_verified", True)),
        "mfa_enabled": bool(data.get("mfa_enabled", False)),
        "must_change_password": bool(data.get("must_change_password", False)),
        "last_login_at": data.get("last_login_at"),
        "locked_until": data.get("locked_until"),
        "failed_login_attempts": int(data.get("failed_login_attempts") or 0),
        "storage_bytes": int(usage.get("storage_bytes") or 0),
        "dataset_count": int(usage.get("dataset_count") or 0),
        "created_at": data.get("created_at"),
        "review_reason": data.get("review_reason"),
        "quota_overrides": data.get("quota_overrides") or {},
    }


def _dataset_row(doc: dict, users: dict, org_names: dict) -> dict:
    owner_id = _dataset_owner(doc)
    owner = users.get(owner_id, {})
    org_id = doc.get("org_id")
    return {
        "id": str(doc.get("_id")),
        "filename": doc.get("filename"),
        "display_name": doc.get("display_name") or doc.get("filename"),
        "dataset_type": doc.get("dataset_type"),
        "status": doc.get("status"),
        "owner_id": owner_id or None,
        "owner_email": owner.get("email"),
        "owner_name": owner.get("full_name"),
        "org_id": org_id,
        "org_name": org_names.get(str(org_id)) if org_id else None,
        "row_count": int(doc.get("row_count") or 0),
        "file_size_bytes": int(doc.get("file_size_bytes") or 0),
        "created_at": doc.get("created_at"),
        "visibility": doc.get("visibility") or ("private" if owner_id else "reference"),
        "source_tag": source_tag_for(doc),
        "publish_requested_at": doc.get("publish_requested_at"),
        "publish_request_reason": doc.get("publish_request_reason"),
        "error_message": doc.get("error_message"),
    }


async def _notify_dataset_owner(database: AsyncIOMotorDatabase, doc: dict, subject: str, body: str) -> None:
    owner_id = _dataset_owner(doc)
    if not owner_id:
        return
    try:
        owner = await database.users.find_one({"_id": ObjectId(owner_id)}, {"email": 1})
    except Exception:
        owner = None
    if owner and owner.get("email"):
        await send_email(owner["email"], subject, body)


async def _active_platform_admins(database: AsyncIOMotorDatabase, exclude_id: Optional[str] = None) -> int:
    docs = await database.users.find({
        "platform_role": PlatformRole.PLATFORM_ADMIN.value,
        "status": UserStatus.ACTIVE.value,
    }).to_list(length=None)
    return sum(1 for doc in docs if str(doc.get("_id")) != str(exclude_id or ""))


@router.get("/overview")
async def overview(
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(require_platform_admin),
):
    now = datetime.utcnow()
    day_ago = now - timedelta(hours=24)
    week_ago = now - timedelta(days=7)
    db_ok = True
    try:
        await database.command("ping")
    except Exception:
        db_ok = False
    pending_users = await database.users.count_documents({"status": UserStatus.PENDING_APPROVAL.value})
    pending_orgs = await database.organizations.count_documents({
        "status": {"$in": ["pending", "info_requested"]},
    })
    failed_jobs = await database.datasets.count_documents({"status": "failed"})
    locked = await database.users.count_documents({"locked_until": {"$gt": now}})
    recent_errors = await database.audit_log.count_documents({
        "created_at": {"$gte": day_ago}, "result": "failure",
    })
    failed_logins = await database.audit_log.count_documents({
        "action": "auth.login_failed", "created_at": {"$gte": day_ago},
    })
    reuse = await database.audit_log.count_documents({
        "action": "auth.refresh_reuse", "created_at": {"$gte": week_ago},
    })
    admins = await database.users.find({
        "platform_role": PlatformRole.PLATFORM_ADMIN.value,
        "status": UserStatus.ACTIVE.value,
    }).to_list(length=None)
    admins_without_mfa = [
        {"id": str(doc.get("_id")), "email": doc.get("email"), "full_name": doc.get("full_name")}
        for doc in admins if not doc.get("mfa_enabled")
    ]
    storage = await _storage_by_owner(database)
    total_storage = sum(item["storage_bytes"] for item in storage.values())
    alerts = []
    if not db_ok:
        alerts.append({"level": "critical", "message": "Database ping failed."})
    if failed_jobs:
        alerts.append({"level": "warning", "message": f"{failed_jobs} failed background job(s)."})
    if admins_without_mfa:
        alerts.append({"level": "warning", "message": f"{len(admins_without_mfa)} platform admin(s) without MFA."})
    if total_storage >= STORAGE_LIMIT_BYTES * 0.8:
        alerts.append({"level": "warning", "message": "Storage usage is above 80%."})
    if failed_logins >= 10:
        alerts.append({"level": "warning", "message": f"{failed_logins} failed logins in the last 24 hours."})
    # Refresh reuse spike alert
    if reuse >= 5:
        alerts.append({"level": "warning", "message": f"Refresh-token reuse spike: {reuse} events in 7 days (possible race conditions)."})
        await notify_admins(
            database, "refresh_reuse_spike",
            "Refresh-token reuse spike detected",
            f"{reuse} refresh-token reuse events in the last 7 days.",
            link="/admin?tab=audit",
            severity="warning",
            dedupe_key=f"reuse_spike:{now.date()}",
        )

    # Backup status
    backup_doc = await database.system_status.find_one({"_id": "backup"})
    last_backup_at = None
    if backup_doc:
        last_backup_at = backup_doc.get("last_backup_at")
        if backup_doc.get("last_backup_status") == "failed":
            alerts.append({"level": "critical", "message": f"Last backup failed: {backup_doc.get('last_backup_error')}"})
            await notify_admins(
                database, "backup_missing_or_stale",
                "Backup failed",
                f"Last backup failed: {backup_doc.get('last_backup_error')}",
                link="/admin",
                severity="critical",
                dedupe_key=f"backup_failed:{now.date()}",
            )
        elif last_backup_at:
            age_hours = (now - last_backup_at).total_seconds() / 3600
            if age_hours > 48:
                alerts.append({"level": "warning", "message": f"Last backup is stale ({age_hours:.1f} hours ago)."})
                await notify_admins(
                    database, "backup_missing_or_stale",
                    "Backup stale",
                    f"Last successful backup was {age_hours:.1f} hours ago.",
                    link="/admin",
                    severity="warning",
                    dedupe_key=f"backup_stale:{now.date()}",
                )

    # Storage at 80%
    if total_storage >= STORAGE_LIMIT_BYTES * 0.8:
        alerts.append({"level": "warning", "message": "Storage usage is above 80%."})
        await notify_admins(
            database, "storage_at_80_percent",
            "Storage usage above 80%",
            f"Platform storage is at {round(total_storage / STORAGE_LIMIT_BYTES * 100, 1)}% capacity.",
            link="/admin?tab=usage",
            severity="warning",
            dedupe_key=f"storage80:{now.date()}",
        )

    # Failed background jobs
    if failed_jobs:
        alerts.append({"level": "warning", "message": f"{failed_jobs} failed background job(s)."})
        await notify_admins(
            database, "failed_background_job",
            f"{failed_jobs} failed background job(s)",
            f"{failed_jobs} dataset processing job(s) have failed.",
            link="/admin?tab=datasets",
            severity="warning",
            dedupe_key=f"failed_jobs:{now.date()}",
        )

    # Admins without MFA
    if admins_without_mfa:
        alerts.append({"level": "warning", "message": f"{len(admins_without_mfa)} platform admin(s) without MFA."})
        await notify_admins(
            database, "admin_without_mfa",
            f"{len(admins_without_mfa)} admin(s) without MFA",
            f"{len(admins_without_mfa)} platform admin(s) have not enabled MFA.",
            link="/admin?tab=users",
            severity="warning",
            dedupe_key=f"admin_no_mfa:{now.date()}",
        )

    # Failed logins
    if failed_logins >= 10:
        alerts.append({"level": "warning", "message": f"{failed_logins} failed logins in the last 24 hours."})
        await notify_admins(
            database, "refresh_reuse_spike",
            f"{failed_logins} failed logins in 24 hours",
            f"High number of failed login attempts detected.",
            link="/admin?tab=audit",
            severity="warning",
            dedupe_key=f"failed_logins:{now.date()}",
        )

    return {
        "api": {"status": "ok"},
        "database": {"status": "ok" if db_ok else "error"},
        "pending_users": pending_users,
        "pending_organizations": pending_orgs,
        "failed_jobs": failed_jobs,
        "recent_errors_24h": recent_errors,
        "failed_logins_24h": failed_logins,
        "refresh_reuse_7d": reuse,
        "locked_accounts": locked,
        "admins_without_mfa": admins_without_mfa,
        "storage": {
            "used_bytes": total_storage,
            "limit_bytes": STORAGE_LIMIT_BYTES,
            "percent": round(total_storage / STORAGE_LIMIT_BYTES * 100, 1),
        },
        "last_backup_at": last_backup_at,
        "alerts": alerts,
    }


@router.get("/audit")
async def list_audit(
    actor: Optional[str] = None,
    event: Optional[str] = None,
    result: Optional[str] = None,
    target: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 100,
    skip: int = 0,
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(require_platform_admin),
):
    limit = max(1, min(int(limit), 500))
    skip = max(0, int(skip))
    query = {}
    if actor:
        value = actor.strip()
        query["$or"] = [
            {"actor_email": value.lower()},
            {"actor_id": value},
        ]
    if event:
        query["action"] = event.strip()
    if result:
        query["result"] = result.strip()
    if target:
        query["target"] = target.strip()
    start = _dt(date_from)
    end = _dt(date_to)
    if start or end:
        window = {}
        if start:
            window["$gte"] = start
        if end:
            window["$lte"] = end
        query["created_at"] = window
    total = await database.audit_log.count_documents(query)
    docs = await database.audit_log.find(query).sort("created_at", -1).skip(skip).limit(limit).to_list(length=limit)
    resolved = await _resolve_audit_targets(database, docs)
    items = []
    for doc in docs:
        item = dict(doc)
        item["id"] = str(item.pop("_id"))
        item.setdefault("result", "success")
        target_info = resolved.get(str(item.get("target")))
        if target_info:
            item.update(target_info)
        items.append(item)
    return {"items": items, "total": total, "limit": limit, "skip": skip}


@router.get("/users")
async def list_users(
    search: Optional[str] = None,
    status_filter: Optional[str] = None,
    platform_role: Optional[str] = None,
    account_type: Optional[str] = None,
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(require_platform_admin),
):
    docs = await database.users.find({}).sort("created_at", -1).to_list(length=5000)
    storage = await _storage_by_owner(database)
    org_names = await _org_names(database)
    needle = (search or "").strip().lower()
    items = []
    for doc in docs:
        row = _admin_user_row(doc, org_names, storage)
        if status_filter and row["status"] != status_filter:
            continue
        if platform_role and row["platform_role"] != platform_role:
            continue
        if account_type and row["account_type"] != account_type:
            continue
        if needle and not any(
            needle in str(row.get(field) or "").lower()
            for field in ("email", "full_name", "org_name", "institution")
        ):
            continue
        items.append(row)
    return {"items": items, "total": len(items)}


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    payload: AdminUserAction,
    request: Request,
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(require_platform_admin),
):
    target = await get_user_by_id(database, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if str(target.id) == str(current_user.id):
        raise HTTPException(status_code=400, detail="You cannot modify your own admin account")
    if not any((
        payload.status, payload.platform_role, payload.account_type,
        payload.org_role, payload.quota_overrides is not None,
    )):
        raise HTTPException(status_code=400, detail="No change requested")
    if payload.status and payload.status not in (UserStatus.ACTIVE, UserStatus.SUSPENDED):
        raise HTTPException(status_code=400, detail="Only active or suspended status is supported here")
    if payload.org_role and not target.org_id:
        raise HTTPException(status_code=400, detail="The user is not a member of an organization")

    updates = {"updated_at": datetime.utcnow()}
    changes = {}
    if payload.status:
        updates["status"] = payload.status.value
        updates["is_active"] = payload.status == UserStatus.ACTIVE
        changes["status"] = payload.status.value
    if payload.account_type:
        updates["account_type"] = payload.account_type.value
        changes["account_type"] = payload.account_type.value
    if payload.org_role:
        updates["org_role"] = payload.org_role.value
        changes["org_role"] = payload.org_role.value
    if payload.quota_overrides is not None:
        valid_fields = {"datasets", "rows", "storage_bytes", "exports_per_hour", "api_keys"}
        quota = {
            field: int(amount)
            for field, amount in payload.quota_overrides.items()
            if field in valid_fields and isinstance(amount, int) and amount >= 0
        }
        updates["quota_overrides"] = quota
        changes["quota_overrides"] = quota
    if payload.platform_role:
        if payload.platform_role == PlatformRole.PLATFORM_ADMIN:
            active_after = (payload.status or target.status) == UserStatus.ACTIVE
            if not target.mfa_enabled or not target.email_verified or not active_after:
                raise HTTPException(
                    status_code=400,
                    detail="The user must be verified, active, and have MFA enabled",
                )
        updates["platform_role"] = payload.platform_role.value
        updates["is_superuser"] = payload.platform_role == PlatformRole.PLATFORM_ADMIN
        changes["platform_role"] = payload.platform_role.value

    stops_admin = (
        target.platform_role == PlatformRole.PLATFORM_ADMIN
        and target.status == UserStatus.ACTIVE
        and (
            (payload.platform_role and payload.platform_role != PlatformRole.PLATFORM_ADMIN)
            or (payload.status and payload.status != UserStatus.ACTIVE)
        )
    )
    if stops_admin and await _active_platform_admins(database, exclude_id=str(target.id)) < 1:
        raise HTTPException(status_code=400, detail="The last active platform admin cannot be removed")

    await database.users.update_one({"_id": target.id}, {"$set": updates})
    await bump_token_version(database, str(target.id))
    await write_audit(
        database, "admin.user_updated", actor=current_user, target=str(target.id),
        metadata={"reason": payload.reason, "changes": changes}, request=request,
    )
    doc = await database.users.find_one({"_id": target.id})
    return _admin_user_row(doc, await _org_names(database), await _storage_by_owner(database))


@router.post("/users/{user_id}/force-logout")
async def force_logout(
    user_id: str,
    request: Request,
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(require_platform_admin),
):
    target = await get_user_by_id(database, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    await bump_token_version(database, user_id)
    await write_audit(database, "admin.force_logout", actor=current_user, target=user_id, request=request)
    return {"message": "User sessions revoked."}


@router.post("/users/{user_id}/unlock")
async def unlock_user(
    user_id: str,
    request: Request,
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(require_platform_admin),
):
    target = await get_user_by_id(database, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    await database.users.update_one(
        {"_id": target.id},
        {"$set": {"failed_login_attempts": 0, "locked_until": None, "updated_at": datetime.utcnow()}},
    )
    await write_audit(database, "admin.user_unlocked", actor=current_user, target=user_id, request=request)
    return {"message": "Account unlocked."}


@router.post("/users/{user_id}/send-password-reset")
async def send_password_reset(
    user_id: str,
    request: Request,
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(require_platform_admin),
):
    target = await get_user_by_id(database, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    raw = await create_one_time_token(
        database, str(target.id), "password_reset", datetime.utcnow() + timedelta(minutes=30),
    )
    await send_email(
        target.email,
        "Reset your EnvPlatform password",
        "A platform administrator requested a password reset. Open this single-use link "
        f"within 30 minutes:\n\n{password_reset_link(raw)}\n",
    )
    await write_audit(
        database, "admin.password_reset_sent", actor=current_user, target=user_id, request=request,
    )
    return {"message": "Password reset email queued."}


@router.get("/datasets")
async def list_admin_datasets(
    search: Optional[str] = None,
    status_filter: Optional[str] = None,
    visibility: Optional[str] = None,
    source_tag: Optional[str] = None,
    owner_id: Optional[str] = None,
    org_id: Optional[str] = None,
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(require_platform_admin),
):
    docs = await database.datasets.find({}).sort("created_at", -1).to_list(length=1000)
    users = {}
    for doc in await database.users.find({}, {"email": 1, "full_name": 1}).to_list(length=None):
        users[str(doc["_id"])] = doc
    org_names = await _org_names(database)
    needle = (search or "").strip().lower()
    items = []
    for doc in docs:
        row = _dataset_row(doc, users, org_names)
        if status_filter and row["status"] != status_filter:
            continue
        if visibility and row["visibility"] != visibility:
            continue
        if source_tag and row["source_tag"] != source_tag:
            continue
        if owner_id and row["owner_id"] != owner_id:
            continue
        if org_id and str(row["org_id"] or "") != str(org_id):
            continue
        if needle and not any(
            needle in str(row.get(field) or "").lower()
            for field in ("filename", "display_name", "owner_email", "org_name")
        ):
            continue
        items.append(row)
    return {"items": items, "total": len(items)}


@router.patch("/datasets/{dataset_id}")
async def update_dataset(
    dataset_id: str,
    payload: AdminDatasetAction,
    request: Request,
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(require_platform_admin),
):
    try:
        object_id = ObjectId(dataset_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Dataset not found")
    doc = await database.datasets.find_one({"_id": object_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Dataset not found")
    filename = doc.get("display_name") or doc.get("filename") or dataset_id
    if payload.action == "set_source":
        if not payload.source_tag:
            raise HTTPException(status_code=400, detail="source_tag is required")
        before = source_tag_for(doc)
        await database.datasets.update_one(
            {"_id": object_id},
            {"$set": {
                "source_tag": payload.source_tag,
                "source_tag_updated_at": datetime.utcnow(),
                "source_tag_updated_by": str(current_user.id),
                "updated_at": datetime.utcnow(),
            }},
        )
        await write_audit(
            database, "admin.dataset_source_updated", actor=current_user, target=dataset_id,
            metadata={
                "reason": payload.reason,
                "filename": doc.get("filename"),
                "before": {"source_tag": before},
                "after": {"source_tag": payload.source_tag},
            },
            request=request,
        )
        return {"dataset_id": dataset_id, "source_tag": payload.source_tag}

    if payload.action == "publish":
        if _dataset_owner(doc) and not (doc.get("publish_requested_at") or doc.get("publish_consented_at")):
            raise HTTPException(
                status_code=409,
                detail="The dataset owner must request publication or give consent first.",
            )
        visibility = "reference"
        updates = {
            "visibility": visibility,
            "published_at": datetime.utcnow(),
            "published_by": str(current_user.id),
            "publish_request_status": "approved",
            "updated_at": datetime.utcnow(),
        }
        event = "admin.dataset_published"
        await _notify_dataset_owner(
            database, doc,
            f"Dataset published: {filename}",
            f"A platform administrator published your dataset '{filename}'.\n\n"
            f"Reason: {payload.reason}\n",
        )
    else:
        visibility = "private"
        updates = {"visibility": visibility, "updated_at": datetime.utcnow()}
        event = "admin.dataset_unpublished"
        await _notify_dataset_owner(
            database, doc,
            f"Dataset unpublished: {filename}",
            f"A platform administrator unpublished your dataset '{filename}'.\n\n"
            f"Reason: {payload.reason}\n",
        )
    await database.datasets.update_one({"_id": object_id}, {"$set": updates})
    await write_audit(
        database, event, actor=current_user, target=dataset_id,
        metadata={
            "reason": payload.reason,
            "filename": doc.get("filename"),
            "before": {"visibility": doc.get("visibility")},
            "after": {"visibility": visibility},
        },
        request=request,
    )
    return {"dataset_id": dataset_id, "visibility": visibility}


@router.delete("/datasets/{dataset_id}")
async def delete_dataset(
    dataset_id: str,
    request: Request,
    reason: str = Query(..., min_length=3, max_length=500),
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(require_platform_admin),
):
    try:
        object_id = ObjectId(dataset_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Dataset not found")
    doc = await database.datasets.find_one({"_id": object_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Dataset not found")
    await database.datasets.delete_one({"_id": object_id})
    for collection in ("air_quality", "water_quality", "anomalies", "forecasts"):
        await getattr(database, collection).delete_many({"dataset_id": dataset_id})
    purge_forecast_models(dataset_id)
    purge_anomaly_models(dataset_id)
    await _notify_dataset_owner(
        database, doc,
        f"Dataset deleted: {doc.get('display_name') or doc.get('filename') or dataset_id}",
        f"A platform administrator deleted your dataset "
        f"'{doc.get('display_name') or doc.get('filename') or dataset_id}'.\n\n"
        f"Reason: {reason}\n",
    )
    await write_audit(
        database, "admin.dataset_deleted", actor=current_user, target=dataset_id,
        metadata={
            "reason": reason,
            "filename": doc.get("filename"),
            "owner_id": _dataset_owner(doc) or None,
            "before": {
                "visibility": doc.get("visibility"),
                "row_count": doc.get("row_count"),
                "source_tag": source_tag_for(doc),
            },
        },
        request=request,
    )
    return {"message": "Dataset and associated data deleted."}


@router.get("/usage")
async def usage(
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(require_platform_admin),
):
    storage = await _storage_by_owner(database)
    users = await database.users.find({}).to_list(length=5000)
    org_names = await _org_names(database)
    total = sum(item["storage_bytes"] for item in storage.values())
    top = []
    for doc in users:
        user_id = str(doc["_id"])
        item = storage.get(user_id)
        if not item:
            continue
        top.append({
            "id": user_id,
            "email": doc.get("email"),
            "full_name": doc.get("full_name"),
            "account_type": doc.get("account_type"),
            "org_name": org_names.get(str(doc.get("org_id"))) if doc.get("org_id") else None,
            "storage_bytes": item["storage_bytes"],
            "dataset_count": item["dataset_count"],
        })
    top.sort(key=lambda item: item["storage_bytes"], reverse=True)
    quotas = {}
    for account_type in AccountType:
        dummy = SimpleNamespace(account_type=account_type, platform_role=PlatformRole.USER)
        quotas[account_type.value] = await quota_public_for(database, dummy)
    platform_settings = await get_system_settings(database)
    return {
        "used_bytes": total,
        "limit_bytes": STORAGE_LIMIT_BYTES,
        "percent": round(total / STORAGE_LIMIT_BYTES * 100, 1),
        "alert": total >= STORAGE_LIMIT_BYTES * 0.8,
        "top_users": top[:10],
        "quotas": quotas,
        "quota_overrides": platform_settings.get("quota_overrides") or {},
    }


@router.get("/settings")
async def get_settings_admin(
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(require_platform_admin),
):
    platform_settings = await get_system_settings(database)
    quotas = {}
    for account_type in AccountType:
        dummy = SimpleNamespace(account_type=account_type, platform_role=PlatformRole.USER)
        quotas[account_type.value] = await quota_public_for(database, dummy)
    return {**platform_settings, "quotas": quotas}


@router.patch("/settings")
async def update_settings_admin(
    payload: AdminSettingsUpdate,
    request: Request,
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(require_platform_admin),
):
    updates = {}
    if payload.registration_mode is not None:
        updates["registration_mode"] = payload.registration_mode
    if payload.allowed_domains is not None:
        updates["allowed_domains"] = normalize_domains(payload.allowed_domains)
    if payload.mfa_required is not None:
        valid = {item.value for item in AccountType}
        mfa = {key: bool(value) for key, value in payload.mfa_required.items() if key in valid}
        updates["mfa_required"] = mfa
    if payload.quota_overrides is not None:
        valid_types = {item.value for item in AccountType}
        valid_fields = {"datasets", "rows", "storage_bytes", "exports_per_hour", "api_keys"}
        overrides = {}
        for key, value in payload.quota_overrides.items():
            if key not in valid_types or not isinstance(value, dict):
                continue
            clean = {
                field: int(amount)
                for field, amount in value.items()
                if field in valid_fields and isinstance(amount, int) and amount >= 0
            }
            if clean:
                overrides[key] = clean
        updates["quota_overrides"] = overrides
    if not updates:
        raise HTTPException(status_code=400, detail="No settings change requested")
    result = await save_system_settings(database, updates, actor=current_user)
    await write_audit(
        database, "admin.settings_updated", actor=current_user,
        metadata={"reason": payload.reason, "changes": updates}, request=request,
    )
    return result
