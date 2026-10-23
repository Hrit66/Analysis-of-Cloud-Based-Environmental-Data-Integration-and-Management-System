import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from bson import ObjectId
from fastapi import HTTPException

from app.api import admin as admin_api
from app.models.admin import AdminDatasetAction, AdminSettingsUpdate, AdminUserAction
from app.models.user import AccountType, PlatformRole, UserStatus
from app.services import auth as auth_service
from app.services.quotas import effective_quota
from app.services.system_settings import get_system_settings
from tests.test_auth_security import Collection, Cursor, FakeDB, _user, apply_update, matches, user_doc


class AdminCursor(Cursor):
    def sort(self, key, direction=1):
        self.docs = sorted(
            self.docs,
            key=lambda doc: doc.get(key) or datetime.min,
            reverse=direction < 0,
        )
        return self


class AdminCollection(Collection):
    def find(self, query, projection=None):
        return AdminCursor([doc for doc in self.docs if matches(doc, query)])

    async def update_one(self, query, update, upsert=False, **kwargs):
        for doc in self.docs:
            if matches(doc, query):
                apply_update(doc, update)
                return SimpleNamespace(matched_count=1, modified_count=1)
        if upsert:
            doc = dict(query)
            apply_update(doc, update)
            self.docs.append(doc)
            return SimpleNamespace(matched_count=1, modified_count=1, upserted_id=doc.get("_id"))
        return SimpleNamespace(matched_count=0, modified_count=0)

    async def delete_one(self, query):
        for index, doc in enumerate(self.docs):
            if matches(doc, query):
                self.docs.pop(index)
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)

    async def delete_many(self, query):
        before = len(self.docs)
        self.docs[:] = [doc for doc in self.docs if not matches(doc, query)]
        return SimpleNamespace(deleted_count=before - len(self.docs))


class AdminFakeDB(FakeDB):
    def __init__(self):
        super().__init__()
        for name in (
            "users", "organizations", "refresh_tokens", "one_time_tokens",
            "audit_log", "datasets", "system_settings", "system_status", "notifications",
            "notification_preferences", "air_quality",
            "water_quality", "anomalies", "forecasts",
        ):
            setattr(self, name, AdminCollection())

    async def command(self, name):
        return {"ok": 1}


async def admin_user(db, email="admin@example.com"):
    doc = user_doc(
        email,
        platform_role=PlatformRole.PLATFORM_ADMIN.value,
        mfa_enabled=True,
    )
    db.users.docs.append(doc)
    return await auth_service.get_user_by_id(db, str(doc["_id"]))


def test_admin_user_update_bumps_tokens_and_audits():
    async def run():
        db = AdminFakeDB()
        actor = await admin_user(db)
        target = user_doc("target@example.com")
        db.users.docs.append(target)

        row = await admin_api.update_user(
            str(target["_id"]),
            AdminUserAction(reason="Policy violation", status=UserStatus.SUSPENDED),
            request=None,
            database=db,
            current_user=actor,
        )

        stored = next(doc for doc in db.users.docs if doc["_id"] == target["_id"])
        assert row["status"] == UserStatus.SUSPENDED.value
        assert stored["status"] == UserStatus.SUSPENDED.value
        assert stored["is_active"] is False
        assert stored["token_version"] == 1
        assert any(
            doc["action"] == "admin.user_updated"
            and doc["target"] == str(target["_id"])
            for doc in db.audit_log.docs
        )

    asyncio.run(run())


def test_admin_cannot_modify_self_or_remove_last_admin():
    async def run():
        db = AdminFakeDB()
        actor = await admin_user(db)

        with pytest.raises(HTTPException) as self_edit:
            await admin_api.update_user(
                str(actor.id),
                AdminUserAction(reason="Self change", status=UserStatus.SUSPENDED),
                request=None,
                database=db,
                current_user=actor,
            )
        assert self_edit.value.status_code == 400

        db.users.docs[:] = [doc for doc in db.users.docs if doc["_id"] != actor.id]
        last = user_doc(
            "last-admin@example.com",
            platform_role=PlatformRole.PLATFORM_ADMIN.value,
            mfa_enabled=True,
        )
        db.users.docs.append(last)
        with pytest.raises(HTTPException) as demote:
            await admin_api.update_user(
                str(last["_id"]),
                AdminUserAction(reason="Demote last admin", platform_role=PlatformRole.USER),
                request=None,
                database=db,
                current_user=actor,
            )
        assert demote.value.status_code == 400
        assert "last active platform admin" in demote.value.detail

        db.users.docs.append(user_doc(
            "second-admin@example.com",
            platform_role=PlatformRole.PLATFORM_ADMIN.value,
            mfa_enabled=True,
        ))
        row = await admin_api.update_user(
            str(last["_id"]),
            AdminUserAction(reason="Second admin exists", platform_role=PlatformRole.USER),
            request=None,
            database=db,
            current_user=actor,
        )
        assert row["platform_role"] == PlatformRole.USER.value

    asyncio.run(run())


