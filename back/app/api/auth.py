from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import get_settings
from app.database import db
from app.models.auth import (
    AdminUserDecision,
    AdminUserUpdate,
    ForgotPasswordRequest,
    MfaDisableRequest,
    MfaCodeRequest,
    MfaEnableRequest,
    MfaSetupRequest,
    MfaSetupResponse,
    MfaVerifyRequest,
    MessageResponse,
    OnboardingResponse,
    PasswordChangeRequest,
    RefreshResponse,
    RegisterRequest,
    RegisterResponse,
    ResetPasswordRequest,
    ResendVerificationRequest,
    SignupInstitution,
    SignupOptionsResponse,
    VerifyEmailRequest,
    VerifyEmailResponse,
)
from app.models.user import (
    AccountType,
    PlatformRole,
    Token,
    UserCreate,
    UserInDB,
    UserStatus,
)
from app.services.auth import (
    AuthFailure,
    REFRESH_COOKIE,
    _normalize_user_doc,
    authenticate_user_with_reason,
    bump_token_version,
    clear_refresh_cookie,
    consume_one_time_token,
    create_mfa_token,
    create_one_time_token,
    create_user,
    generate_totp_secret,
    get_current_user,
    get_mfa_user,
    get_password_hash,
    get_user_by_email,
    get_user_by_id,
    issue_tokens,
    mfa_is_required,
    normalize_email,
    revoke_refresh_token,
    rotate_refresh_token,
    set_refresh_cookie,
    totp_uri,
    user_public,
    verify_password,
    verify_totp,
    write_audit,
)
from app.services.domains import (
    email_domain,
    institutions,
    is_allowlisted,
)
from app.services.email import (
    password_reset_link,
    send_email,
    send_verification_email,
)
from app.services.passwords import validate_password
from app.services.quotas import quota_public_for, upload_limit_for, usage_for_user
from app.services.rate_limit import enforce as enforce_rate_limit
from app.services.system_settings import get_system_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

GENERIC_REGISTRATION_MESSAGE = (
    "If the details are valid, check your email for the next step."
)


def get_database() -> AsyncIOMotorDatabase:
    return db.db


async def get_current_user_dep(
    token: str = Depends(oauth2_scheme),
    database: AsyncIOMotorDatabase = Depends(get_database),
):
    user = await get_current_user(token, database)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user.must_change_password:
        raise HTTPException(status_code=403, detail="Change your password before continuing")
    return user


async def get_optional_user(
    token: Optional[str] = Depends(oauth2_scheme_optional),
    database: AsyncIOMotorDatabase = Depends(get_database),
):
    if not token:
        return None
    user = await get_current_user(token, database)
    if user and user.must_change_password:
        return None
    return user


async def get_current_active_user(current_user=Depends(get_current_user_dep)):
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    if current_user.must_change_password:
        raise HTTPException(status_code=403, detail="Change your password before continuing")
    return current_user


async def get_password_change_user(
    token: str = Depends(oauth2_scheme),
    database: AsyncIOMotorDatabase = Depends(get_database),
):
    user = await get_current_user(token, database)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def require_platform_admin(current_user=Depends(get_current_active_user)):
    if current_user.platform_role != PlatformRole.PLATFORM_ADMIN:
        raise HTTPException(status_code=404, detail="Not found")
    if not current_user.mfa_enabled or current_user.must_change_password:
        raise HTTPException(
            status_code=403,
            detail="Platform administrators must change their password and enrol MFA first",
        )
    return current_user


def _verification_token(raw: Optional[str]) -> Optional[str]:
    return raw if get_settings().ENVIRONMENT == "development" else None


def _client_ip(request: Optional[Request]) -> str:
    if request is not None and getattr(request, "client", None):
        return request.client.host
    return "unknown"


def _token_flags(user: UserInDB) -> dict:
    return {
        "must_change_password": bool(user.must_change_password),
        "onboarding_required": bool(
            not user.onboarding_completed
            and user.platform_role != PlatformRole.PLATFORM_ADMIN
        ),
    }


async def _issue_verification(database, user: UserInDB, request: Optional[Request] = None) -> str:
    raw = await create_one_time_token(
        database,
        str(user.id),
        "email_verify",
        datetime.utcnow()
        + timedelta(minutes=get_settings().EMAIL_VERIFICATION_EXPIRE_MINUTES),
    )
    await send_verification_email(user.email, raw)
    await write_audit(
        database,
        "auth.verification_sent",
        actor=user,
        target=str(user.id),
        request=request,
    )
    return raw


