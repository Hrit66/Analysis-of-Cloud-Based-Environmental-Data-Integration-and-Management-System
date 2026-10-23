import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, Tuple

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from bson import ObjectId
from bson.errors import InvalidId
from jose import JWTError, jwt
from motor.motor_asyncio import AsyncIOMotorDatabase
from passlib.context import CryptContext

from app.config import get_settings
from app.models.user import (
    AccountType,
    OrgRole,
    PlatformRole,
    UserCreate,
    UserInDB,
    UserStatus,
)


password_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)
legacy_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

REFRESH_COOKIE = "env_refresh"
MFA_ISSUER = "EnvPlatform"


class AuthFailure(Exception):
    def __init__(self, message: str, status_code: int = 401, *, clear_cookie: bool = True):
        self.message = message
        self.status_code = status_code
        self.clear_cookie = clear_cookie
        super().__init__(message)


def utcnow() -> datetime:
    return datetime.utcnow()


def normalize_email(email: str) -> str:
    return str(email).strip().lower()


def get_password_hash(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not hashed_password:
        return False
    if hashed_password.startswith("$argon2"):
        try:
            return password_hasher.verify(hashed_password, plain_password)
        except (VerifyMismatchError, InvalidHashError):
            return False
    try:
        return legacy_context.verify(plain_password, hashed_password)
    except Exception:
        return False


def password_needs_rehash(hashed_password: str) -> bool:
    if not hashed_password or not hashed_password.startswith("$argon2"):
        return True
    try:
        return password_hasher.check_needs_rehash(hashed_password)
    except Exception:
        return True


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    settings = get_settings()
    to_encode = data.copy()
    now = utcnow()
    expire = now + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "iat": now, "type": "access", "jti": secrets.token_hex(16)})
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_mfa_token(user: UserInDB, purpose: str) -> str:
    settings = get_settings()
    now = utcnow()
    payload = {
        "sub": str(user.id),
        "type": "mfa",
        "purpose": purpose,
        "tv": user.token_version,
        "exp": now + timedelta(minutes=settings.MFA_CHALLENGE_EXPIRE_MINUTES),
        "iat": now,
        "jti": secrets.token_hex(16),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        raise AuthFailure("Could not validate credentials") from exc


def _normalize_user_doc(doc: dict) -> dict:
    doc = dict(doc)
    if "_id" in doc:
        doc["id"] = str(doc.pop("_id"))
    doc.setdefault("account_type", AccountType.RESEARCHER.value)
    doc.setdefault("platform_role", PlatformRole.USER.value)
    doc.setdefault("status", UserStatus.ACTIVE.value)
    doc.setdefault("email_verified", True)
    doc.setdefault("mfa_enabled", False)
    doc.setdefault("token_version", 0)
    doc.setdefault("orcid_verified", False)
    doc.setdefault("onboarding_completed", False)
    doc.setdefault("must_change_password", False)
    doc.setdefault("review_required", False)
    doc.setdefault("signup_source", "legacy")
    if doc.get("is_superuser"):
        doc["platform_role"] = PlatformRole.PLATFORM_ADMIN.value
    if doc.get("account_type") == AccountType.GOVT_AGENCY.value and not doc.get("org_id"):
        doc["account_type"] = AccountType.RESEARCHER.value
    if doc.get("account_type") == AccountType.GLOBAL_ORG.value and not doc.get("org_id"):
        doc["account_type"] = AccountType.RESEARCHER.value
    return doc


async def get_user_by_email(db: AsyncIOMotorDatabase, email: str) -> Optional[UserInDB]:
    doc = await db.users.find_one({"email": normalize_email(email)})
    if not doc:
        return None
    return UserInDB(**_normalize_user_doc(doc))


async def get_user_by_id(db: AsyncIOMotorDatabase, user_id: str) -> Optional[UserInDB]:
    try:
        object_id = ObjectId(str(user_id))
    except (InvalidId, TypeError):
        return None
    doc = await db.users.find_one({"_id": object_id})
    if not doc:
        return None
    return UserInDB(**_normalize_user_doc(doc))


async def create_user(
    db: AsyncIOMotorDatabase,
    user_create: UserCreate,
    *,
    email_verified: Optional[bool] = None,
    status: Optional[UserStatus] = None,
) -> UserInDB:
    now = utcnow()
    payload = user_create.model_dump()
    payload.pop("password", None)
    payload["email"] = normalize_email(user_create.email)
    payload["hashed_password"] = get_password_hash(user_create.password)
    payload["email_verified"] = (
        user_create.email_verified if email_verified is None else email_verified
    )
    payload["status"] = status or user_create.status
    payload["created_at"] = now
    payload["updated_at"] = now
    payload["failed_login_attempts"] = 0
    payload["locked_until"] = None
    result = await db.users.insert_one(payload)
    payload["_id"] = result.inserted_id
    return UserInDB(**_normalize_user_doc(payload))


async def _org_mfa_required(db: AsyncIOMotorDatabase, user: UserInDB) -> bool:
    if not user.org_id:
        return False
    try:
        org = await db.organizations.find_one({"_id": ObjectId(user.org_id)})
    except (InvalidId, TypeError):
        return True
    if not org:
        return True
    return bool((org.get("settings") or {}).get("require_mfa", True))


async def mfa_is_required(db: AsyncIOMotorDatabase, user: UserInDB) -> bool:
    if user.platform_role == PlatformRole.PLATFORM_ADMIN:
        return True
    from app.services.system_settings import get_system_settings, mfa_required_for

    platform_settings = await get_system_settings(db)
    if mfa_required_for(platform_settings, user):
        return True
    return await _org_mfa_required(db, user)


async def authenticate_user_with_reason(
    db: AsyncIOMotorDatabase, email: str, password: str
) -> Tuple[Optional[UserInDB], str]:
    user = await get_user_by_email(db, email)
    if not user:
        return None, "invalid"
    now = utcnow()
    if user.locked_until and user.locked_until > now:
        return None, "locked"
    if not verify_password(password, user.hashed_password):
        settings = get_settings()
        attempts = (user.failed_login_attempts or 0) + 1
        update = {"failed_login_attempts": attempts, "updated_at": now}
        if attempts >= settings.LOCKOUT_THRESHOLD:
            update["locked_until"] = now + timedelta(minutes=settings.LOCKOUT_MINUTES)
            update["failed_login_attempts"] = 0
        await db.users.update_one({"_id": ObjectId(str(user.id))}, {"$set": update})
        await write_audit(
            db, "auth.login_failed", actor=user, target=str(user.id),
            metadata={"reason": "bad_password", "locked": bool(update.get("locked_until"))},
            result="failure",
        )
        return None, "locked" if update.get("locked_until") else "invalid"
    if not user.is_active or user.status in (UserStatus.SUSPENDED, UserStatus.REJECTED):
        return None, "inactive"
    if not user.email_verified or user.status == UserStatus.PENDING_VERIFICATION:
        return None, "unverified"
    if user.status == UserStatus.PENDING_APPROVAL:
        return None, "pending_approval"
    if user.status != UserStatus.ACTIVE:
        return None, "inactive"
    if user.org_id:
        try:
            org = await db.organizations.find_one({"_id": ObjectId(user.org_id)})
        except (InvalidId, TypeError):
            org = None
        if not org or org.get("status") != "verified":
            return None, "org_inactive"
    update = {
        "failed_login_attempts": 0,
        "locked_until": None,
        "last_login_at": now,
        "updated_at": now,
    }
    if password_needs_rehash(user.hashed_password):
        update["hashed_password"] = get_password_hash(password)
    await db.users.update_one({"_id": ObjectId(str(user.id))}, {"$set": update})
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    return user, "ok"


async def authenticate_user(
    db: AsyncIOMotorDatabase, email: str, password: str
) -> Optional[UserInDB]:
    user, _ = await authenticate_user_with_reason(db, email, password)
    return user


async def get_current_user(token: str, db: AsyncIOMotorDatabase) -> Optional[UserInDB]:
    try:
        payload = decode_token(token)
    except AuthFailure:
        return None
    if payload.get("type") != "access":
        return None
    subject = payload.get("sub")
    if not subject:
        return None
    user = await get_user_by_id(db, subject)
    if not user:
        user = await get_user_by_email(db, subject)
    if not user:
        return None
    if int(payload.get("tv", 0)) != int(user.token_version or 0):
        return None
    if not user.is_active or user.status != UserStatus.ACTIVE:
        return None
    if not user.email_verified:
        return None
    if user.org_id:
        try:
            org = await db.organizations.find_one({"_id": ObjectId(user.org_id)})
        except (InvalidId, TypeError):
            return None
        if not org or org.get("status") != "verified":
            return None
    if (
        not user.mfa_enabled
        and not user.must_change_password
        and await mfa_is_required(db, user)
    ):
        return None
    return user


ANALYSIS_NAVIGATION = [
    "home",
    "upload",
    "datasets",
    "aqi",
    "wqi",
    "temperature",
    "rainfall",
    "anomalies",
    "reports",
]


def allowed_navigation(user: UserInDB) -> list[str]:
    if user.platform_role == PlatformRole.PLATFORM_ADMIN:
        return ["home", "admin"]
    navigation = list(ANALYSIS_NAVIGATION)
    if user.org_id and user.org_role == OrgRole.ORG_ADMIN:
        navigation.append("organization")
    return navigation


def user_public(user: UserInDB) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "is_active": user.is_active,
        "is_superuser": user.is_superuser,
        "account_type": user.account_type,
        "org_id": user.org_id,
        "org_role": user.org_role,
        "platform_role": user.platform_role,
        "orcid": user.orcid,
        "orcid_verified": user.orcid_verified,
        "institution": user.institution,
        "onboarding_completed": user.onboarding_completed,
        "onboarding_required": bool(
            not user.onboarding_completed
            and user.platform_role != PlatformRole.PLATFORM_ADMIN
        ),
        "must_change_password": user.must_change_password,
        "review_required": user.review_required,
        "review_reason": user.review_reason,
        "email_verified": user.email_verified,
        "status": user.status,
        "mfa_enabled": user.mfa_enabled,
        "navigation": allowed_navigation(user),
        "created_at": user.created_at,
    }


