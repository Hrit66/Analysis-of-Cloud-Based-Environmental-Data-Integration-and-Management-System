from datetime import datetime, timedelta
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.api.auth import (
    get_current_active_user,
    get_database,
    require_platform_admin,
)
from app.config import get_settings
from app.models.auth import MessageResponse
from app.models.organization import (
    InviteCreate,
    InviteResponse,
    MemberResponse,
    MemberRoleUpdate,
    OrganizationApproval,
    OrganizationContactResend,
    OrganizationContactVerify,
    OrganizationDecision,
    OrganizationSetup,
    InviteAccept,
    OrganizationCreate,
    OrganizationResponse,
    OrganizationSettings,
    OrganizationStatus,
    OrganizationSuspend,
)
from app.models.user import AccountType, OrgRole, PlatformRole, Token, UserCreate, UserStatus
from app.services.auth import (
    bump_token_version,
    consume_one_time_token,
    create_one_time_token,
    create_user,
    get_user_by_email,
    get_user_by_id,
    create_mfa_token,
    create_one_time_token_record,
    get_password_hash,
    issue_tokens,
    mfa_is_required,
    normalize_email,
    revoke_all_refresh_tokens,
    user_public,
    write_audit,
)
from app.services.domains import domain_matches, email_domain
from app.services.email import (
    send_decision_email,
    send_invite_email,
    send_org_contact_email,
    send_org_setup_email,
)
from app.services.organizations import (
    ACCOUNT_TYPE_BY_ORG,
    ensure_not_last_admin,
    get_org,
    normalize_domains,
    require_verified_org,
)
from app.services.passwords import validate_password
from app.services.rate_limit import enforce as enforce_rate_limit

router = APIRouter(prefix="/api/organizations", tags=["organizations"])


def _org_response(org: dict) -> OrganizationResponse:
    return OrganizationResponse(
        id=str(org["_id"]),
        name=org["name"],
        type=org["type"],
        domains=org.get("domains") or [],
        country=org.get("country"),
        contact_email=org["contact_email"],
        phone=org.get("phone"),
        purpose=org.get("purpose"),
        document_url=org.get("document_url"),
        contact_verified=bool(org.get("contact_verified", False)),
        contact_verified_at=org.get("contact_verified_at"),
        status=org.get("status", OrganizationStatus.PENDING.value),
        settings=org.get("settings") or {},
        requested_by=org.get("requested_by"),
        created_at=org.get("created_at") or datetime.utcnow(),
        updated_at=org.get("updated_at") or datetime.utcnow(),
        approved_by=org.get("approved_by"),
        approved_at=org.get("approved_at"),
        approval_note=org.get("approval_note"),
        rejected_by=org.get("rejected_by"),
        rejected_at=org.get("rejected_at"),
        rejected_reason=org.get("rejected_reason"),
    )


def _is_org_admin(user, org_id: str) -> bool:
    return bool(
        user.org_id
        and str(user.org_id) == str(org_id)
        and user.org_role == OrgRole.ORG_ADMIN
    )


def _is_platform_admin(user) -> bool:
    return user.platform_role == PlatformRole.PLATFORM_ADMIN


async def _require_org_manager(user, org_id: str):
    if _is_platform_admin(user):
        return
    if not _is_org_admin(user, org_id):
        raise HTTPException(status_code=404, detail="Organization not found")


def _client_ip(request) -> str:
    if request is not None and getattr(request, "client", None):
        return request.client.host
    return "unknown"


async def _domain_conflict(database, domains, exclude_id=None):
    docs = await database.organizations.find({}).to_list(length=None)
    for org in docs:
        if exclude_id and str(org.get("_id")) == str(exclude_id):
            continue
        if org.get("status") not in (
            OrganizationStatus.PENDING.value,
            OrganizationStatus.INFO_REQUESTED.value,
            OrganizationStatus.VERIFIED.value,
        ):
            continue
        if set(domains) & set(org.get("domains") or []):
            return org
    return None


