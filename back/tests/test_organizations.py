import asyncio
from datetime import datetime

import pytest
from bson import ObjectId
from fastapi import HTTPException
from starlette.responses import Response

from app.api.organizations import (
    accept_invite,
    approve_organization,
    create_invite,
    get_organization,
    reinstate_organization,
    remove_member,
    suspend_organization,
    update_settings,
)
from app.models.organization import (
    InviteAccept,
    InviteCreate,
    OrganizationApproval,
    OrganizationSettings,
    OrganizationSuspend,
    OrganizationStatus,
    OrganizationType,
)
from app.models.user import AccountType, OrgRole, PlatformRole, UserStatus
from app.services import auth as auth_service
from app.services.organizations import ACCOUNT_TYPE_BY_ORG, normalize_domains

from tests.test_auth_security import FakeDB, _user, user_doc


def test_domains_are_normalized_and_invalid_ones_rejected():
    assert normalize_domains(["@Example.EDU", "example.edu", "lab.example.edu"]) == [
        "example.edu", "lab.example.edu",
    ]
    with pytest.raises(HTTPException):
        normalize_domains(["not-a-domain"])
    assert ACCOUNT_TYPE_BY_ORG[OrganizationType.GOVT] == AccountType.GOVT_AGENCY


def test_requester_can_view_pending_application_but_outsider_cannot():
    async def run():
        db = FakeDB()
        requester_doc = user_doc("requester@example.edu")
        db.users.docs.append(requester_doc)
        requester = _user(str(requester_doc["_id"]), email=requester_doc["email"])
        org_doc = {
            "_id": ObjectId(),
            "name": "Example University",
            "type": OrganizationType.UNIVERSITY.value,
            "domains": ["example.edu"],
            "contact_email": "requester@example.edu",
            "status": OrganizationStatus.PENDING.value,
            "settings": {"require_mfa": True, "allowed_domains": ["example.edu"]},
            "requested_by": str(requester.id),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        db.organizations.docs.append(org_doc)
        result = await get_organization(str(org_doc["_id"]), database=db, current_user=requester)
        assert result.status == OrganizationStatus.PENDING
        with pytest.raises(HTTPException):
            await get_organization(
                str(org_doc["_id"]), database=db, current_user=_user("64b000000000000000000078"),
            )

    asyncio.run(run())


def test_platform_approval_assigns_first_org_admin():
    async def run():
        db = FakeDB()
        requester_doc = user_doc("requester@example.edu")
        db.users.docs.append(requester_doc)
        requester = _user(str(requester_doc["_id"]), email=requester_doc["email"])
        platform = _user("64b000000000000000000099", platform_role=PlatformRole.PLATFORM_ADMIN)
        org_doc = {
            "_id": ObjectId(),
            "name": "Example University",
            "type": OrganizationType.UNIVERSITY.value,
            "domains": ["example.edu"],
            "contact_email": "requester@example.edu",
            "status": OrganizationStatus.PENDING.value,
            "settings": {"require_mfa": True, "allowed_domains": ["example.edu"]},
            "requested_by": str(requester.id),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        db.organizations.docs.append(org_doc)

        result = await approve_organization(
            str(org_doc["_id"]), OrganizationApproval(note="verified"),
            database=db, current_user=platform,
        )
        assert result.status == OrganizationStatus.VERIFIED
        updated = db.users.docs[0]
        assert updated["org_id"] == str(org_doc["_id"])
        assert updated["org_role"] == OrgRole.ORG_ADMIN.value
        assert updated["account_type"] == AccountType.RESEARCHER.value
        assert updated["token_version"] == 1

    asyncio.run(run())


def test_invite_is_single_use_and_assigns_org_role():
    async def run():
        db = FakeDB()
        org_id = ObjectId()
        admin_doc = user_doc("admin@example.edu", org_id=str(org_id), org_role=OrgRole.ORG_ADMIN.value)
        db.users.docs.append(admin_doc)
        admin = _user(str(admin_doc["_id"]), email=admin_doc["email"], org_id=str(org_id), org_role=OrgRole.ORG_ADMIN)
        db.organizations.docs.append({
            "_id": org_id,
            "name": "Example University",
            "type": OrganizationType.UNIVERSITY.value,
            "domains": ["example.edu"],
            "contact_email": "admin@example.edu",
            "status": OrganizationStatus.VERIFIED.value,
            "settings": {"require_mfa": True, "allowed_domains": ["example.edu"]},
            "requested_by": str(admin.id),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        })

        invite = await create_invite(
            str(org_id), InviteCreate(email="new@example.edu", org_role=OrgRole.ANALYST),
            database=db, current_user=admin,
        )
        assert invite.token
        response = Response()
        issued = await accept_invite(
            InviteAccept(token=invite.token, password="long enough password", full_name="New Member", terms_accepted=True),
            request=None, response=response, database=db,
        )
        assert issued.mfa_setup_required and issued.mfa_token
        assert issued.access_token is None
        created = next(doc for doc in db.users.docs if doc["email"] == "new@example.edu")
        assert created["org_id"] == str(org_id)
        assert created["org_role"] == OrgRole.ANALYST.value
        assert created["email_verified"] is True

        with pytest.raises(HTTPException):
            await accept_invite(
                InviteAccept(token=invite.token, password="long enough password", terms_accepted=True),
                request=None, response=Response(), database=db,
            )

    asyncio.run(run())


def test_removing_member_revokes_sessions_and_keeps_last_admin():
    async def run():
        db = FakeDB()
        org_id = ObjectId()
        admin_doc = user_doc("admin@example.edu", org_id=str(org_id), org_role=OrgRole.ORG_ADMIN.value)
        member_doc = user_doc("member@example.edu", org_id=str(org_id), org_role=OrgRole.VIEWER.value)
        db.users.docs.extend([admin_doc, member_doc])
        admin = _user(str(admin_doc["_id"]), email=admin_doc["email"], org_id=str(org_id), org_role=OrgRole.ORG_ADMIN)

        await remove_member(str(org_id), str(member_doc["_id"]), database=db, current_user=admin)
        assert member_doc["org_id"] is None
        assert member_doc["org_role"] is None
        assert member_doc["token_version"] == 1

        with pytest.raises(HTTPException):
            await remove_member(str(org_id), str(admin_doc["_id"]), database=db, current_user=admin)

    asyncio.run(run())


def test_suspension_revokes_refresh_tokens_and_reinstate_keeps_them_revoked():
    async def run():
        db = FakeDB()
        org_id = ObjectId()
        member_doc = user_doc("member@example.edu", org_id=str(org_id), org_role=OrgRole.VIEWER.value)
        db.users.docs.append(member_doc)
        db.organizations.docs.append({
            "_id": org_id,
            "name": "Example University",
            "type": OrganizationType.UNIVERSITY.value,
            "domains": ["example.edu"],
            "contact_email": "member@example.edu",
            "status": OrganizationStatus.VERIFIED.value,
            "settings": {"require_mfa": True, "allowed_domains": ["example.edu"]},
            "requested_by": str(member_doc["_id"]),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        })
        member = _user(str(member_doc["_id"]), email=member_doc["email"], org_id=str(org_id), org_role=OrgRole.VIEWER)
        _, raw, _ = await auth_service.issue_access_token(db, member)
        platform = _user("64b000000000000000000099", platform_role=PlatformRole.PLATFORM_ADMIN)

        await suspend_organization(
            str(org_id), OrganizationSuspend(reason="policy"),
            database=db, current_user=platform,
        )
        assert db.refresh_tokens.docs[0]["revoked_at"] is not None
        assert db.users.docs[0]["token_version"] == 1

        await reinstate_organization(str(org_id), database=db, current_user=platform)
        assert db.refresh_tokens.docs[0]["revoked_at"] is not None
        with pytest.raises(auth_service.AuthFailure):
            await auth_service.rotate_refresh_token(db, raw)

    asyncio.run(run())


def test_pending_organization_cannot_be_reinstated_without_approval():
    async def run():
        db = FakeDB()
        org_id = ObjectId()
        db.organizations.docs.append({
            "_id": org_id,
            "name": "Example University",
            "type": OrganizationType.UNIVERSITY.value,
            "domains": ["example.edu"],
            "contact_email": "requester@example.edu",
            "status": OrganizationStatus.PENDING.value,
            "settings": {"require_mfa": True, "allowed_domains": ["example.edu"]},
            "requested_by": "64b000000000000000000001",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        })
        platform = _user("64b000000000000000000099", platform_role=PlatformRole.PLATFORM_ADMIN)
        with pytest.raises(HTTPException) as exc:
            await reinstate_organization(str(org_id), database=db, current_user=platform)
        assert exc.value.status_code == 409
        assert db.organizations.docs[0]["status"] == OrganizationStatus.PENDING.value

    asyncio.run(run())


def test_org_admin_can_update_settings_but_outsider_cannot():
    async def run():
        db = FakeDB()
        org_id = ObjectId()
        admin_doc = user_doc("admin@example.edu", org_id=str(org_id), org_role=OrgRole.ORG_ADMIN.value)
        db.users.docs.append(admin_doc)
        db.organizations.docs.append({
            "_id": org_id,
            "name": "Example University",
            "type": OrganizationType.UNIVERSITY.value,
            "domains": ["example.edu"],
            "contact_email": "admin@example.edu",
            "status": OrganizationStatus.VERIFIED.value,
            "settings": {"require_mfa": True, "allowed_domains": ["example.edu"]},
            "requested_by": str(admin_doc["_id"]),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        })
        admin = _user(str(admin_doc["_id"]), email=admin_doc["email"], org_id=str(org_id), org_role=OrgRole.ORG_ADMIN)
        result = await update_settings(
            str(org_id), OrganizationSettings(require_mfa=False, allowed_domains=["@example.edu"]),
            database=db, current_user=admin,
        )
        assert result.settings.require_mfa is False
        assert result.settings.allowed_domains == ["example.edu"]

        outsider = _user("64b000000000000000000077")
        with pytest.raises(HTTPException):
            await update_settings(
                str(org_id), OrganizationSettings(), database=db, current_user=outsider,
            )

    asyncio.run(run())


def test_org_admin_cannot_manage_another_organization():
    from fastapi.testclient import TestClient

    from app.api import auth as auth_api
    from app.main import app

    db = FakeDB()
    org_a, org_b = ObjectId(), ObjectId()
    admin_doc = user_doc(
        "admin@a.edu", org_id=str(org_a), org_role=OrgRole.ORG_ADMIN.value
    )
    db.users.docs.append(admin_doc)
    for org_id, name, email in (
        (org_a, "Org A", "admin@a.edu"),
        (org_b, "Org B", "admin@b.edu"),
    ):
        db.organizations.docs.append({
            "_id": org_id,
            "name": name,
            "type": OrganizationType.UNIVERSITY.value,
            "domains": [email.split("@")[1]],
            "contact_email": email,
            "status": OrganizationStatus.VERIFIED.value,
            "settings": {"require_mfa": False, "allowed_domains": []},
            "requested_by": str(admin_doc["_id"]),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        })
    token = auth_service.create_access_token({
        "sub": str(admin_doc["_id"]),
        "email": admin_doc["email"],
        "tv": 0,
    })
    headers = {"Authorization": f"Bearer {token}"}
    app.dependency_overrides[auth_api.get_database] = lambda: db
    try:
        client = TestClient(app)
        assert client.get(f"/api/organizations/{org_a}/members", headers=headers).status_code == 200
        assert client.get(f"/api/organizations/{org_b}/members", headers=headers).status_code == 404
        assert client.patch(
            f"/api/organizations/{org_b}/settings",
            headers=headers, json={"require_mfa": False},
        ).status_code == 404
        assert client.post(
            f"/api/organizations/{org_b}/invites",
            headers=headers, json={"email": "new@b.edu", "org_role": "viewer"},
        ).status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_student_cannot_manage_organizations():
    from fastapi.testclient import TestClient

    from app.api import auth as auth_api
    from app.main import app

    db = FakeDB()
    student_doc = user_doc("student@example.com", account_type=AccountType.STUDENT.value)
    db.users.docs.append(student_doc)
    org_id = str(ObjectId())
    token = auth_service.create_access_token({
        "sub": str(student_doc["_id"]),
        "email": student_doc["email"],
        "tv": 0,
    })
    headers = {"Authorization": f"Bearer {token}"}
    app.dependency_overrides[auth_api.get_database] = lambda: db
    try:
        client = TestClient(app)
        assert client.get(f"/api/organizations/{org_id}/members", headers=headers).status_code == 404
        assert client.post(
            f"/api/organizations/{org_id}/invites",
            headers=headers, json={"email": "new@example.com", "org_role": "viewer"},
        ).status_code == 404
        assert client.patch(
            f"/api/organizations/{org_id}/settings",
            headers=headers, json={"require_mfa": False},
        ).status_code == 404
    finally:
        app.dependency_overrides.clear()