def test_admin_promotion_requires_verified_active_mfa_account():
    async def run():
        db = AdminFakeDB()
        actor = await admin_user(db)
        target = user_doc("promote@example.com", mfa_enabled=False)
        db.users.docs.append(target)

        with pytest.raises(HTTPException) as no_mfa:
            await admin_api.update_user(
                str(target["_id"]),
                AdminUserAction(reason="Promote to admin", platform_role=PlatformRole.PLATFORM_ADMIN),
                request=None,
                database=db,
                current_user=actor,
            )
        assert no_mfa.value.status_code == 400
        assert "MFA" in no_mfa.value.detail

        target["mfa_enabled"] = True
        row = await admin_api.update_user(
            str(target["_id"]),
            AdminUserAction(reason="Promote to admin", platform_role=PlatformRole.PLATFORM_ADMIN),
            request=None,
            database=db,
            current_user=actor,
        )
        stored = next(doc for doc in db.users.docs if doc["_id"] == target["_id"])
        assert row["platform_role"] == PlatformRole.PLATFORM_ADMIN.value
        assert stored["is_superuser"] is True

    asyncio.run(run())


def test_admin_dataset_publish_and_delete_audits_and_cascades(monkeypatch):
    async def run():
        monkeypatch.setattr(admin_api, "purge_forecast_models", lambda _dataset_id: None)
        monkeypatch.setattr(admin_api, "purge_anomaly_models", lambda _dataset_id: None)
        db = AdminFakeDB()
        actor = await admin_user(db)
        dataset_id = ObjectId()
        db.datasets.docs.append({
            "_id": dataset_id,
            "filename": "sample.csv",
            "owner_id": str(actor.id),
            "visibility": "private",
            "file_size_bytes": 1024,
            "row_count": 10,
            "created_at": datetime.utcnow(),
            "publish_requested_at": datetime.utcnow(),
            "publish_request_reason": "Test publish request",
        })
        db.air_quality.docs.append({"dataset_id": str(dataset_id)})

        await admin_api.update_dataset(
            str(dataset_id),
            AdminDatasetAction(action="publish", reason="Open reference data"),
            request=None,
            database=db,
            current_user=actor,
        )
        assert db.datasets.docs[0]["visibility"] == "reference"

        await admin_api.delete_dataset(
            str(dataset_id),
            request=None,
            reason="Retracted by owner request",
            database=db,
            current_user=actor,
        )
        assert db.datasets.docs == []
        assert db.air_quality.docs == []
        actions = [doc["action"] for doc in db.audit_log.docs]
        assert "admin.dataset_published" in actions
        assert "admin.dataset_deleted" in actions

    asyncio.run(run())


def test_admin_settings_persist_and_apply_quota_override():
    async def run():
        db = AdminFakeDB()
        db.system_settings.docs.append({"_id": "global"})
        actor = await admin_user(db)

        await admin_api.update_settings_admin(
            AdminSettingsUpdate(
                registration_mode="invite_only",
                allowed_domains=["Example.EDU"],
                mfa_required={"student": True},
                quota_overrides={"student": {"datasets": 3, "storage_bytes": 4096}},
                reason="Tighten student access",
            ),
            request=None,
            database=db,
            current_user=actor,
        )

        settings = await get_system_settings(db)
        assert settings["registration_mode"] == "invite_only"
        assert settings["allowed_domains"] == ["example.edu"]
        assert settings["mfa_required"]["student"] is True
        assert settings["updated_by"] == str(actor.id)

        student = _user("64b000000000000000000123", account_type=AccountType.STUDENT)
        quota = await effective_quota(db, student)
        assert quota.datasets == 3
        assert quota.storage_bytes == 4096
        assert any(doc["action"] == "admin.settings_updated" for doc in db.audit_log.docs)

    asyncio.run(run())


def test_admin_can_set_and_clear_per_user_quota_override():
    async def run():
        db = AdminFakeDB()
        actor = await admin_user(db)
        target = user_doc("quota@example.com", account_type=AccountType.STUDENT.value)
        db.users.docs.append(target)

        row = await admin_api.update_user(
            str(target["_id"]),
            AdminUserAction(
                reason="Custom research quota",
                quota_overrides={"datasets": 2, "storage_bytes": 8192},
            ),
            request=None,
            database=db,
            current_user=actor,
        )
        assert row["quota_overrides"] == {"datasets": 2, "storage_bytes": 8192}
        updated = await auth_service.get_user_by_id(db, str(target["_id"]))
        quota = await effective_quota(db, updated)
        assert quota.datasets == 2
        assert quota.storage_bytes == 8192

        row = await admin_api.update_user(
            str(target["_id"]),
            AdminUserAction(reason="Return to account default", quota_overrides={}),
            request=None,
            database=db,
            current_user=actor,
        )
        assert row["quota_overrides"] == {}
        updated = await auth_service.get_user_by_id(db, str(target["_id"]))
        quota = await effective_quota(db, updated)
        assert quota.datasets == 10
        assert quota.storage_bytes == 25 * 1024 * 1024

    asyncio.run(run())