async def issue_access_token(db: AsyncIOMotorDatabase, user: UserInDB) -> tuple:
    settings = get_settings()
    access = create_access_token(
        {"sub": str(user.id), "email": user.email, "tv": user.token_version},
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    raw_refresh = secrets.token_urlsafe(48)
    now = utcnow()
    await db.refresh_tokens.insert_one({
        "token_hash": hash_token(raw_refresh),
        "user_id": str(user.id),
        "token_version": user.token_version,
        "family_id": secrets.token_hex(16),
        "created_at": now,
        "expires_at": now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        "revoked_at": None,
        "replaced_by": None,
    })
    return access, raw_refresh, settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60


async def issue_tokens(
    db: AsyncIOMotorDatabase, user: UserInDB, response, request=None
) -> dict:
    access, raw_refresh, expires_in = await issue_access_token(db, user)
    set_refresh_cookie(response, raw_refresh)
    await write_audit(
        db, "auth.login", actor=user, target=str(user.id),
        metadata={"ip": getattr(request, "client", None) and request.client.host},
    )
    return {
        "access_token": access,
        "token_type": "bearer",
        "expires_in": expires_in,
    }


def set_refresh_cookie(response, raw_refresh: str):
    settings = get_settings()
    secure = settings.COOKIE_SECURE
    if secure is None:
        secure = settings.ENVIRONMENT != "development"
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=raw_refresh,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        httponly=True,
        secure=secure,
        samesite=settings.COOKIE_SAMESITE,
        domain=settings.COOKIE_DOMAIN,
        path="/api/auth",
    )