async def _validate_application(database, payload: OrganizationCreate):
    domains = normalize_domains(payload.domains)
    if not domains:
        raise HTTPException(status_code=400, detail="Provide at least one organization domain")
    if not payload.terms_accepted:
        raise HTTPException(status_code=400, detail="Accept the terms to apply")
    contact_email = normalize_email(payload.contact_email)
    if not domain_matches(email_domain(contact_email), domains):
        raise HTTPException(
            status_code=400,
            detail="The contact email must use one of the organization domains",
        )
    conflict = await _domain_conflict(database, domains)
    if conflict:
        raise HTTPException(status_code=409, detail="One or more domains are already registered")
    return domains, contact_email


async def _create_application(
    database,
    payload: OrganizationCreate,
    request=None,
    requested_by: Optional[str] = None,
    validated=None,
):
    settings = get_settings()
    domains, contact_email = validated or await _validate_application(database, payload)
    if validated and await _domain_conflict(database, domains):
        raise HTTPException(status_code=409, detail="One or more domains are already registered")
    now = datetime.utcnow()
    doc = {
        "name": payload.name.strip(),
        "type": payload.type.value,
        "domains": domains,
        "country": payload.country,
        "contact_email": contact_email,
        "phone": payload.phone,
        "purpose": payload.purpose,
        "document_url": payload.document_url,
        "contact_verified": False,
        "contact_verified_at": None,
        "status": OrganizationStatus.PENDING.value,
        "settings": {
            "require_mfa": True,
            "allowed_domains": domains,
            "default_visibility": "private",
        },
        "requested_by": str(requested_by) if requested_by else None,
        "terms_version": settings.TERMS_VERSION,
        "terms_accepted_at": now,
        "created_at": now,
        "updated_at": now,
    }
    result = await database.organizations.insert_one(doc)
    doc["_id"] = result.inserted_id
    org_id = str(result.inserted_id)
    raw, _ = await create_one_time_token_record(
        database,
        str(requested_by) if requested_by else "public",
        "org_contact",
        now + timedelta(minutes=settings.EMAIL_VERIFICATION_EXPIRE_MINUTES),
        metadata={"org_id": org_id, "email": contact_email},
    )
    await send_org_contact_email(contact_email, doc["name"], raw)
    await write_audit(
        database, "org.applied", actor=None, org_id=org_id, target=org_id,
        metadata={"contact_email": contact_email, "requested_by": str(requested_by) if requested_by else None},
        request=request,
    )
    return doc


@router.post("/applications", response_model=OrganizationResponse, status_code=201)
async def apply_organization_public(
    payload: OrganizationCreate,
    request: Request,
    database: AsyncIOMotorDatabase = Depends(get_database),
):
    settings = get_settings()
    validated = await _validate_application(database, payload)
    email = validated[1]
    enforce_rate_limit(
        f"org-apply:ip:{_client_ip(request)}", settings.ORG_APPLY_RATE_LIMIT,
        settings.ORG_APPLY_RATE_WINDOW_SECONDS,
    )
    enforce_rate_limit(
        f"org-apply:email:{email}", settings.ORG_APPLY_RATE_LIMIT,
        settings.ORG_APPLY_RATE_WINDOW_SECONDS,
    )
    doc = await _create_application(
        database, payload, request=request, validated=validated,
    )
    # Notify platform admins of new org application
    from app.services.notifications import notify_admins
    await notify_admins(
        database, "org_application_pending",
        "New organization application",
        f"Organization '{payload.name}' has applied (contact: {validated[1]}).",
        link="/admin?tab=orgs",
        severity="info",
    )
    return _org_response(doc)