def test_admin_audit_filters_by_event_and_result():
    async def run():
        db = AdminFakeDB()
        actor = await admin_user(db)
        await auth_service.write_audit(
            db, "auth.login_failed", actor=actor, target="target@example.com", result="failure",
        )
        await auth_service.write_audit(
            db, "admin.user_updated", actor=actor, target="other@example.com",
        )

        result = await admin_api.list_audit(
            event="auth.login_failed",
            result="failure",
            database=db,
            current_user=actor,
        )
        assert result["total"] == 1
        assert result["items"][0]["action"] == "auth.login_failed"
        assert result["items"][0]["result"] == "failure"

        all_items = await admin_api.list_audit(database=db, current_user=actor)
        assert all_items["total"] == 2
        assert all_items["items"][0]["result"] == "success"

    asyncio.run(run())


def test_admin_audit_resolves_targets_and_captures_forwarded_ip():
    async def run():
        db = AdminFakeDB()
        actor = await admin_user(db)
        target = user_doc("target@example.com")
        dataset = {"_id": ObjectId(), "filename": "air_quality.csv", "owner_id": str(target["_id"])}
        org = {"_id": ObjectId(), "name": "Example University"}
        db.users.docs.append(target)
        db.datasets.docs.append(dataset)
        db.organizations.docs.append(org)

        request = SimpleNamespace(
            headers={
                "x-forwarded-for": "203.0.113.7, 10.0.0.1",
                "user-agent": "pytest-agent",
            },
            client=SimpleNamespace(host="127.0.0.1"),
        )

        await auth_service.write_audit(
            db, "admin.user_updated", actor=actor, target=str(target["_id"]), request=request,
        )
        await auth_service.write_audit(
            db, "admin.dataset_deleted", actor=actor, target=str(dataset["_id"]), request=request,
        )
        await auth_service.write_audit(
            db, "org.approved", actor=actor, target=str(org["_id"]), request=request,
        )

        result = await admin_api.list_audit(database=db, current_user=actor)
        by_action = {item["action"]: item for item in result["items"]}

        user_item = by_action["admin.user_updated"]
        assert user_item["target_label"] == "target@example.com"
        assert user_item["target_type"] == "user"
        assert user_item["ip"] == "203.0.113.7"
        assert user_item["user_agent"] == "pytest-agent"

        assert by_action["admin.dataset_deleted"]["target_label"] == "air_quality.csv"
        assert by_action["admin.dataset_deleted"]["target_type"] == "dataset"
        assert by_action["org.approved"]["target_label"] == "Example University"
        assert by_action["org.approved"]["target_type"] == "organization"

    asyncio.run(run())


def test_admin_force_logout_and_unlock():
    async def run():
        db = AdminFakeDB()
        actor = await admin_user(db)
        target = user_doc(
            "locked@example.com",
            failed_login_attempts=5,
            locked_until=datetime.utcnow() + timedelta(minutes=10),
        )
        db.users.docs.append(target)
        db.refresh_tokens.docs.append({
            "user_id": str(target["_id"]),
            "revoked_at": None,
        })

        await admin_api.force_logout(
            str(target["_id"]), request=None, database=db, current_user=actor,
        )
        stored = next(doc for doc in db.users.docs if doc["_id"] == target["_id"])
        assert stored["token_version"] == 1
        assert db.refresh_tokens.docs[0]["revoked_at"] is not None

        await admin_api.unlock_user(
            str(target["_id"]), request=None, database=db, current_user=actor,
        )
        assert stored["failed_login_attempts"] == 0
        assert stored["locked_until"] is None
        actions = [doc["action"] for doc in db.audit_log.docs]
        assert "admin.force_logout" in actions
        assert "admin.user_unlocked" in actions

    asyncio.run(run())


def test_admin_overview_reports_counts_and_security_alerts():
    async def run():
        db = AdminFakeDB()
        actor = await admin_user(db)
        db.users.docs.append(user_doc("pending@example.com", status=UserStatus.PENDING_APPROVAL.value))
        db.organizations.docs.append({"_id": ObjectId(), "name": "Org", "status": "pending"})
        db.datasets.docs.append({"_id": ObjectId(), "status": "failed", "file_size_bytes": 10})
        await auth_service.write_audit(db, "auth.login_failed", actor=actor, result="failure")

        result = await admin_api.overview(database=db, current_user=actor)
        assert result["database"]["status"] == "ok"
        assert result["pending_users"] == 1
        assert result["pending_organizations"] == 1
        assert result["failed_jobs"] == 1
        assert result["failed_logins_24h"] == 1
        assert result["admins_without_mfa"] == []
        assert result["alerts"]

    asyncio.run(run())
