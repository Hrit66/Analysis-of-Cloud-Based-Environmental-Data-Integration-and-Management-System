from fastapi.testclient import TestClient

from app.api import auth as auth_api
from app.main import app
from app.models.user import AccountType, OrgRole, PlatformRole
from app.services import auth as auth_service
from app.services.auth import user_public

from tests.test_auth_security import FakeDB, _user, user_doc


ANALYSIS_NAVIGATION = [
    "home", "upload", "datasets", "aqi", "wqi",
    "temperature", "rainfall", "anomalies", "reports",
]


def test_navigation_matrix_is_role_scoped():
    student = _user(
        "64b000000000000000000001", account_type=AccountType.STUDENT,
    )
    assert user_public(student)["navigation"] == ANALYSIS_NAVIGATION

    org_member = _user(
        "64b000000000000000000002",
        org_id="64b000000000000000000010",
        org_role=OrgRole.ANALYST,
    )
    assert user_public(org_member)["navigation"] == ANALYSIS_NAVIGATION

    org_admin = _user(
        "64b000000000000000000003",
        org_id="64b000000000000000000010",
        org_role=OrgRole.ORG_ADMIN,
    )
    assert user_public(org_admin)["navigation"] == ANALYSIS_NAVIGATION + ["organization"]

    platform_admin = _user(
        "64b000000000000000000004",
        platform_role=PlatformRole.PLATFORM_ADMIN,
    )
    assert user_public(platform_admin)["navigation"] == ["home", "admin"]


def test_me_returns_navigation_from_server():
    db = FakeDB()
    admin_doc = user_doc(
        "admin@example.com",
        platform_role=PlatformRole.PLATFORM_ADMIN.value,
        mfa_enabled=True,
    )
    db.users.docs.append(admin_doc)
    token = auth_service.create_access_token({
        "sub": str(admin_doc["_id"]),
        "email": admin_doc["email"],
        "tv": 0,
    })
    app.dependency_overrides[auth_api.get_database] = lambda: db
    try:
        response = TestClient(app).get(
            "/api/auth/me", headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["navigation"] == ["home", "admin"]
    assert response.json()["platform_role"] == PlatformRole.PLATFORM_ADMIN.value