def clear_refresh_cookie(response):
    settings = get_settings()
    response.delete_cookie(
        REFRESH_COOKIE,
        path="/api/auth",
        domain=settings.COOKIE_DOMAIN,
    )


async def rotate_refresh_token(
    db: AsyncIOMotorDatabase, raw_token: str
) -> Tuple[UserInDB, str, int, str]:
    if not raw_token:
        raise AuthFailure("Refresh token missing")
    token_hash = hash_token(raw_token)
    now = utcnow()
    doc = await db.refresh_tokens.find_one({"token_hash": token_hash})
    if not doc:
        raise AuthFailure("Invalid refresh token")
    if doc.get("revoked_at"):
        rotated_at = doc.get("rotated_at") or doc.get("revoked_at")
        grace = get_settings().REFRESH_REUSE_GRACE_SECONDS
        age = (now - rotated_at).total_seconds() if rotated_at else None
        if doc.get("replaced_by") and age is not None and 0 <= age <= grace:
            await write_audit(
                db, "auth.refresh_race", target=str(doc.get("user_id") or ""),
                metadata={
                    "family_id": doc.get("family_id"),
                    "age_seconds": round(age, 3),
                    "grace_seconds": grace,
                },
                result="failure",
            )
            raise AuthFailure("Refresh token already used", clear_cookie=False)
        await db.refresh_tokens.update_many(
            {"family_id": doc.get("family_id"), "revoked_at": None},
            {"$set": {"revoked_at": now, "revoked_reason": "reuse"}},
        )
        await write_audit(
            db, "auth.refresh_reuse", target=str(doc.get("user_id") or ""),
            metadata={"family_id": doc.get("family_id")}, result="failure",
        )
        raise AuthFailure("Refresh token reuse detected")
    if doc.get("expires_at") and doc["expires_at"] <= now:
        raise AuthFailure("Refresh token expired")
    user = await get_user_by_id(db, doc.get("user_id"))
    if not user or not user.is_active or user.status != UserStatus.ACTIVE or not user.email_verified:
        raise AuthFailure("Account is not active")
    if int(doc.get("token_version", 0)) != int(user.token_version or 0):
        raise AuthFailure("Refresh token revoked")
    if user.org_id:
        try:
            org = await db.organizations.find_one({"_id": ObjectId(user.org_id)})
        except (InvalidId, TypeError):
            org = None
        if not org or org.get("status") != "verified":
            raise AuthFailure("Organization is not active")
    if not user.mfa_enabled and await mfa_is_required(db, user):
        raise AuthFailure("MFA setup required")
    raw_new = secrets.token_urlsafe(48)
    settings = get_settings()
    result = await db.refresh_tokens.update_one(
        {"_id": doc["_id"], "revoked_at": None},
        {"$set": {
            "revoked_at": now,
            "revoked_reason": "rotated",
            "replaced_by": hash_token(raw_new),
            "rotated_at": now,
        }},
    )
    if result.modified_count != 1:
        raise AuthFailure("Refresh token already used")
    await db.refresh_tokens.insert_one({
        "token_hash": hash_token(raw_new),
        "user_id": str(user.id),
        "token_version": user.token_version,
        "family_id": doc.get("family_id"),
        "created_at": now,
        "expires_at": now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        "revoked_at": None,
        "replaced_by": None,
    })
    access = create_access_token(
        {"sub": str(user.id), "email": user.email, "tv": user.token_version},
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return user, raw_new, settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60, access


async def revoke_refresh_token(db: AsyncIOMotorDatabase, raw_token: str):
    if not raw_token:
        return
    await db.refresh_tokens.update_one(
        {"token_hash": hash_token(raw_token), "revoked_at": None},
        {"$set": {"revoked_at": utcnow(), "revoked_reason": "logout"}},
    )


async def revoke_all_refresh_tokens(db: AsyncIOMotorDatabase, user_id: str):
    await db.refresh_tokens.update_many(
        {"user_id": str(user_id), "revoked_at": None},
        {"$set": {"revoked_at": utcnow(), "revoked_reason": "revoked"}},
    )


async def bump_token_version(db: AsyncIOMotorDatabase, user_id: str) -> int:
    result = await db.users.find_one_and_update(
        {"_id": ObjectId(str(user_id))},
        {"$inc": {"token_version": 1}, "$set": {"updated_at": utcnow()}},
        return_document=True,
    )
    version = int((result or {}).get("token_version", 0))
    await revoke_all_refresh_tokens(db, str(user_id))
    return version


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=MFA_ISSUER)