@router.get("/signup-options", response_model=SignupOptionsResponse)
async def signup_options(database: AsyncIOMotorDatabase = Depends(get_database)):
    platform_settings = await get_system_settings(database)
    return SignupOptionsResponse(
        allowed_domains=platform_settings["allowed_domains"],
        institutions=[SignupInstitution(**item) for item in institutions()],
        terms_version=get_settings().TERMS_VERSION,
    )


@router.post("/register", response_model=RegisterResponse, status_code=201)
async def register(
    payload: RegisterRequest,
    request: Request,
    database: AsyncIOMotorDatabase = Depends(get_database),
):
    settings = get_settings()
    email = normalize_email(payload.email)
    ip = _client_ip(request)
    enforce_rate_limit(
        f"register:ip:{ip}", settings.REGISTER_RATE_LIMIT,
        settings.REGISTER_RATE_WINDOW_SECONDS,
    )
    enforce_rate_limit(
        f"register:email:{email}", settings.REGISTER_RATE_LIMIT,
        settings.REGISTER_RATE_WINDOW_SECONDS,
    )
    validate_password(payload.password)
    if not payload.terms_accepted:
        raise HTTPException(status_code=400, detail="Accept the terms to create an account.")
    platform_settings = await get_system_settings(database)
    if platform_settings["registration_mode"] == "invite_only":
        raise HTTPException(status_code=403, detail="Public registration is invite-only.")
    allowlisted = is_allowlisted(email, platform_settings["allowed_domains"])
    if platform_settings["registration_mode"] == "domain_allowlist" and not allowlisted:
        raise HTTPException(
            status_code=403,
            detail="Registration is restricted to approved academic domains.",
        )
    if payload.orcid:
        compact = payload.orcid.strip()
        parts = compact.split("-")
        if len(parts) != 4 or [len(part) for part in parts] != [4, 4, 4, 4]:
            raise HTTPException(status_code=400, detail="ORCID iD must look like 0000-0000-0000-0000.")

    existing = await get_user_by_email(database, email)
    if existing:
        raw = None
        if not existing.email_verified and existing.status in (
            UserStatus.PENDING_VERIFICATION, UserStatus.PENDING,
        ):
            raw = await _issue_verification(database, existing, request)
        return RegisterResponse(
            message=GENERIC_REGISTRATION_MESSAGE,
            verification_required=True,
            verification_token=_verification_token(raw),
        )

    review_required = not allowlisted
    account_type = (
        AccountType.RESEARCHER
        if payload.signup_type == "researcher"
        else AccountType.STUDENT
    )
    now = datetime.utcnow()
    user_create = UserCreate(
        email=email,
        password=payload.password,
        full_name=payload.full_name,
        account_type=account_type,
        platform_role=PlatformRole.USER,
        orcid=payload.orcid,
        orcid_verified=False,
        institution=payload.institution,
        institution_domain=email_domain(email),
        terms_version=settings.TERMS_VERSION,
        terms_accepted_at=now,
        review_required=review_required,
        review_reason="non_allowlisted_domain" if review_required else None,
        signup_source="public",
        email_verified=False,
        status=UserStatus.PENDING_VERIFICATION,
    )
    user = await create_user(
        database,
        user_create,
        email_verified=False,
        status=UserStatus.PENDING_VERIFICATION,
    )
    raw = await _issue_verification(database, user, request)
    await write_audit(
        database,
        "auth.register",
        actor=user,
        target=str(user.id),
        metadata={
            "signup_type": payload.signup_type,
            "allowlisted_domain": allowlisted,
            "review_required": review_required,
        },
        request=request,
    )
    return RegisterResponse(
        message=GENERIC_REGISTRATION_MESSAGE,
        verification_required=True,
        verification_token=_verification_token(raw),
        status=UserStatus.PENDING_VERIFICATION.value,
    )