@router.post("/applications/resend-contact", response_model=MessageResponse)
async def resend_organization_contact(
    payload: OrganizationContactResend,
    request: Request,
    database: AsyncIOMotorDatabase = Depends(get_database),
):
    settings = get_settings()
    email = normalize_email(payload.contact_email)
    enforce_rate_limit(
        f"org-resend:ip:{_client_ip(request)}", settings.RESEND_RATE_LIMIT,
        settings.RESEND_RATE_WINDOW_SECONDS,
    )
    enforce_rate_limit(
        f"org-resend:email:{email}", settings.RESEND_RATE_LIMIT,
        settings.RESEND_RATE_WINDOW_SECONDS,
    )
    raw = None
    org = await database.organizations.find_one({
        "contact_email": email,
        "status": {"$in": [
            OrganizationStatus.PENDING.value,
            OrganizationStatus.INFO_REQUESTED.value,
        ]},
    })
    if org:
        raw, _ = await create_one_time_token_record(
            database, "public", "org_contact",
            datetime.utcnow() + timedelta(minutes=settings.EMAIL_VERIFICATION_EXPIRE_MINUTES),
            metadata={"org_id": str(org["_id"]), "email": email},
        )
        await send_org_contact_email(email, org["name"], raw)
    return MessageResponse(
        message="If the application exists, a new verification link has been sent.",
        verification_token=raw if settings.ENVIRONMENT == "development" else None,
    )


@router.post("/applications/verify-contact", response_model=OrganizationResponse)
async def verify_organization_contact(
    payload: OrganizationContactVerify,
    database: AsyncIOMotorDatabase = Depends(get_database),
):
    token = await consume_one_time_token(database, payload.token, "org_contact")
    if not token:
        raise HTTPException(status_code=400, detail="Invalid or expired verification token")
    org_id = (token.get("metadata") or {}).get("org_id")
    org = await get_org(database, org_id)
    if not org:
        raise HTTPException(status_code=400, detail="Organization application not found")
    if org.get("status") not in (
        OrganizationStatus.PENDING.value,
        OrganizationStatus.INFO_REQUESTED.value,
    ):
        raise HTTPException(status_code=409, detail="This application cannot be verified now")
    now = datetime.utcnow()
    await database.organizations.update_one(
        {"_id": org["_id"]},
        {"$set": {
            "contact_verified": True,
            "contact_verified_at": now,
            "updated_at": now,
        }},
    )
    org = await get_org(database, org_id)
    await write_audit(
        database, "org.contact_verified", org_id=org_id, target=org_id,
        metadata={"contact_email": org.get("contact_email")},
    )
    return _org_response(org)


@router.get("/applications")
async def list_organization_applications(
    status: Optional[OrganizationStatus] = None,
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(require_platform_admin),
):
    query = {}
    if status:
        query["status"] = status.value
    docs = await database.organizations.find(query).sort("created_at", -1).to_list(length=200)
    return [_org_response(doc) for doc in docs]


