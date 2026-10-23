import asyncio
from datetime import datetime

import pytest
from bson import ObjectId
from fastapi import HTTPException

from app.api import auth as auth_api
from app.api import organizations as org_api
from app.models.auth import AdminUserDecision, RegisterRequest
from app.models.organization import (
    OrganizationApproval,
    OrganizationContactResend,
    OrganizationContactVerify,
    OrganizationCreate,
    OrganizationSetup,
    OrganizationStatus,
    OrganizationType,
)
from app.models.user import AccountType, OrgRole, PlatformRole, UserStatus
from app.scripts.bootstrap_admin import bootstrap_admin
from app.services import auth as auth_service

from tests.test_auth_security import FakeDB, _user, user_doc


def test_allowlisted_student_signup_verifies_and_logs_in():
    async def run():
        db = FakeDB()
        result = await auth_api.register(
            RegisterRequest(
                email="student@iit.ac.in",
                password="correct horse battery",
                full_name="Student",
                signup_type="student",
                terms_accepted=True,
            ),
            request=None,
            database=db,
        )
        assert result.verification_required
        assert result.verification_token
        stored = db.users.docs[0]
        assert stored["status"] == UserStatus.PENDING_VERIFICATION.value
        assert stored["account_type"] == AccountType.STUDENT.value
        verified = await auth_api.verify_email(
            auth_api.VerifyEmailRequest(token=result.verification_token),
            database=db,
        )
        assert verified.can_login
        assert verified.status == UserStatus.ACTIVE.value
        user, reason = await auth_service.authenticate_user_with_reason(
            db, "student@iit.ac.in", "correct horse battery"
        )
        assert user and reason == "ok"

    asyncio.run(run())


def test_non_allowlisted_signup_needs_admin_approval():
    async def run():
        db = FakeDB()
        result = await auth_api.register(
            RegisterRequest(
                email="student@example.com",
                password="correct horse battery",
                full_name="Student",
                terms_accepted=True,
            ),
            request=None,
            database=db,
        )
        verified = await auth_api.verify_email(
            auth_api.VerifyEmailRequest(token=result.verification_token),
            database=db,
        )
        assert verified.can_login is False
        assert verified.status == UserStatus.PENDING_APPROVAL.value
        user, reason = await auth_service.authenticate_user_with_reason(
            db, "student@example.com", "correct horse battery"
        )
        assert user is None and reason == "pending_approval"
        admin = _user("64b000000000000000000099", platform_role=PlatformRole.PLATFORM_ADMIN, mfa_enabled=True)
        approved = await auth_api.admin_approve_user(
            str(db.users.docs[0]["_id"]),
            AdminUserDecision(reason="verified"),
            database=db,
            current_user=admin,
        )
        assert approved["status"] == UserStatus.ACTIVE.value

    asyncio.run(run())


def test_registration_requires_terms_and_rejects_common_password():
    async def run():
        db = FakeDB()
        with pytest.raises(HTTPException) as terms:
            await auth_api.register(
                RegisterRequest(
                    email="student@iit.ac.in",
                    password="correct horse battery",
                    terms_accepted=False,
                ),
                request=None,
                database=db,
            )
        assert terms.value.status_code == 400
        with pytest.raises(HTTPException) as common:
            await auth_api.register(
                RegisterRequest(
                    email="student2@iit.ac.in",
                    password="password123",
                    terms_accepted=True,
                ),
                request=None,
                database=db,
            )
        assert common.value.status_code == 400

    asyncio.run(run())


def test_public_org_application_verifies_contact_and_sets_up_admin():
    async def run():
        db = FakeDB()
        payload = OrganizationCreate(
            name="Example University",
            type=OrganizationType.UNIVERSITY,
            domains=["example.edu"],
            contact_email="admin@example.edu",
            terms_accepted=True,
        )
        org = await org_api.apply_organization_public(payload, request=None, database=db)
        assert org.contact_verified is False
        assert org.status == OrganizationStatus.PENDING
        contact = next(
            doc for doc in db.one_time_tokens.docs if doc["kind"] == "org_contact"
        )
        raw = None
        # The raw token is only stored as a hash; issue a fresh one for the test.
        raw, _ = await auth_service.create_one_time_token_record(
            db, "public", "org_contact",
            datetime.utcnow().replace(year=datetime.utcnow().year + 1),
            metadata={"org_id": org.id, "email": "admin@example.edu"},
        )
        verified = await org_api.verify_organization_contact(
            OrganizationContactVerify(token=raw), database=db,
        )
        assert verified.contact_verified is True
        admin = _user("64b000000000000000000099", platform_role=PlatformRole.PLATFORM_ADMIN, mfa_enabled=True)
        approved = await org_api.approve_organization(
            org.id, OrganizationApproval(note="ok"), database=db, current_user=admin,
        )
        assert approved.status == OrganizationStatus.VERIFIED
        setup_doc = next(
            doc for doc in db.one_time_tokens.docs if doc["kind"] == "org_setup"
        )
        assert setup_doc["used_at"] is None
        raw_setup = None
        # Use a fresh setup token because the raw value is hashed in storage.
        raw_setup, _ = await auth_service.create_one_time_token_record(
            db, "public", "org_setup",
            datetime.utcnow().replace(year=datetime.utcnow().year + 1),
            metadata={"org_id": org.id, "email": "admin@example.edu", "org_role": OrgRole.ORG_ADMIN.value},
        )
        issued = await org_api.setup_organization_admin(
            OrganizationSetup(
                token=raw_setup,
                password="correct horse battery",
                full_name="Org Admin",
            ),
            request=None, response=None, database=db,
        )
        assert issued.mfa_setup_required
        stored = next(doc for doc in db.users.docs if doc["email"] == "admin@example.edu")
        assert stored["org_role"] == OrgRole.ORG_ADMIN.value
        assert stored["account_type"] == AccountType.RESEARCHER.value

    asyncio.run(run())