@router.post("/verify-email", response_model=VerifyEmailResponse)
async def verify_email(
    payload: VerifyEmailRequest,
    database: AsyncIOMotorDatabase = Depends(get_database),
):
    token = await consume_one_time_token(database, payload.token, "email_verify")
    if not token:
        raise HTTPException(status_code=400, detail="Invalid or expired verification token")
    user = await get_user_by_id(database, token.get("user_id"))
    if not user:
        raise HTTPException(status_code=400, detail="Account not found")
    if user.status == UserStatus.REJECTED:
        raise HTTPException(status_code=403, detail="This account application was rejected.")
    next_status = (
        UserStatus.PENDING_APPROVAL
        if user.review_required
        else UserStatus.ACTIVE
    )
    await database.users.update_one(
        {"_id": user.id},
        {"$set": {
            "email_verified": True,
            "status": next_status.value,
            "updated_at": datetime.utcnow(),
        }},
    )
    user.email_verified = True
    user.status = next_status
    await write_audit(
        database,
        "auth.email_verified",
        actor=user,
        target=str(user.id),
        metadata={"status": next_status.value},
    )
    can_login = next_status == UserStatus.ACTIVE
    return VerifyEmailResponse(
        message=(
            "Email verified. You can sign in now."
            if can_login
            else "Email verified. Your account is awaiting administrator review."
        ),
        status=next_status.value,
        can_login=can_login,
    )


@router.post("/resend-verification", response_model=MessageResponse)
async def resend_verification(
    payload: ResendVerificationRequest,
    request: Request,
    database: AsyncIOMotorDatabase = Depends(get_database),
):
    settings = get_settings()
    email = normalize_email(payload.email)
    enforce_rate_limit(
        f"resend:ip:{_client_ip(request)}", settings.RESEND_RATE_LIMIT,
        settings.RESEND_RATE_WINDOW_SECONDS,
    )
    enforce_rate_limit(
        f"resend:email:{email}", settings.RESEND_RATE_LIMIT,
        settings.RESEND_RATE_WINDOW_SECONDS,
    )
    user = await get_user_by_email(database, email)
    raw = None
    if user and not user.email_verified and user.status in (
        UserStatus.PENDING_VERIFICATION, UserStatus.PENDING,
    ):
        raw = await _issue_verification(database, user, request)
    return MessageResponse(
        message="If the account needs verification, a new link has been sent.",
        verification_token=_verification_token(raw),
    )


@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    database: AsyncIOMotorDatabase = Depends(get_database),
):
    settings = get_settings()
    email = normalize_email(payload.email)
    enforce_rate_limit(
        f"forgot:ip:{_client_ip(request)}", settings.RESEND_RATE_LIMIT,
        settings.RESEND_RATE_WINDOW_SECONDS,
    )
    enforce_rate_limit(
        f"forgot:email:{email}", settings.RESEND_RATE_LIMIT,
        settings.RESEND_RATE_WINDOW_SECONDS,
    )
    user = await get_user_by_email(database, email)
    raw = None
    if user and user.status == UserStatus.ACTIVE:
        raw = await create_one_time_token(
            database,
            str(user.id),
            "password_reset",
            datetime.utcnow() + timedelta(minutes=30),
        )
        await send_email(
            user.email,
            "Reset your EnvPlatform password",
            "Open this single-use link within 30 minutes to reset your password:\n\n"
            f"{password_reset_link(raw)}\n",
        )
        await write_audit(
            database, "auth.password_reset_requested", actor=user,
            target=str(user.id), request=request,
        )
    return MessageResponse(
        message="If the account exists, a password reset link has been sent.",
        verification_token=_verification_token(raw),
    )


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(
    payload: ResetPasswordRequest,
    request: Request,
    database: AsyncIOMotorDatabase = Depends(get_database),
):
    validate_password(payload.new_password)
    token = await consume_one_time_token(database, payload.token, "password_reset")
    if not token:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    user = await get_user_by_id(database, token.get("user_id"))
    if not user:
        raise HTTPException(status_code=400, detail="Account not found")
    await database.users.update_one(
        {"_id": user.id},
        {"$set": {
            "hashed_password": get_password_hash(payload.new_password),
            "must_change_password": False,
            "failed_login_attempts": 0,
            "locked_until": None,
            "updated_at": datetime.utcnow(),
        }},
    )
    await bump_token_version(database, str(user.id))
    await write_audit(
        database, "auth.password_reset", actor=user, target=str(user.id),
        request=request,
    )
    return MessageResponse(message="Password reset. Sign in with your new password.")


