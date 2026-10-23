from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.organization import OrganizationStatus, OrganizationType
from app.models.user import AccountType, OrgRole


ACCOUNT_TYPE_BY_ORG = {
    OrganizationType.UNIVERSITY: AccountType.RESEARCHER,
    OrganizationType.GOVT: AccountType.GOVT_AGENCY,
    OrganizationType.NGO: AccountType.RESEARCHER,
    OrganizationType.INTL_ORG: AccountType.GLOBAL_ORG,
}


def normalize_domains(domains) -> list:
    cleaned = []
    for value in domains or []:
        domain = str(value).strip().lower().lstrip("@")
        if not domain or "." not in domain or "/" in domain or " " in domain:
            raise HTTPException(status_code=400, detail=f"Invalid organization domain: {value}")
        if domain not in cleaned:
            cleaned.append(domain)
    return cleaned


async def get_org(database: AsyncIOMotorDatabase, org_id: str) -> Optional[dict]:
    try:
        return await database.organizations.find_one({"_id": ObjectId(str(org_id))})
    except (InvalidId, TypeError):
        return None


async def require_verified_org(database: AsyncIOMotorDatabase, org_id: str) -> dict:
    org = await get_org(database, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    if org.get("status") != OrganizationStatus.VERIFIED.value:
        raise HTTPException(status_code=403, detail="Organization is not verified")
    return org


async def count_org_admins(database: AsyncIOMotorDatabase, org_id: str) -> int:
    return await database.users.count_documents({
        "org_id": str(org_id),
        "org_role": OrgRole.ORG_ADMIN.value,
        "status": "active",
    })


async def ensure_not_last_admin(database: AsyncIOMotorDatabase, org_id: str, user_id: str) -> None:
    target = await database.users.find_one({"_id": ObjectId(str(user_id))})
    if target and target.get("org_role") == OrgRole.ORG_ADMIN.value:
        if await count_org_admins(database, org_id) <= 1:
            raise HTTPException(status_code=400, detail="An organization must keep at least one org admin")
