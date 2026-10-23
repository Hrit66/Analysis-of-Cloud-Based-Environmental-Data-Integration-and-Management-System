"""Runtime platform settings stored in MongoDB."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.config import get_settings
from app.models.user import AccountType, PlatformRole

SETTINGS_ID = "global"

DEFAULT_MFA_REQUIRED = {
    AccountType.STUDENT.value: False,
    AccountType.RESEARCHER.value: False,
    AccountType.GOVT_AGENCY.value: True,
    AccountType.GLOBAL_ORG.value: True,
}

DEFAULT_REGISTRATION_MODE = "open"
REGISTRATION_MODES = {"open", "invite_only", "domain_allowlist"}


def _env_domains() -> list[str]:
    raw = get_settings().ACADEMIC_DOMAIN_ALLOWLIST
    return [item.strip().lower().lstrip("@") for item in raw.split(",") if item.strip()]


async def get_system_settings(db) -> dict:
    collection = getattr(db, "system_settings", None)
    doc = None
    if collection is not None:
        doc = await collection.find_one({"_id": SETTINGS_ID})
    doc = doc or {}

    allowed = doc.get("allowed_domains")
    if not isinstance(allowed, list):
        allowed = _env_domains()

    mfa = dict(DEFAULT_MFA_REQUIRED)
    stored_mfa = doc.get("mfa_required")
    if isinstance(stored_mfa, dict):
        for key, value in stored_mfa.items():
            if key in mfa and isinstance(value, bool):
                mfa[key] = value

    mode = doc.get("registration_mode")
    if mode not in REGISTRATION_MODES:
        mode = DEFAULT_REGISTRATION_MODE

    overrides = doc.get("quota_overrides")
    if not isinstance(overrides, dict):
        overrides = {}

    return {
        "registration_mode": mode,
        "allowed_domains": allowed,
        "mfa_required": mfa,
        "quota_overrides": overrides,
        "updated_by": doc.get("updated_by"),
        "updated_by_email": doc.get("updated_by_email"),
        "updated_at": doc.get("updated_at"),
    }


async def save_system_settings(db, updates: dict, actor=None) -> dict:
    collection = getattr(db, "system_settings", None)
    if collection is None:
        raise RuntimeError("Settings storage is unavailable")
    payload = dict(updates)
    payload["updated_at"] = datetime.utcnow()
    if actor is not None:
        payload["updated_by"] = str(getattr(actor, "id", "") or "")
        payload["updated_by_email"] = getattr(actor, "email", None)
    await collection.update_one({"_id": SETTINGS_ID}, {"$set": payload}, upsert=True)
    return await get_system_settings(db)


def mfa_required_for(settings: dict, user) -> bool:
    if getattr(user, "platform_role", None) == PlatformRole.PLATFORM_ADMIN:
        return True
    account_type = getattr(user, "account_type", AccountType.STUDENT)
    value = account_type.value if hasattr(account_type, "value") else str(account_type)
    return bool(settings.get("mfa_required", {}).get(value, False))