@router.post("/login", response_model=Token)
async def login(
    response: Response,
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    database: AsyncIOMotorDatabase = Depends(get_database),
):
    settings = get_settings()
    email = normalize_email(form_data.username)
    enforce_rate_limit(
        f"login:ip:{_client_ip(request)}", settings.LOGIN_RATE_LIMIT,
        settings.LOGIN_RATE_WINDOW_SECONDS,
    )
    enforce_rate_limit(
        f"login:email:{email}", settings.LOGIN_RATE_LIMIT,
        settings.LOGIN_RATE_WINDOW_SECONDS,
    )
    user, reason = await authenticate_user_with_reason(
        database, form_data.username, form_data.password
    )
    if not user:
        if reason == "locked":
            raise HTTPException(status_code=429, detail="Too many failed attempts. Try again later.")
        if reason == "unverified":
            raise HTTPException(status_code=403, detail="Verify your email before signing in")
        if reason == "pending_approval":
            raise HTTPException(status_code=403, detail="Your account is awaiting administrator approval")
        if reason == "org_inactive":
            raise HTTPException(status_code=403, detail="Organization is pending or suspended")
        if reason == "inactive":
            raise HTTPException(status_code=403, detail="Account is not active")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user.must_change_password:
        token = await issue_tokens(database, user, response, request)
        return Token(**token, must_change_password=True, onboarding_required=False)
    if user.mfa_enabled:
        return Token(
            mfa_required=True,
            mfa_token=create_mfa_token(user, "verify"),
            must_change_password=False,
            onboarding_required=_token_flags(user)["onboarding_required"],
        )
    if await mfa_is_required(database, user):
        return Token(
            mfa_setup_required=True,
            mfa_token=create_mfa_token(user, "setup"),
            must_change_password=False,
            onboarding_required=_token_flags(user)["onboarding_required"],
        )

    token = await issue_tokens(database, user, response, request)
    return Token(**token, **_token_flags(user))


@router.post("/mfa/verify", response_model=Token)
async def verify_mfa(
    payload: MfaVerifyRequest,
    response: Response,
    request: Request,
    database: AsyncIOMotorDatabase = Depends(get_database),
):
    user = await get_mfa_user(database, payload.mfa_token)
    if not user.mfa_enabled or not user.mfa_secret:
        raise HTTPException(status_code=400, detail="MFA is not enabled for this account")
    if not verify_totp(user.mfa_secret, payload.code):
        await write_audit(database, "auth.mfa_failed", actor=user, target=str(user.id))
        raise HTTPException(status_code=401, detail="Invalid authentication code")
    token = await issue_tokens(database, user, response, request)
    return Token(**token, **_token_flags(user))


@router.post("/mfa/setup", response_model=MfaSetupResponse)
async def setup_mfa(
    payload: MfaSetupRequest,
    database: AsyncIOMotorDatabase = Depends(get_database),
):
    user = await get_mfa_user(database, payload.mfa_token)
    if user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA is already enabled")
    secret = generate_totp_secret()
    await database.users.update_one(
        {"_id": user.id},
        {"$set": {"pending_mfa_secret": secret, "updated_at": datetime.utcnow()}},
    )
    return MfaSetupResponse(secret=secret, otpauth_uri=totp_uri(secret, user.email))


@router.post("/mfa/enable", response_model=Token)
async def enable_mfa(
    payload: MfaEnableRequest,
    response: Response,
    request: Request,
    database: AsyncIOMotorDatabase = Depends(get_database),
):
    user = await get_mfa_user(database, payload.mfa_token)
    if user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA is already enabled")
    if not user.pending_mfa_secret or not verify_totp(user.pending_mfa_secret, payload.code):
        raise HTTPException(status_code=400, detail="Invalid authentication code")
    await database.users.update_one(
        {"_id": user.id},
        {"$set": {
            "mfa_secret": user.pending_mfa_secret,
            "pending_mfa_secret": None,
            "mfa_enabled": True,
            "updated_at": datetime.utcnow(),
        }},
    )
    user.mfa_enabled = True
    user.mfa_secret = user.pending_mfa_secret
    user.token_version = await bump_token_version(database, str(user.id))
    await write_audit(database, "auth.mfa_enabled", actor=user, target=str(user.id))
    token = await issue_tokens(database, user, response, request)
    return Token(**token, **_token_flags(user))


@router.post("/mfa/setup-authenticated", response_model=MfaSetupResponse)
async def setup_mfa_authenticated(
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(get_current_active_user),
):
    if current_user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA is already enabled")
    secret = generate_totp_secret()
    await database.users.update_one(
        {"_id": current_user.id},
        {"$set": {"pending_mfa_secret": secret, "updated_at": datetime.utcnow()}},
    )
    await write_audit(
        database, "auth.mfa_setup_started", actor=current_user, target=str(current_user.id),
    )
    return MfaSetupResponse(secret=secret, otpauth_uri=totp_uri(secret, current_user.email))


