import asyncio

import pytest
from bson import ObjectId
from fastapi import HTTPException

from app.api import notifications as notif_api
from app.models.user import OrgRole, PlatformRole, UserStatus
from app.services import notifications as notif
from tests.test_auth_security import FakeDB, _user, user_doc


def test_dedupe_creates_exactly_one_notification():
    async def run():
        db = FakeDB()
        uid = str(ObjectId())
        first = await notif.notify(
            db, [uid], "upload_completed", "Upload done", "Body", dedupe_key="dataset-1"
        )
        second = await notif.notify(
            db, [uid], "upload_completed", "Upload done", "Body", dedupe_key="dataset-1"
        )
        assert len(first) == 1
        assert second == []
        assert len(db.notifications.docs) == 1
        assert db.notifications.docs[0]["user_id"] == uid

    asyncio.run(run())


def test_notification_links_must_be_internal_paths():
    async def run():
        db = FakeDB()
        uid = str(ObjectId())

        await notif.notify(db, [uid], "upload_completed", "One", "Body", link="https://evil.example")
        await notif.notify(
            db, [uid], "upload_completed", "Two", "Body", link="//evil.example", dedupe_key="two"
        )
        await notif.notify(
            db, [uid], "upload_completed", "Three", "Body", link="/datasets", dedupe_key="three"
        )

        assert [doc["link"] for doc in db.notifications.docs] == ["", "", "/datasets"]

    asyncio.run(run())


def test_preferences_control_in_app_and_email(monkeypatch):
    sent = []

    async def fake_send_email(to, subject, body):
        sent.append((to, subject))
        return True

    monkeypatch.setattr(notif, "send_email", fake_send_email)

    async def run():
        db = FakeDB()
        uid = ObjectId()
        db.users.docs.append(user_doc("user@example.com", _id=uid))

        await notif.update_preferences(
            db, str(uid), {"upload_failed": {"in_app": False, "email": False}}
        )
        created = await notif.notify(
            db, [str(uid)], "upload_failed", "Upload failed", "Body"
        )
        assert created == []
        assert db.notifications.docs == []
        assert sent == []

        await notif.update_preferences(
            db, str(uid), {"upload_failed": {"in_app": True, "email": False}}
        )
        created = await notif.notify(
            db, [str(uid)], "upload_failed", "Upload failed", "Body"
        )
        assert len(created) == 1
        assert len(db.notifications.docs) == 1
        assert sent == []

        await notif.update_preferences(
            db, str(uid), {"upload_failed": {"in_app": False, "email": True}}
        )
        created = await notif.notify(
            db, [str(uid)], "upload_failed", "Upload failed again", "Body"
        )
        assert created == []
        assert len(db.notifications.docs) == 1
        assert sent == [("user@example.com", "Upload failed again")]

    asyncio.run(run())


def test_preferences_defaults_are_not_shared_between_users():
    async def run():
        db = FakeDB()
        first = str(ObjectId())
        second = str(ObjectId())

        await notif.update_preferences(
            db, first, {"upload_completed": {"in_app": False, "email": False}}
        )

        first_prefs = await notif.get_preferences(db, first)
        second_prefs = await notif.get_preferences(db, second)
        assert first_prefs["upload_completed"]["in_app"] is False
        assert second_prefs["upload_completed"]["in_app"] is True
        assert notif.DEFAULT_PREFERENCES["upload_completed"]["in_app"] is True
        assert notif.DEFAULT_PREFERENCES["upload_completed"]["email"] is False

    asyncio.run(run())


def test_unread_count_read_and_delete_are_user_scoped():
    async def run():
        db = FakeDB()
        owner_id = ObjectId()
        other_id = ObjectId()
        owner = _user(str(owner_id))
        other = _user(str(other_id))

        created = await notif.notify(
            db, [str(owner_id)], "upload_completed", "Done", "Body"
        )
        notification_id = created[0]

        assert await notif.get_unread_count(db, str(owner_id)) == 1
        assert await notif.get_unread_count(db, str(other_id)) == 0

        with pytest.raises(HTTPException) as wrong_user:
            await notif_api.mark_read(
                notification_id, database=db, current_user=other
            )
        assert wrong_user.value.status_code == 404
        assert await notif.get_unread_count(db, str(owner_id)) == 1

        response = await notif_api.mark_read(
            notification_id, database=db, current_user=owner
        )
        assert response["message"] == "Marked as read"
        assert await notif.get_unread_count(db, str(owner_id)) == 0

        with pytest.raises(HTTPException) as replay:
            await notif_api.mark_read(
                notification_id, database=db, current_user=owner
            )
        assert replay.value.status_code == 404

        with pytest.raises(HTTPException) as wrong_delete:
            await notif_api.delete_notification(
                notification_id, database=db, current_user=other
            )
        assert wrong_delete.value.status_code == 404
        assert len(db.notifications.docs) == 1

        deleted = await notif_api.delete_notification(
            notification_id, database=db, current_user=owner
        )
        assert deleted["message"] == "Deleted"
        assert db.notifications.docs == []

    asyncio.run(run())