def verify_totp(secret: str, code: str) -> bool:
    if not secret or not code:
        return False
    try:
        return pyotp.TOTP(secret).verify(str(code).strip(), valid_window=1)
    except Exception:
        return False


async def get_mfa_user(db: AsyncIOMotorDatabase, token: str) -> UserInDB:
    try:
        payload = decode_token(token)
    except AuthFailure:
        raise AuthFailure("Invalid or expired MFA challenge")
    if payload.get("type") != "mfa":
        raise AuthFailure("Invalid MFA challenge")
    user = await get_user_by_id(db, payload.get("sub"))
    if not user:
        raise AuthFailure("Account not found")
    if int(payload.get("tv", 0)) != int(user.token_version or 0):
        raise AuthFailure("MFA challenge expired")
    if not user.is_active or user.status != UserStatus.ACTIVE or not user.email_verified:
        raise AuthFailure("Account is not active")
    return user


async def create_one_time_token_record(
    db: AsyncIOMotorDatabase,
    user_id: str,
    kind: str,
    expires_at: datetime,
    metadata: Optional[dict] = None,
) -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    result = await db.one_time_tokens.insert_one({
        "token_hash": hash_token(raw),
        "user_id": str(user_id),
        "kind": kind,
        "metadata": metadata or {},
        "created_at": utcnow(),
        "expires_at": expires_at,
        "used_at": None,
    })
    return raw, str(result.inserted_id)