def test_org_contact_verification_can_be_resent():
    async def run():
        db = FakeDB()
        payload = OrganizationCreate(
            name="Resend University",
            type=OrganizationType.UNIVERSITY,
            domains=["resend.edu"],
            contact_email="admin@resend.edu",
            terms_accepted=True,
        )
        org = await org_api.apply_organization_public(payload, request=None, database=db)
        resent = await org_api.resend_organization_contact(
            OrganizationContactResend(contact_email="admin@resend.edu"),
            request=None,
            database=db,
        )
        assert resent.verification_token
        verified = await org_api.verify_organization_contact(
            OrganizationContactVerify(token=resent.verification_token), database=db,
        )
        assert verified.contact_verified is True
        assert verified.id == org.id

    asyncio.run(run())


def test_org_application_rejects_domain_mismatch_and_duplicate():
    async def run():
        db = FakeDB()
        with pytest.raises(HTTPException) as mismatch:
            await org_api.apply_organization_public(
                OrganizationCreate(
                    name="Bad Org",
                    type=OrganizationType.GOVT,
                    domains=["gov.in"],
                    contact_email="person@example.com",
                    terms_accepted=True,
                ),
                request=None, database=db,
            )
        assert mismatch.value.status_code == 400
        db.organizations.docs.append({
            "_id": ObjectId(), "name": "Existing", "type": "university",
            "domains": ["example.edu"], "contact_email": "a@example.edu",
            "status": OrganizationStatus.PENDING.value,
        })
        with pytest.raises(HTTPException) as duplicate:
            await org_api.apply_organization_public(
                OrganizationCreate(
                    name="Duplicate",
                    type=OrganizationType.UNIVERSITY,
                    domains=["example.edu"],
                    contact_email="b@example.edu",
                    terms_accepted=True,
                ),
                request=None, database=db,
            )
        assert duplicate.value.status_code == 409

    asyncio.run(run())


def test_bootstrap_admin_forces_password_change_and_mfa():
    async def run():
        db = FakeDB()
        user = await bootstrap_admin(db, "first-admin@example.com", "correct horse battery")
        assert user.platform_role == PlatformRole.PLATFORM_ADMIN
        assert user.must_change_password is True
        assert user.mfa_enabled is False
        assert user.status == UserStatus.ACTIVE
        assert user.email_verified is True

    asyncio.run(run())


def test_bootstrap_admin_can_change_password_then_gets_mfa_setup():
    from fastapi.testclient import TestClient
    from app.main import app

    async def seed():
        db = FakeDB()
        await bootstrap_admin(db, "bootstrap@example.com", "correct horse battery")
        return db

    db = asyncio.run(seed())
    app.dependency_overrides[auth_api.get_database] = lambda: db
    try:
        client = TestClient(app)
        login = client.post("/api/auth/login", data={
            "username": "bootstrap@example.com",
            "password": "correct horse battery",
        })
        assert login.status_code == 200
        body = login.json()
        assert body["must_change_password"] is True
        headers = {"Authorization": f"Bearer {body['access_token']}"}
        assert client.get("/api/auth/me", headers=headers).status_code == 200
        changed = client.post("/api/auth/password", headers=headers, json={
            "current_password": "correct horse battery",
            "new_password": "new correct horse battery",
        })
        assert changed.status_code == 200
        relogin = client.post("/api/auth/login", data={
            "username": "bootstrap@example.com",
            "password": "new correct horse battery",
        })
        assert relogin.status_code == 200
        assert relogin.json()["mfa_setup_required"] is True
    finally:
        app.dependency_overrides.clear()