@router.post("/mfa/enable-authenticated", response_model=MessageResponse)
async def enable_mfa_authenticated(
    payload: MfaCodeRequest,
    response: Response,
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(get_current_active_user),
):
    if current_user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA is already enabled")
    if not current_user.pending_mfa_secret or not verify_totp(
        current_user.pending_mfa_secret, payload.code
    ):
        raise HTTPException(status_code=400, detail="Invalid authentication code")
    await database.users.update_one(
        {"_id": current_user.id},
        {"$set": {
            "mfa_secret": current_user.pending_mfa_secret,
            "pending_mfa_secret": None,
            "mfa_enabled": True,
            "updated_at": datetime.utcnow(),
        }},
    )
    await bump_token_version(database, str(current_user.id))
    clear_refresh_cookie(response)
    await write_audit(
        database, "auth.mfa_enabled", actor=current_user, target=str(current_user.id),
    )
    # Notify user of MFA change
    from app.services.notifications import notify_user
    await notify_user(
        database, str(current_user.id), "mfa_changed",
        "MFA enabled",
        "Multi-factor authentication has been enabled on your account.",
        link="/mfa",
        severity="info",
    )
    return MessageResponse(message="MFA enabled. Sign in again.")


@router.post("/mfa/disable", response_model=MessageResponse)
async def disable_mfa(
    payload: MfaDisableRequest,
    response: Response,
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(get_current_active_user),
):
    if await mfa_is_required(database, current_user):
        raise HTTPException(status_code=400, detail="MFA is required for this account")
    if not verify_password(payload.password, current_user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect password")
    if not verify_totp(current_user.mfa_secret, payload.code):
        raise HTTPException(status_code=401, detail="Invalid authentication code")
    await database.users.update_one(
        {"_id": current_user.id},
        {"$set": {
            "mfa_enabled": False,
            "mfa_secret": None,
            "pending_mfa_secret": None,
            "updated_at": datetime.utcnow(),
        }},
    )
    await bump_token_version(database, str(current_user.id))
    clear_refresh_cookie(response)
    await write_audit(database, "auth.mfa_disabled", actor=current_user, target=str(current_user.id))
    return MessageResponse(message="MFA disabled. Sign in again.")


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(
    request: Request,
    response: Response,
    database: AsyncIOMotorDatabase = Depends(get_database),
):
    raw = request.cookies.get(REFRESH_COOKIE)
    try:
        _, new_raw, expires_in, access = await rotate_refresh_token(database, raw)
    except AuthFailure as exc:
        if exc.clear_cookie:
            clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    set_refresh_cookie(response, new_raw)
    return RefreshResponse(access_token=access, expires_in=expires_in)


@router.post("/logout", response_model=MessageResponse)
async def logout(
    request: Request,
    response: Response,
    database: AsyncIOMotorDatabase = Depends(get_database),
):
    raw = request.cookies.get(REFRESH_COOKIE)
    await revoke_refresh_token(database, raw)
    clear_refresh_cookie(response)
    return MessageResponse(message="Signed out.")


@router.get("/me")
async def read_users_me(current_user=Depends(get_password_change_user)):
    return user_public(current_user)


@router.get("/me/usage")
async def read_my_usage(
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(get_current_active_user),
):
    return {
        "quota": await quota_public_for(database, current_user),
        "usage": await usage_for_user(database, current_user),
        "max_upload_bytes": upload_limit_for(current_user),
    }


@router.post("/onboarding/complete", response_model=OnboardingResponse)
async def complete_onboarding(
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(get_current_active_user),
):
    await database.users.update_one(
        {"_id": current_user.id},
        {"$set": {"onboarding_completed": True, "updated_at": datetime.utcnow()}},
    )
    await write_audit(
        database, "auth.onboarding_completed", actor=current_user,
        target=str(current_user.id),
    )
    return OnboardingResponse(
        message="Onboarding complete.", onboarding_completed=True,
    )


@router.post("/password", response_model=MessageResponse)
async def change_password(
    payload: PasswordChangeRequest,
    response: Response,
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(get_password_change_user),
):
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect current password")
    validate_password(payload.new_password)
    await database.users.update_one(
        {"_id": current_user.id},
        {"$set": {
            "hashed_password": get_password_hash(payload.new_password),
            "must_change_password": False,
            "updated_at": datetime.utcnow(),
        }},
    )
    await bump_token_version(database, str(current_user.id))
    clear_refresh_cookie(response)
    await write_audit(database, "auth.password_changed", actor=current_user, target=str(current_user.id))
    from app.services.notifications import notify_user
    await notify_user(
        database, str(current_user.id), "password_changed",
        "Password changed",
        "Your password has been successfully changed.",
        link="/change-password",
        severity="info",
    )
    return MessageResponse(message="Password changed. Sign in again.")


def _admin_public(doc: dict) -> dict:
    return user_public(UserInDB(**_normalize_user_doc(doc)))


@router.get("/admin/users")
async def admin_list_users(
    status_filter: Optional[UserStatus] = None,
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(require_platform_admin),
):
    query = {}
    if status_filter:
        query["status"] = status_filter.value
    docs = await database.users.find(query).sort("created_at", -1).to_list(length=200)
    return [_admin_public(doc) for doc in docs]


@router.post("/admin/users/{user_id}/approve", response_model=dict)
async def admin_approve_user(
    user_id: str,
    payload: AdminUserDecision,
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(require_platform_admin),
):
    user = await get_user_by_id(database, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.status != UserStatus.PENDING_APPROVAL:
        raise HTTPException(status_code=409, detail="User is not awaiting approval")
    account_type = user.account_type
    if payload.account_type:
        try:
            account_type = AccountType(payload.account_type)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid account type")
    await database.users.update_one(
        {"_id": user.id},
        {"$set": {
            "status": UserStatus.ACTIVE.value,
            "account_type": account_type.value,
            "review_required": False,
            "approved_by": str(current_user.id),
            "approved_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }},
    )
    await bump_token_version(database, user_id)
    await send_email(
        user.email,
        "Your EnvPlatform account was approved",
        "Your account was approved. Sign in to continue.",
    )
    await write_audit(
        database, "auth.user_approved", actor=current_user, target=user_id,
        metadata={"account_type": account_type.value, "reason": payload.reason},
    )
    user = await get_user_by_id(database, user_id)
    return user_public(user)


@router.post("/admin/users/{user_id}/reject", response_model=dict)
async def admin_reject_user(
    user_id: str,
    payload: AdminUserDecision,
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(require_platform_admin),
):
    user = await get_user_by_id(database, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.status != UserStatus.PENDING_APPROVAL:
        raise HTTPException(status_code=409, detail="User is not awaiting approval")
    await database.users.update_one(
        {"_id": user.id},
        {"$set": {
            "status": UserStatus.REJECTED.value,
            "review_required": False,
            "rejected_reason": payload.reason,
            "updated_at": datetime.utcnow(),
        }},
    )
    await bump_token_version(database, user_id)
    await send_email(
        user.email,
        "Your EnvPlatform account application",
        f"Your account application was not approved. {payload.reason or ''}".strip(),
    )
    await write_audit(
        database, "auth.user_rejected", actor=current_user, target=user_id,
        metadata={"reason": payload.reason},
    )
    user = await get_user_by_id(database, user_id)
    return user_public(user)


@router.patch("/admin/users/{user_id}", response_model=dict)
async def admin_update_user(
    user_id: str,
    payload: AdminUserUpdate,
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(require_platform_admin),
):
    user = await get_user_by_id(database, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    updates = {"updated_at": datetime.utcnow()}
    if payload.account_type:
        try:
            updates["account_type"] = AccountType(payload.account_type).value
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid account type")
    if payload.platform_role:
        try:
            role = PlatformRole(payload.platform_role)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid platform role")
        if role == PlatformRole.PLATFORM_ADMIN and (
            not user.mfa_enabled
            or user.status != UserStatus.ACTIVE
            or not user.email_verified
        ):
            raise HTTPException(
                status_code=400,
                detail="The user must have a verified, active account with MFA enabled",
            )
        updates["platform_role"] = role.value
        if role == PlatformRole.PLATFORM_ADMIN:
            updates["account_type"] = AccountType.RESEARCHER.value
    await database.users.update_one({"_id": user.id}, {"$set": updates})
    await bump_token_version(database, user_id)
    await write_audit(
        database, "auth.user_updated", actor=current_user, target=user_id,
        metadata={k: str(v) for k, v in updates.items() if k != "updated_at"},
    )
    user = await get_user_by_id(database, user_id)
    return user_public(user)