async def create_one_time_token(
    db: AsyncIOMotorDatabase,
    user_id: str,
    kind: str,
    expires_at: datetime,
    metadata: Optional[dict] = None,
) -> str:
    raw, _ = await create_one_time_token_record(
        db, user_id, kind, expires_at, metadata
    )
    return raw


async def consume_one_time_token(
    db: AsyncIOMotorDatabase, raw: str, kind: str
) -> Optional[dict]:
    if not raw:
        return None
    now = utcnow()
    doc = await db.one_time_tokens.find_one_and_update(
        {
            "token_hash": hash_token(raw),
            "kind": kind,
            "used_at": None,
            "expires_at": {"$gt": now},
        },
        {"$set": {"used_at": now}},
    )
    return doc


async def write_audit(
    db: AsyncIOMotorDatabase,
    action: str,
    *,
    actor=None,
    org_id: Optional[str] = None,
    target: Optional[str] = None,
    metadata: Optional[dict] = None,
    request=None,
    result: str = "success",
) -> None:
    actor_id = None
    actor_email = None
    if actor is not None:
        actor_id = str(getattr(actor, "id", None) or (actor.get("_id") if isinstance(actor, dict) else None) or "")
        actor_email = getattr(actor, "email", None) if not isinstance(actor, dict) else actor.get("email")
        if not org_id:
            org_id = getattr(actor, "org_id", None) if not isinstance(actor, dict) else actor.get("org_id")
    ip = None
    user_agent = None
    if request is not None:
        headers = getattr(request, "headers", None)
        forwarded = headers.get("x-forwarded-for") if headers is not None else None
        if forwarded:
            ip = forwarded.split(",")[0].strip() or None
        elif getattr(request, "client", None):
            ip = request.client.host
        if headers is not None:
            user_agent = (headers.get("user-agent") or "")[:512] or None
    try:
        await db.audit_log.insert_one({
            "action": action,
            "actor_id": actor_id or None,
            "actor_email": actor_email,
            "org_id": org_id,
            "target": target,
            "metadata": metadata or {},
            "ip": ip,
            "user_agent": user_agent,
            "result": result,
            "created_at": utcnow(),
        })
    except Exception:
        pass
