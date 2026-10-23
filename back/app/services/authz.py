from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.user import OrgRole, PlatformRole


READABLE_VISIBILITIES = {"reference", "public"}


def _user_id(user) -> Optional[str]:
    if user is None:
        return None
    value = getattr(user, "id", None)
    if value is None and isinstance(user, dict):
        value = user.get("_id") or user.get("id")
    return str(value) if value is not None else None


def _user_org_id(user) -> Optional[str]:
    if user is None:
        return None
    if isinstance(user, dict):
        return user.get("org_id")
    return getattr(user, "org_id", None)


def _org_role(user) -> Optional[str]:
    if user is None:
        return None
    if isinstance(user, dict):
        return user.get("org_role")
    return getattr(user, "org_role", None)


def is_platform_admin(user) -> bool:
    if user is None:
        return False
    role = user.get("platform_role") if isinstance(user, dict) else getattr(user, "platform_role", None)
    return role == PlatformRole.PLATFORM_ADMIN or role == PlatformRole.PLATFORM_ADMIN.value


def is_org_admin(user) -> bool:
    role = _org_role(user)
    return role == OrgRole.ORG_ADMIN or role == OrgRole.ORG_ADMIN.value


def _dataset_owner(dataset: dict) -> Optional[str]:
    value = dataset.get("owner_id") or dataset.get("user_id")
    return str(value) if value else None


def _is_legacy_public(dataset: dict) -> bool:
    return not _dataset_owner(dataset) and not dataset.get("org_id") and not dataset.get("visibility")


def dataset_readable(dataset: dict, user) -> bool:
    if not dataset:
        return False
    visibility = dataset.get("visibility") or "private"
    if _is_legacy_public(dataset):
        return True
    if visibility in READABLE_VISIBILITIES:
        return True
    if user is None:
        return False
    user_id = _user_id(user)
    owner = _dataset_owner(dataset)
    if owner and owner == user_id:
        return True
    if user_id and user_id in {str(value) for value in (dataset.get("shared_with_users") or [])}:
        return True
    if visibility == "org":
        org_id = _user_org_id(user)
        return bool(org_id and dataset.get("org_id") and str(dataset["org_id"]) == str(org_id))
    return False


def dataset_writable(dataset: dict, user) -> bool:
    if not dataset:
        return False
    if _is_legacy_public(dataset):
        return True
    if user is None:
        return False
    user_id = _user_id(user)
    owner = _dataset_owner(dataset)
    if owner and owner == user_id:
        return True
    if is_org_admin(user):
        org_id = _user_org_id(user)
        return bool(org_id and dataset.get("org_id") and str(dataset["org_id"]) == str(org_id))
    return False


def readable_query(user) -> dict:
    if user is None:
        return {
            "$or": [
                {"visibility": {"$in": list(READABLE_VISIBILITIES)}},
                {"$and": [
                    {"user_id": None},
                    {"org_id": None},
                    {"visibility": {"$exists": False}},
                ]},
                {"$and": [
                    {"owner_id": None},
                    {"org_id": None},
                    {"visibility": {"$exists": False}},
                ]},
            ]
        }
    user_id = _user_id(user)
    org_id = _user_org_id(user)
    clauses = [
        {"user_id": user_id},
        {"owner_id": user_id},
        {"shared_with_users": user_id},
        {"visibility": {"$in": list(READABLE_VISIBILITIES)}},
    ]
    if org_id:
        clauses.append({"visibility": "org", "org_id": str(org_id)})
    return {"$or": clauses}


async def get_dataset_or_none(database: AsyncIOMotorDatabase, dataset_id: str) -> Optional[dict]:
    try:
        object_id = ObjectId(dataset_id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid dataset ID")
    return await database.datasets.find_one({"_id": object_id})


async def require_dataset_access(
    database: AsyncIOMotorDatabase,
    dataset_id: str,
    user,
    *,
    write: bool = False,
) -> dict:
    dataset = await get_dataset_or_none(database, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    allowed = dataset_writable(dataset, user) if write else dataset_readable(dataset, user)
    if not allowed:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return dataset
