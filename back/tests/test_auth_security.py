import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pyotp
import pytest
from bson import ObjectId
from fastapi import HTTPException
from passlib.context import CryptContext

from app.models.organization import OrganizationStatus
from app.models.user import AccountType, OrgRole, PlatformRole, UserInDB, UserStatus
from app.services import auth as auth_service
from app.services.authz import dataset_readable, dataset_writable, readable_query, require_dataset_access
from app.services.quotas import quota_for


def matches(doc, query):
    for key, value in query.items():
        if key == "$or":
            if not any(matches(doc, clause) for clause in value):
                return False
        elif key == "$and":
            if not all(matches(doc, clause) for clause in value):
                return False
        elif key == "$gt":
            return False
        elif isinstance(value, dict):
            if "$in" in value and doc.get(key) not in value["$in"]:
                return False
            if "$ne" in value and doc.get(key) == value["$ne"]:
                return False
            if "$exists" in value and (key in doc) != value["$exists"]:
                return False
            if "$gt" in value and not (doc.get(key) is not None and doc.get(key) > value["$gt"]):
                return False
            if "$lt" in value and not (doc.get(key) is not None and doc.get(key) < value["$lt"]):
                return False
        elif doc.get(key) != value:
            return False
    return True


def apply_update(doc, update):
    for key, value in update.get("$set", {}).items():
        doc[key] = value
    for key, value in update.get("$inc", {}).items():
        doc[key] = doc.get(key, 0) + value


class Collection:
    def __init__(self):
        self.docs = []

    async def insert_one(self, doc):
        doc = dict(doc)
        doc.setdefault("_id", ObjectId())
        self.docs.append(doc)
        return SimpleNamespace(inserted_id=doc["_id"])

    async def find_one(self, query, projection=None):
        for doc in self.docs:
            if matches(doc, query):
                return dict(doc)
        return None

    async def find_one_and_update(self, query, update, return_document=True, **kwargs):
        for doc in self.docs:
            if matches(doc, query):
                apply_update(doc, update)
                return dict(doc)
        return None

    async def update_one(self, query, update, upsert=False):
        for doc in self.docs:
            if matches(doc, query):
                apply_update(doc, update)
                return SimpleNamespace(matched_count=1, modified_count=1)
        if upsert:
            doc = dict(query)
            apply_update(doc, update)
            doc.setdefault("_id", ObjectId())
            self.docs.append(doc)
            return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=doc["_id"])
        return SimpleNamespace(matched_count=0, modified_count=0)

    async def update_many(self, query, update):
        changed = 0
        for doc in self.docs:
            if matches(doc, query):
                apply_update(doc, update)
                changed += 1
        return SimpleNamespace(matched_count=changed, modified_count=changed)

    async def delete_one(self, query):
        for index, doc in enumerate(self.docs):
            if matches(doc, query):
                self.docs.pop(index)
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)

    def find(self, query):
        return Cursor([doc for doc in self.docs if matches(doc, query)])

    async def count_documents(self, query):
        return sum(1 for doc in self.docs if matches(doc, query))

    async def aggregate(self, pipeline):
        # Simple implementation for storage sum pipeline:
        # [{"$match": {"status": {"$ne": "failed"}}},
        #  {"$group": {"_id": None, "total": {"$sum": {"$ifNull": ["$file_size_bytes", 0]}}}}]
        match_stage = None
        group_stage = None
        for stage in pipeline:
            if "$match" in stage:
                match_stage = stage["$match"]
            if "$group" in stage:
                group_stage = stage["$group"]

        filtered = self.docs
        if match_stage:
            status_ne = match_stage.get("status", {}).get("$ne")
            if status_ne:
                filtered = [d for d in filtered if d.get("status") != status_ne]

        total = 0
        for doc in filtered:
            total += doc.get("file_size_bytes") or 0

        class AggCursor:
            async def to_list(self, length=None):
                return [{"_id": None, "total": total}]

        return AggCursor()


class Cursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, key_or_list, direction=None):
        keys = (
            [(key_or_list, direction if direction is not None else 1)]
            if isinstance(key_or_list, str)
            else list(key_or_list)
        )
        for key, order in reversed(keys):
            self.docs.sort(
                key=lambda doc: (doc.get(key) is None, doc.get(key)),
                reverse=(order == -1),
            )
        return self

    def skip(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    async def to_list(self, length=None):
        docs = self.docs if length is None else self.docs[:length]
        return [dict(doc) for doc in docs]


class FakeDB:
    def __init__(self):
        self.users = Collection()
        self.organizations = Collection()
        self.refresh_tokens = Collection()
        self.one_time_tokens = Collection()
        self.audit_log = Collection()
        self.datasets = Collection()
        self.notifications = Collection()
        self.notification_preferences = Collection()


def user_doc(email="user@example.com", password="correct horse battery", **extra):
    return {
        "_id": ObjectId(),
        "email": email,
        "full_name": "Test User",
        "hashed_password": auth_service.get_password_hash(password),
        "is_active": True,
        "is_superuser": False,
        "account_type": AccountType.RESEARCHER.value,
        "platform_role": PlatformRole.USER.value,
        "status": UserStatus.ACTIVE.value,
        "email_verified": True,
        "mfa_enabled": False,
        "token_version": 0,
        "failed_login_attempts": 0,
        "locked_until": None,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        **extra,
    }


def test_argon2_hashing_and_legacy_bcrypt_verification():
    hashed = auth_service.get_password_hash("correct horse battery")
    assert hashed.startswith("$argon2")
    assert auth_service.verify_password("correct horse battery", hashed)
    assert not auth_service.verify_password("wrong password", hashed)
    legacy = CryptContext(schemes=["bcrypt"]).hash("legacy password")
    assert auth_service.verify_password("legacy password", legacy)
    assert auth_service.password_needs_rehash(legacy)


def test_login_upgrades_legacy_hash_and_resets_lockout():
    async def run():
        db = FakeDB()
        legacy = CryptContext(schemes=["bcrypt"]).hash("correct horse battery")
        doc = user_doc(hashed_password=legacy)
        db.users.docs.append(doc)
        user, reason = await auth_service.authenticate_user_with_reason(
            db, doc["email"], "correct horse battery"
        )
        assert reason == "ok" and user
        assert db.users.docs[0]["hashed_password"].startswith("$argon2")
        assert db.users.docs[0]["failed_login_attempts"] == 0

    asyncio.run(run())


def test_failed_logins_lock_the_account():
    async def run():
        db = FakeDB()
        doc = user_doc()
        db.users.docs.append(doc)
        for _ in range(4):
            _, reason = await auth_service.authenticate_user_with_reason(
                db, doc["email"], "wrong password"
            )
            assert reason == "invalid"
        _, reason = await auth_service.authenticate_user_with_reason(
            db, doc["email"], "wrong password"
        )
        assert reason == "locked"
        assert db.users.docs[0]["locked_until"] > datetime.utcnow()
        _, reason = await auth_service.authenticate_user_with_reason(
            db, doc["email"], "correct horse battery"
        )
        assert reason == "locked"

    asyncio.run(run())


def test_access_token_rejects_mfa_token_and_stale_version():
    async def run():
        db = FakeDB()
        doc = user_doc()
        db.users.docs.append(doc)
        user = UserInDB(**auth_service._normalize_user_doc(doc))
        access = auth_service.create_access_token(
            {"sub": str(user.id), "email": user.email, "tv": 0}
        )
        assert await auth_service.get_current_user(access, db)
        mfa = auth_service.create_mfa_token(user, "verify")
        assert await auth_service.get_current_user(mfa, db) is None
        stale = auth_service.create_access_token(
            {"sub": str(user.id), "email": user.email, "tv": 99}
        )
        assert await auth_service.get_current_user(stale, db) is None

    asyncio.run(run())


def test_refresh_token_race_is_rejected_without_revoking_family():
    async def run():
        db = FakeDB()
        doc = user_doc()
        db.users.docs.append(doc)
        user = UserInDB(**auth_service._normalize_user_doc(doc))
        _, raw, _ = await auth_service.issue_access_token(db, user)
        user, new_raw, _, access = await auth_service.rotate_refresh_token(db, raw)
        assert new_raw != raw and access
        with pytest.raises(auth_service.AuthFailure) as race:
            await auth_service.rotate_refresh_token(db, raw)
        assert race.value.clear_cookie is False
        live = [row for row in db.refresh_tokens.docs if not row["revoked_at"]]
        assert len(live) == 1
        assert any(
            row["action"] == "auth.refresh_race"
            for row in db.audit_log.docs
        )
        assert not any(
            row["action"] == "auth.refresh_reuse"
            for row in db.audit_log.docs
        )
        _, rotated_again, _, _ = await auth_service.rotate_refresh_token(db, new_raw)
        assert rotated_again

    asyncio.run(run())


def test_late_refresh_replay_revokes_the_family():
    async def run():
        db = FakeDB()
        doc = user_doc()
        db.users.docs.append(doc)
        user = UserInDB(**auth_service._normalize_user_doc(doc))
        _, raw, _ = await auth_service.issue_access_token(db, user)
        await auth_service.rotate_refresh_token(db, raw)
        old = next(row for row in db.refresh_tokens.docs if row["token_hash"] == auth_service.hash_token(raw))
        old["rotated_at"] = datetime.utcnow() - timedelta(minutes=2)
        with pytest.raises(auth_service.AuthFailure):
            await auth_service.rotate_refresh_token(db, raw)
        assert all(row["revoked_at"] for row in db.refresh_tokens.docs)
        assert any(row["action"] == "auth.refresh_reuse" for row in db.audit_log.docs)

    asyncio.run(run())


def test_mfa_is_required_for_org_members_and_totp_works():
    async def run():
        db = FakeDB()
        org_id = ObjectId()
        db.organizations.docs.append({
            "_id": org_id,
            "status": OrganizationStatus.VERIFIED.value,
            "settings": {"require_mfa": True},
        })
        doc = user_doc(org_id=str(org_id), org_role=OrgRole.VIEWER.value)
        db.users.docs.append(doc)
        user = UserInDB(**auth_service._normalize_user_doc(doc))
        assert await auth_service.mfa_is_required(db, user)
        secret = pyotp.random_base32()
        assert auth_service.verify_totp(secret, pyotp.TOTP(secret).now())
        assert not auth_service.verify_totp(secret, "000000")

    asyncio.run(run())


def test_mfa_policy_blocks_access_and_refresh_until_enabled():
    async def run():
        db = FakeDB()
        org_id = ObjectId()
        db.organizations.docs.append({
            "_id": org_id,
            "status": OrganizationStatus.VERIFIED.value,
            "settings": {"require_mfa": True},
        })
        doc = user_doc(org_id=str(org_id), org_role=OrgRole.VIEWER.value)
        db.users.docs.append(doc)
        user = UserInDB(**auth_service._normalize_user_doc(doc))
        access = auth_service.create_access_token(
            {"sub": str(user.id), "email": user.email, "tv": 0}
        )
        assert await auth_service.get_current_user(access, db) is None
        _, raw, _ = await auth_service.issue_access_token(db, user)
        with pytest.raises(auth_service.AuthFailure):
            await auth_service.rotate_refresh_token(db, raw)
        doc["mfa_enabled"] = True
        assert await auth_service.get_current_user(access, db)

    asyncio.run(run())


def _user(user_id, **extra):
    values = {
        "id": ObjectId(user_id),
        "email": f"{user_id}@example.com",
        "is_active": True,
        "is_superuser": False,
        "account_type": AccountType.RESEARCHER,
        "platform_role": PlatformRole.USER,
        "status": UserStatus.ACTIVE,
        "email_verified": True,
        "mfa_enabled": False,
        "token_version": 0,
        "hashed_password": "x",
        "created_at": datetime.utcnow(),
    }
    values.update(extra)
    return UserInDB(**values)


def test_dataset_read_write_matrix_is_private_by_default():
    owner = _user("64b000000000000000000001")
    other = _user("64b000000000000000000002", org_id="64b000000000000000000010")
    analyst = _user(
        "64b000000000000000000003", org_id="64b000000000000000000010",
        org_role=OrgRole.ANALYST,
    )
    org_admin = _user(
        "64b000000000000000000004", org_id="64b000000000000000000010",
        org_role=OrgRole.ORG_ADMIN,
    )
    platform_admin = _user(
        "64b000000000000000000005", platform_role=PlatformRole.PLATFORM_ADMIN,
    )
    private = {"_id": ObjectId(), "owner_id": str(owner.id), "visibility": "private"}
    shared = {**private, "shared_with_users": [str(other.id)]}
    org_doc = {**private, "visibility": "org", "org_id": str(other.org_id)}
    reference = {"_id": ObjectId(), "visibility": "reference"}

    assert dataset_readable(private, owner)
    assert not dataset_readable(private, other)
    assert not dataset_readable(private, platform_admin)
    assert dataset_readable(shared, other)
    assert dataset_readable(org_doc, analyst)
    other_org_analyst = _user(
        "64b000000000000000000007", org_id="64b000000000000000000011",
        org_role=OrgRole.ANALYST,
    )
    assert not dataset_readable(org_doc, other_org_analyst)
    assert not dataset_readable(org_doc, _user("64b000000000000000000006"))
    assert dataset_readable(reference, other)
    assert dataset_writable(private, owner)
    assert dataset_writable(org_doc, org_admin)
    assert not dataset_writable(org_doc, analyst)
    assert not dataset_writable(org_doc, other_org_analyst)


def test_readable_query_scopes_org_and_shared_datasets():
    user = _user(
        "64b000000000000000000003", org_id="64b000000000000000000010",
        org_role=OrgRole.ANALYST,
    )
    query = readable_query(user)
    assert query["$or"]
    assert {"visibility": "org", "org_id": str(user.org_id)} in query["$or"]
    assert {"shared_with_users": str(user.id)} in query["$or"]


def test_require_dataset_access_returns_404_instead_of_403():
    async def run():
        db = FakeDB()
        doc = user_doc(owner_id="someone-else", visibility="private")
        db.datasets.docs.append(doc)
        with pytest.raises(HTTPException) as exc:
            await require_dataset_access(db, str(doc["_id"]), user_doc())
        assert exc.value.status_code == 404

    asyncio.run(run())


def test_pending_or_suspended_org_invalidates_existing_access():
    async def run():
        db = FakeDB()
        org_id = ObjectId()
        org_doc = {
            "_id": org_id,
            "status": OrganizationStatus.VERIFIED.value,
            "settings": {"require_mfa": False},
        }
        db.organizations.docs.append(org_doc)
        doc = user_doc(org_id=str(org_id), org_role=OrgRole.VIEWER.value)
        db.users.docs.append(doc)
        user = UserInDB(**auth_service._normalize_user_doc(doc))
        access = auth_service.create_access_token(
            {"sub": str(user.id), "email": user.email, "tv": 0}
        )
        assert await auth_service.get_current_user(access, db)
        org_doc["status"] = OrganizationStatus.PENDING.value
        assert await auth_service.get_current_user(access, db) is None
        org_doc["status"] = OrganizationStatus.SUSPENDED.value
        assert await auth_service.get_current_user(access, db) is None
        org_doc["status"] = OrganizationStatus.VERIFIED.value
        assert await auth_service.get_current_user(access, db)

    asyncio.run(run())


def test_registration_ignores_client_supplied_roles():
    from fastapi.testclient import TestClient

    from app.api import auth as auth_api
    from app.main import app

    db = FakeDB()
    app.dependency_overrides[auth_api.get_database] = lambda: db
    try:
        response = TestClient(app).post("/api/auth/register", json={
            "email": "self-elevate@example.com",
            "password": "long enough password",
            "full_name": "Self Elevate",
            "terms_accepted": True,
            "account_type": "govt_agency",
            "platform_role": "platform_admin",
            "org_role": "org_admin",
            "is_superuser": True,
        })
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 201
    stored = db.users.docs[0]
    assert stored["account_type"] == AccountType.STUDENT.value
    assert stored["platform_role"] == PlatformRole.USER.value
    assert stored["org_role"] is None
    assert stored["is_superuser"] is False


def test_invalid_mfa_challenge_returns_401_not_500():
    from fastapi.testclient import TestClient
    from app.main import app

    response = TestClient(app).post(
        "/api/auth/mfa/verify",
        json={"mfa_token": "not-a-token", "code": "123456"},
    )
    assert response.status_code == 401

def test_authenticated_mfa_setup_and_enable():
    from fastapi.testclient import TestClient
    from app.api import auth as auth_api
    from app.main import app

    db = FakeDB()
    doc = user_doc("mfa@example.com")
    db.users.docs.append(doc)
    token = auth_service.create_access_token({
        "sub": str(doc["_id"]), "email": doc["email"], "tv": 0,
    })
    headers = {"Authorization": f"Bearer {token}"}
    app.dependency_overrides[auth_api.get_database] = lambda: db
    try:
        client = TestClient(app)
        assert client.post("/api/auth/mfa/setup-authenticated").status_code == 401
        setup = client.post("/api/auth/mfa/setup-authenticated", headers=headers)
        assert setup.status_code == 200
        secret = setup.json()["secret"]
        assert db.users.docs[0]["pending_mfa_secret"] == secret
        enabled = client.post(
            "/api/auth/mfa/enable-authenticated",
            headers=headers,
            json={"code": pyotp.TOTP(secret).now()},
        )
        assert enabled.status_code == 200
        assert db.users.docs[0]["mfa_enabled"] is True
        assert db.users.docs[0]["mfa_secret"] == secret
        assert db.users.docs[0]["token_version"] == 1
    finally:
        app.dependency_overrides.clear()


def test_quota_is_smaller_for_students():
    student = _user("64b000000000000000000001", account_type=AccountType.STUDENT)
    researcher = _user("64b000000000000000000002", account_type=AccountType.RESEARCHER)
    assert quota_for(student).datasets < quota_for(researcher).datasets
    assert quota_for(student).api_keys == 0