def test_list_notifications_paginates_and_filters_unread():
    async def run():
        db = FakeDB()
        uid = str(ObjectId())

        for index in range(3):
            await notif.notify(
                db,
                [uid],
                "upload_completed",
                f"Notification {index}",
                "Body",
                dedupe_key=f"dataset-{index}",
            )

        first_page = await notif.list_notifications(db, uid, limit=2)
        assert len(first_page["items"]) == 2
        assert first_page["has_more"] is True
        assert first_page["next_cursor"]

        second_page = await notif.list_notifications(
            db, uid, cursor=first_page["next_cursor"], limit=2
        )
        assert len(second_page["items"]) == 1
        assert second_page["has_more"] is False

        newest_id = first_page["items"][0]["id"]
        await notif.mark_read(db, uid, newest_id)

        unread = await notif.list_notifications(db, uid, unread_only=True, limit=10)
        assert len(unread["items"]) == 2
        assert all(item["read_at"] is None for item in unread["items"])

        marked = await notif.mark_all_read(db, uid)
        assert marked == 2
        assert await notif.get_unread_count(db, uid) == 0

    asyncio.run(run())


def test_notify_admins_only_reaches_active_platform_admins():
    async def run():
        db = FakeDB()
        admin = user_doc(
            "admin@example.com",
            platform_role=PlatformRole.PLATFORM_ADMIN.value,
            status=UserStatus.ACTIVE.value,
        )
        inactive_admin = user_doc(
            "inactive-admin@example.com",
            platform_role=PlatformRole.PLATFORM_ADMIN.value,
            status=UserStatus.SUSPENDED.value,
            is_active=False,
        )
        member = user_doc("member@example.com")
        db.users.docs.extend([admin, inactive_admin, member])

        created = await notif.notify_admins(
            db, "refresh_reuse_spike", "Spike", "Body"
        )

        assert created
        recipients = {doc["user_id"] for doc in db.notifications.docs}
        assert recipients == {str(admin["_id"])}

    asyncio.run(run())


def test_notify_org_admins_only_reaches_that_orgs_admins():
    async def run():
        db = FakeDB()
        org_id = str(ObjectId())
        other_org_id = str(ObjectId())
        org_admin = user_doc(
            "org-admin@example.com",
            org_id=org_id,
            org_role=OrgRole.ORG_ADMIN.value,
            status=UserStatus.ACTIVE.value,
        )
        viewer = user_doc(
            "viewer@example.com",
            org_id=org_id,
            org_role=OrgRole.VIEWER.value,
            status=UserStatus.ACTIVE.value,
        )
        other_admin = user_doc(
            "other-admin@example.com",
            org_id=other_org_id,
            org_role=OrgRole.ORG_ADMIN.value,
            status=UserStatus.ACTIVE.value,
        )
        db.users.docs.extend([org_admin, viewer, other_admin])

        await notif.notify_org_admins(
            db, org_id, "org_application_decision", "Approved", "Body"
        )

        recipients = {doc["user_id"] for doc in db.notifications.docs}
        assert recipients == {str(org_admin["_id"])}

    asyncio.run(run())


def test_preferences_endpoint_rejects_unknown_types():
    async def run():
        db = FakeDB()
        user = _user(str(ObjectId()))

        with pytest.raises(HTTPException) as unknown:
            await notif_api.update_preferences(
                {"not_a_real_type": {"in_app": True}},
                database=db,
                current_user=user,
            )
        assert unknown.value.status_code == 400

        with pytest.raises(HTTPException) as bad_value:
            await notif_api.update_preferences(
                {"upload_completed": {"in_app": "yes"}},
                database=db,
                current_user=user,
            )
        assert bad_value.value.status_code == 400

    asyncio.run(run())
