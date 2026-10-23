"""Create or reset the first platform administrator.

Usage:
    FIRST_ADMIN_EMAIL=... FIRST_ADMIN_PASSWORD=... python -m app.scripts.bootstrap_admin

The account is forced to change its password and enrol TOTP on first login.
There is intentionally no public endpoint that can create a platform admin.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime

from app.config import get_settings
from app.database import close_mongo_connection, connect_to_mongo, db
from app.models.user import AccountType, PlatformRole, UserCreate, UserStatus
from app.services.auth import (
    bump_token_version,
    create_user,
    get_password_hash,
    get_user_by_email,
    normalize_email,
    write_audit,
)
from app.services.passwords import validate_password


async def bootstrap_admin(database, email: str, password: str):
    email = normalize_email(email)
    validate_password(password)
    now = datetime.utcnow()
    user = await get_user_by_email(database, email)
    if user:
        await database.users.update_one(
            {"_id": user.id},
            {"$set": {
                "hashed_password": get_password_hash(password),
                "account_type": AccountType.RESEARCHER.value,
                "platform_role": PlatformRole.PLATFORM_ADMIN.value,
                "email_verified": True,
                "status": UserStatus.ACTIVE.value,
                "must_change_password": True,
                "mfa_enabled": False,
                "mfa_secret": None,
                "pending_mfa_secret": None,
                "terms_version": get_settings().TERMS_VERSION,
                "terms_accepted_at": now,
                "updated_at": now,
            }},
        )
        await bump_token_version(database, str(user.id))
    else:
        user = await create_user(
            database,
            UserCreate(
                email=email,
                password=password,
                full_name="Platform Administrator",
                account_type=AccountType.RESEARCHER,
                platform_role=PlatformRole.PLATFORM_ADMIN,
                email_verified=True,
                status=UserStatus.ACTIVE,
                must_change_password=True,
                terms_version=get_settings().TERMS_VERSION,
                terms_accepted_at=now,
            ),
            email_verified=True,
            status=UserStatus.ACTIVE,
        )
    await write_audit(
        database, "auth.bootstrap_admin", target=str(user.id),
        metadata={"email": email},
    )
    return await get_user_by_email(database, email)


async def _main() -> int:
    settings = get_settings()
    email = (settings.FIRST_ADMIN_EMAIL or "").strip()
    password = settings.FIRST_ADMIN_PASSWORD or ""
    if not email or not password:
        print("Set FIRST_ADMIN_EMAIL and FIRST_ADMIN_PASSWORD first.", file=sys.stderr)
        return 2
    await connect_to_mongo()
    try:
        user = await bootstrap_admin(db.db, email, password)
        print(f"Platform administrator ready: {user.email}")
        print("They must change the password and enrol TOTP on first login.")
        return 0
    finally:
        await close_mongo_connection()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