@router.post("/applications/{org_id}/reject", response_model=OrganizationResponse)
async def reject_organization(
    org_id: str,
    payload: OrganizationDecision,
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(require_platform_admin),
):
    org = await get_org(database, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    if org.get("status") not in (
        OrganizationStatus.PENDING.value,
        OrganizationStatus.INFO_REQUESTED.value,
    ):
        raise HTTPException(status_code=409, detail="Application is not pending")
    now = datetime.utcnow()
    await database.organizations.update_one(
        {"_id": org["_id"]},
        {"$set": {
            "status": OrganizationStatus.REJECTED.value,
            "rejected_reason": payload.reason,
            "rejected_by": str(current_user.id),
            "rejected_at": now,
            "updated_at": now,
        }},
    )
    await send_decision_email(
        org["contact_email"], org["name"], False, payload.reason
    )
    await write_audit(
        database, "org.rejected", actor=current_user, org_id=org_id,
        target=org_id, metadata={"reason": payload.reason},
    )

    # Notify requester of rejection
    from app.services.notifications import notify_user
    requester_id = org.get("requested_by")
    if requester_id:
        await notify_user(
            database, str(requester_id), "org_application_decision",
            f"Organization '{org['name']}' application declined",
            f"Reason: {payload.reason}",
            link="/organization",
            severity="warning",
        )

    return _org_response(await get_org(database, org_id))


@router.post("/applications/{org_id}/request-info", response_model=OrganizationResponse)
async def request_organization_info(
    org_id: str,
    payload: OrganizationDecision,
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(require_platform_admin),
):
    org = await get_org(database, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    if org.get("status") not in (
        OrganizationStatus.PENDING.value,
        OrganizationStatus.INFO_REQUESTED.value,
    ):
        raise HTTPException(status_code=409, detail="Application is not pending")
    await database.organizations.update_one(
        {"_id": org["_id"]},
        {"$set": {
            "status": OrganizationStatus.INFO_REQUESTED.value,
            "info_requested_reason": payload.reason,
            "info_requested_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }},
    )
    await send_decision_email(org["contact_email"], org["name"], False, payload.reason)
    await write_audit(
        database, "org.info_requested", actor=current_user, org_id=org_id,
        target=org_id, metadata={"reason": payload.reason},
    )
    return _org_response(await get_org(database, org_id))


@router.post("", response_model=OrganizationResponse, status_code=201)
async def apply_organization(
    payload: OrganizationCreate,
    request: Request,
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(get_current_active_user),
):
    if current_user.org_id:
        raise HTTPException(status_code=400, detail="This account already belongs to an organization")
    existing = await database.organizations.find_one({
        "status": OrganizationStatus.PENDING.value,
        "requested_by": str(current_user.id),
    })
    if existing:
        raise HTTPException(status_code=409, detail="You already have a pending organization application")
    doc = await _create_application(
        database, payload, request=request, requested_by=str(current_user.id)
    )
    return _org_response(doc)


@router.get("", response_model=list)
async def list_organizations(
    status: Optional[OrganizationStatus] = None,
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(require_platform_admin),
):
    query = {}
    if status:
        query["status"] = status.value
    docs = await database.organizations.find(query).sort("created_at", -1).to_list(length=200)
    return [_org_response(doc) for doc in docs]


@router.get("/me", response_model=OrganizationResponse)
async def my_organization(
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(get_current_active_user),
):
    if not current_user.org_id:
        raise HTTPException(status_code=404, detail="No organization membership")
    org = await get_org(database, current_user.org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return _org_response(org)


@router.get("/{org_id}", response_model=OrganizationResponse)
async def get_organization(
    org_id: str,
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(get_current_active_user),
):
    org = await get_org(database, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    if (
        not _is_platform_admin(current_user)
        and str(current_user.org_id or "") != str(org_id)
        and str(org.get("requested_by") or "") != str(current_user.id)
    ):
        raise HTTPException(status_code=404, detail="Organization not found")
    return _org_response(org)


@router.post("/{org_id}/approve", response_model=OrganizationResponse)
async def approve_organization(
    org_id: str,
    payload: OrganizationApproval,
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(require_platform_admin),
):
    org = await get_org(database, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    if org.get("status") not in (
        OrganizationStatus.PENDING.value,
        OrganizationStatus.INFO_REQUESTED.value,
    ):
        raise HTTPException(status_code=409, detail="Organization is not pending")
    if not org.get("contact_verified", True):
        raise HTTPException(status_code=409, detail="Verify the organization contact email first")
    legacy_requester = "contact_verified" not in org
    requester = await get_user_by_id(database, org.get("requested_by"))
    if legacy_requester and not requester:
        raise HTTPException(status_code=400, detail="Organization requester no longer exists")
    now = datetime.utcnow()
    await database.organizations.update_one(
        {"_id": org["_id"]},
        {"$set": {
            "status": OrganizationStatus.VERIFIED.value,
            "approved_by": str(current_user.id),
            "approved_at": now,
            "approval_note": payload.note,
            "updated_at": now,
        }},
    )
    if legacy_requester:
        await database.users.update_one(
            {"_id": requester.id},
            {"$set": {
                "org_id": str(org["_id"]),
                "org_role": OrgRole.ORG_ADMIN.value,
                "account_type": ACCOUNT_TYPE_BY_ORG.get(org["type"], AccountType.RESEARCHER).value,
                "email_verified": True,
                "status": UserStatus.ACTIVE.value,
                "updated_at": now,
            }},
        )
        await bump_token_version(database, str(requester.id))
    else:
        raw, _ = await create_one_time_token_record(
            database,
            str(org.get("requested_by") or "public"),
            "org_setup",
            now + timedelta(days=get_settings().INVITE_EXPIRE_DAYS),
            metadata={
                "org_id": org_id,
                "email": org.get("contact_email"),
                "org_role": OrgRole.ORG_ADMIN.value,
            },
        )
        await send_org_setup_email(org["contact_email"], org["name"], raw)
    org = await get_org(database, org_id)
    await write_audit(
        database, "org.approved", actor=current_user, org_id=org_id,
        target=org_id, metadata={"requester": str(org.get("requested_by") or "")},
    )

    # Notify requester/org admins of approval
    from app.services.notifications import notify_org_admins, notify_user
    requester_id = org.get("requested_by")
    if requester_id:
        await notify_user(
            database, str(requester_id), "org_application_decision",
            f"Organization '{org['name']}' approved",
            "Your organization application has been approved. You can now set up your organization.",
            link="/organization",
            severity="info",
        )
    await notify_org_admins(
        database, str(org["_id"]), "org_application_decision",
        f"Organization '{org['name']}' approved",
        "The organization has been approved and is now active.",
        link="/organization",
        severity="info",
    )
    return _org_response(org)


@router.post("/setup", response_model=Token)
async def setup_organization_admin(
    payload: OrganizationSetup,
    request: Request,
    response: Response,
    database: AsyncIOMotorDatabase = Depends(get_database),
):
    validate_password(payload.password)
    if not payload.terms_accepted:
        raise HTTPException(status_code=400, detail="Accept the terms to continue")
    token = await consume_one_time_token(database, payload.token, "org_setup")
    if not token:
        raise HTTPException(status_code=400, detail="Invalid or expired setup link")
    metadata = token.get("metadata") or {}
    org_id = metadata.get("org_id")
    org = await require_verified_org(database, org_id)
    email = normalize_email(metadata.get("email") or org.get("contact_email") or "")
    if not email:
        raise HTTPException(status_code=400, detail="Setup link has no email")
    account_type = ACCOUNT_TYPE_BY_ORG.get(org["type"], AccountType.RESEARCHER)
    user = await get_user_by_email(database, email)
    if user:
        if user.platform_role == PlatformRole.PLATFORM_ADMIN:
            raise HTTPException(status_code=409, detail="Platform administrators cannot be organization admins")
        if user.org_id and str(user.org_id) != str(org_id):
            raise HTTPException(status_code=409, detail="This email already belongs to another organization")
        await database.users.update_one(
            {"_id": user.id},
            {"$set": {
                "hashed_password": get_password_hash(payload.password),
                "org_id": str(org_id),
                "org_role": OrgRole.ORG_ADMIN.value,
                "account_type": account_type.value,
                "email_verified": True,
                "status": UserStatus.ACTIVE.value,
                "must_change_password": False,
                "terms_version": get_settings().TERMS_VERSION,
                "terms_accepted_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }},
        )
        user = await get_user_by_id(database, str(user.id))
        user.token_version = await bump_token_version(database, str(user.id))
    else:
        user = await create_user(
            database,
            UserCreate(
                email=email,
                password=payload.password,
                full_name=payload.full_name,
                account_type=account_type,
                org_id=str(org_id),
                org_role=OrgRole.ORG_ADMIN,
                email_verified=True,
                status=UserStatus.ACTIVE,
                terms_version=get_settings().TERMS_VERSION,
                terms_accepted_at=datetime.utcnow(),
            ),
            email_verified=True,
            status=UserStatus.ACTIVE,
        )
    await write_audit(
        database, "org.admin_setup", actor=user, org_id=org_id, target=str(user.id),
    )
    if user.mfa_enabled:
        return Token(mfa_required=True, mfa_token=create_mfa_token(user, "verify"))
    if await mfa_is_required(database, user):
        return Token(mfa_setup_required=True, mfa_token=create_mfa_token(user, "setup"))
    issued = await issue_tokens(database, user, response=response, request=request)
    return Token(**issued)


@router.post("/{org_id}/suspend", response_model=OrganizationResponse)
async def suspend_organization(
    org_id: str,
    payload: OrganizationSuspend,
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(require_platform_admin),
):
    org = await get_org(database, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    now = datetime.utcnow()
    await database.organizations.update_one(
        {"_id": org["_id"]},
        {"$set": {
            "status": OrganizationStatus.SUSPENDED.value,
            "suspended_at": now,
            "suspended_by": str(current_user.id),
            "suspend_reason": payload.reason,
            "updated_at": now,
        }},
    )
    members = await database.users.find({"org_id": str(org_id)}).to_list(length=None)
    await database.users.update_many(
        {"org_id": str(org_id)},
        {"$inc": {"token_version": 1}, "$set": {"updated_at": now}},
    )
    for member in members:
        await revoke_all_refresh_tokens(database, str(member["_id"]))
    org = await get_org(database, org_id)
    await write_audit(
        database, "org.suspended", actor=current_user, org_id=org_id,
        target=org_id, metadata={"reason": payload.reason},
    )
    return _org_response(org)


@router.post("/{org_id}/reinstate", response_model=OrganizationResponse)
async def reinstate_organization(
    org_id: str,
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(require_platform_admin),
):
    org = await get_org(database, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    if org.get("status") != OrganizationStatus.SUSPENDED.value:
        raise HTTPException(status_code=409, detail="Organization is not suspended")
    await database.organizations.update_one(
        {"_id": org["_id"]},
        {"$set": {
            "status": OrganizationStatus.VERIFIED.value,
            "suspended_at": None,
            "suspend_reason": None,
            "updated_at": datetime.utcnow(),
        }},
    )
    org = await get_org(database, org_id)
    await write_audit(database, "org.reinstated", actor=current_user, org_id=org_id, target=org_id)
    return _org_response(org)


@router.patch("/{org_id}/settings", response_model=OrganizationResponse)
async def update_settings(
    org_id: str,
    payload: OrganizationSettings,
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(get_current_active_user),
):
    if not _is_org_admin(current_user, org_id):
        raise HTTPException(status_code=404, detail="Organization not found")
    await require_verified_org(database, org_id)
    settings = payload.model_dump()
    settings["allowed_domains"] = normalize_domains(settings.get("allowed_domains") or [])
    await database.organizations.update_one(
        {"_id": ObjectId(org_id)},
        {"$set": {"settings": settings, "updated_at": datetime.utcnow()}},
    )
    org = await get_org(database, org_id)
    await write_audit(database, "org.settings_updated", actor=current_user, org_id=org_id, target=org_id)
    return _org_response(org)


@router.get("/{org_id}/members")
async def list_members(
    org_id: str,
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(get_current_active_user),
):
    await _require_org_manager(current_user, org_id)
    docs = await database.users.find({"org_id": str(org_id)}).sort("created_at", 1).to_list(length=500)
    return [
        MemberResponse(
            user_id=str(doc["_id"]),
            email=doc["email"],
            full_name=doc.get("full_name"),
            account_type=doc.get("account_type", "student"),
            org_role=doc.get("org_role"),
            status=doc.get("status", "active"),
            mfa_enabled=bool(doc.get("mfa_enabled")),
            created_at=doc.get("created_at") or datetime.utcnow(),
        )
        for doc in docs
    ]


@router.patch("/{org_id}/members/{user_id}", response_model=MemberResponse)
async def update_member_role(
    org_id: str,
    user_id: str,
    payload: MemberRoleUpdate,
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(get_current_active_user),
):
    if not _is_org_admin(current_user, org_id):
        raise HTTPException(status_code=404, detail="Organization not found")
    target = await get_user_by_id(database, user_id)
    if not target or str(target.org_id or "") != str(org_id):
        raise HTTPException(status_code=404, detail="Member not found")
    if target.platform_role == PlatformRole.PLATFORM_ADMIN:
        raise HTTPException(status_code=400, detail="Platform admins are managed separately")
    if target.org_role == OrgRole.ORG_ADMIN and payload.org_role != OrgRole.ORG_ADMIN:
        await ensure_not_last_admin(database, org_id, user_id)
    await database.users.update_one(
        {"_id": target.id},
        {"$set": {"org_role": payload.org_role.value, "updated_at": datetime.utcnow()}},
    )
    await bump_token_version(database, user_id)
    await write_audit(
        database, "org.member_role_updated", actor=current_user, org_id=org_id,
        target=user_id, metadata={"org_role": payload.org_role.value},
    )
    return MemberResponse(
        user_id=user_id,
        email=target.email,
        full_name=target.full_name,
        account_type=target.account_type.value,
        org_role=payload.org_role,
        status=target.status.value,
        mfa_enabled=target.mfa_enabled,
        created_at=target.created_at,
    )


@router.delete("/{org_id}/members/{user_id}", response_model=MessageResponse)
async def remove_member(
    org_id: str,
    user_id: str,
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(get_current_active_user),
):
    if not _is_org_admin(current_user, org_id):
        raise HTTPException(status_code=404, detail="Organization not found")
    target = await get_user_by_id(database, user_id)
    if not target or str(target.org_id or "") != str(org_id):
        raise HTTPException(status_code=404, detail="Member not found")
    if target.platform_role == PlatformRole.PLATFORM_ADMIN:
        raise HTTPException(status_code=400, detail="Platform admins are managed separately")
    await ensure_not_last_admin(database, org_id, user_id)
    await database.users.update_one(
        {"_id": target.id},
        {"$set": {
            "org_id": None,
            "org_role": None,
            "status": UserStatus.ACTIVE.value,
            "updated_at": datetime.utcnow(),
        }},
    )
    await bump_token_version(database, user_id)
    await write_audit(
        database, "org.member_removed", actor=current_user, org_id=org_id, target=user_id,
    )
    return MessageResponse(message="Member removed. Their sessions have been revoked.")


@router.post("/{org_id}/invites", response_model=InviteResponse, status_code=201)
async def create_invite(
    org_id: str,
    payload: InviteCreate,
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(get_current_active_user),
):
    if not _is_org_admin(current_user, org_id):
        raise HTTPException(status_code=404, detail="Organization not found")
    org = await require_verified_org(database, org_id)
    email = normalize_email(payload.email)
    existing = await get_user_by_email(database, email)
    if existing and str(existing.org_id or "") == str(org_id):
        raise HTTPException(status_code=409, detail="This account is already a member")
    pending = await database.one_time_tokens.find({
        "kind": "org_invite", "used_at": None,
    }).to_list(length=500)
    for doc in pending:
        meta = doc.get("metadata") or {}
        if (
            str(meta.get("org_id")) == str(org_id)
            and meta.get("email") == email
            and doc.get("expires_at") and doc["expires_at"] > datetime.utcnow()
        ):
            raise HTTPException(status_code=409, detail="An invitation is already pending for this email")
    expires = datetime.utcnow() + timedelta(days=get_settings().INVITE_EXPIRE_DAYS)
    raw, token_id = await create_one_time_token_record(
        database,
        str(current_user.id),
        "org_invite",
        expires,
        metadata={
            "org_id": str(org_id),
            "org_role": payload.org_role.value,
            "email": email,
            "invited_by": str(current_user.id),
        },
    )
    await send_invite_email(email, org["name"], raw, payload.org_role.value)
    await write_audit(
        database, "org.invite_created", actor=current_user, org_id=org_id,
        target=email, metadata={"org_role": payload.org_role.value},
    )
    return InviteResponse(
        id=token_id,
        email=email,
        org_id=str(org_id),
        org_role=payload.org_role,
        expires_at=expires,
        token=raw if get_settings().ENVIRONMENT == "development" else None,
    )


@router.get("/{org_id}/invites")
async def list_invites(
    org_id: str,
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(get_current_active_user),
):
    if not _is_org_admin(current_user, org_id):
        raise HTTPException(status_code=404, detail="Organization not found")
    docs = await database.one_time_tokens.find({
        "kind": "org_invite", "used_at": None,
    }).to_list(length=500)
    now = datetime.utcnow()
    result = []
    for doc in docs:
        meta = doc.get("metadata") or {}
        if str(meta.get("org_id")) != str(org_id):
            continue
        if doc.get("expires_at") and doc["expires_at"] <= now:
            continue
        result.append(InviteResponse(
            id=str(doc["_id"]),
            email=meta.get("email"),
            org_id=str(org_id),
            org_role=OrgRole(meta.get("org_role") or OrgRole.VIEWER.value),
            expires_at=doc["expires_at"],
        ))
    return result


@router.delete("/{org_id}/invites/{invite_id}", response_model=MessageResponse)
async def revoke_invite(
    org_id: str,
    invite_id: str,
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(get_current_active_user),
):
    if not _is_org_admin(current_user, org_id):
        raise HTTPException(status_code=404, detail="Organization not found")
    try:
        object_id = ObjectId(invite_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Invitation not found")
    doc = await database.one_time_tokens.find_one({
        "_id": object_id, "kind": "org_invite", "used_at": None,
    })
    if not doc or str((doc.get("metadata") or {}).get("org_id")) != str(org_id):
        raise HTTPException(status_code=404, detail="Invitation not found")
    await database.one_time_tokens.update_one(
        {"_id": object_id},
        {"$set": {"used_at": datetime.utcnow(), "revoked_by": str(current_user.id)}},
    )
    await write_audit(
        database, "org.invite_revoked", actor=current_user, org_id=org_id,
        target=invite_id,
    )
    return MessageResponse(message="Invitation revoked.")


@router.post("/accept-invite", response_model=Token)
async def accept_invite(
    payload: InviteAccept,
    request: Request,
    response: Response,
    database: AsyncIOMotorDatabase = Depends(get_database),
):
    validate_password(payload.password)
    if not payload.terms_accepted:
        raise HTTPException(status_code=400, detail="Accept the terms to join the organization")
    token = await consume_one_time_token(database, payload.token, "org_invite")
    if not token:
        raise HTTPException(status_code=400, detail="Invalid or expired invitation")
    metadata = token.get("metadata") or {}
    org_id = metadata.get("org_id")
    org = await require_verified_org(database, org_id)
    email = normalize_email(metadata.get("email") or "")
    role = OrgRole(metadata.get("org_role") or OrgRole.VIEWER.value)
    account_type = ACCOUNT_TYPE_BY_ORG.get(org["type"], AccountType.RESEARCHER)
    user = await get_user_by_email(database, email)
    if user:
        if user.platform_role == PlatformRole.PLATFORM_ADMIN:
            raise HTTPException(status_code=409, detail="Platform administrators cannot join an organization")
        if user.org_id and str(user.org_id) != str(org_id):
            raise HTTPException(status_code=409, detail="This account already belongs to another organization")
        await database.users.update_one(
            {"_id": user.id},
            {"$set": {
                "org_id": str(org_id),
                "org_role": role.value,
                "account_type": account_type.value,
                "email_verified": True,
                "status": UserStatus.ACTIVE.value,
                "terms_version": get_settings().TERMS_VERSION,
                "terms_accepted_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }},
        )
        user = await get_user_by_id(database, str(user.id))
        user.token_version = await bump_token_version(database, str(user.id))
    else:
        user = await create_user(
            database,
            UserCreate(
                email=email,
                password=payload.password,
                full_name=payload.full_name,
                account_type=account_type,
                org_id=str(org_id),
                org_role=role,
                email_verified=True,
                status=UserStatus.ACTIVE,
                terms_version=get_settings().TERMS_VERSION,
                terms_accepted_at=datetime.utcnow(),
            ),
            email_verified=True,
            status=UserStatus.ACTIVE,
        )
    await write_audit(database, "org.invite_accepted", actor=user, org_id=org_id, target=str(user.id))
    if user.mfa_enabled:
        return Token(mfa_required=True, mfa_token=create_mfa_token(user, "verify"))
    if await mfa_is_required(database, user):
        return Token(mfa_setup_required=True, mfa_token=create_mfa_token(user, "setup"))
    issued = await issue_tokens(database, user, response, request)
    return Token(**issued)


@router.get("/{org_id}/audit")
async def organization_audit(
    org_id: str,
    limit: int = 100,
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user=Depends(get_current_active_user),
):
    await _require_org_manager(current_user, org_id)
    limit = max(1, min(int(limit), 500))
    docs = await database.audit_log.find({"org_id": str(org_id)}).sort("created_at", -1).to_list(length=limit)
    for doc in docs:
        doc["id"] = str(doc.pop("_id"))
    return {"items": docs, "limit": limit}
