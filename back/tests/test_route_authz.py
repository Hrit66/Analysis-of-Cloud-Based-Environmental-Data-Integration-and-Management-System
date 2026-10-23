from bson import ObjectId
from fastapi.testclient import TestClient

from app.api import analytics, auth as auth_api, datasets as datasets_api, export
from app.main import app
from app.services import auth as auth_service

from tests.test_auth_security import FakeDB, user_doc


FOREIGN_DATASET_REQUESTS = [
    ("GET", "/api/analytics/aqi/{dataset_id}", {}),
    ("GET", "/api/analytics/aqi/{dataset_id}/summary", {}),
    ("GET", "/api/analytics/anomalies/{dataset_id}", {}),
    ("GET", "/api/analytics/anomalies/{dataset_id}/summary", {}),
    ("GET", "/api/analytics/forecasts/{dataset_id}", {}),
    ("GET", "/api/analytics/forecasts/{dataset_id}/latest", {"params": {"location": "x", "parameter": "pm25"}}),
    ("GET", "/api/analytics/trends/{dataset_id}", {"params": {"location": "x", "parameter": "pm25"}}),
    ("GET", "/api/analytics/temperature/{dataset_id}", {}),
    ("GET", "/api/analytics/temperature/{dataset_id}/summary", {}),
    ("GET", "/api/analytics/date-range/{dataset_id}", {}),
    ("GET", "/api/analytics/rainfall/{dataset_id}", {}),
    ("GET", "/api/analytics/rainfall/{dataset_id}/summary", {}),
    ("GET", "/api/analytics/rainfall/{dataset_id}/outlook", {}),
    ("GET", "/api/analytics/wqi/{dataset_id}", {}),
    ("GET", "/api/analytics/wqi/{dataset_id}/summary", {}),
    ("GET", "/api/analytics/wqi/{dataset_id}/trend", {"params": {"location": "x"}}),
    ("GET", "/api/export/aqi/{dataset_id}", {}),
    ("GET", "/api/export/anomalies/{dataset_id}", {}),
    ("GET", "/api/export/forecasts/{dataset_id}", {}),
    ("GET", "/api/export/raw/{dataset_id}", {}),
    ("GET", "/api/export/dataset/{dataset_id}", {}),
    ("GET", "/api/datasets/{dataset_id}", {}),
    ("GET", "/api/datasets/{dataset_id}/status", {}),
    ("GET", "/api/datasets/{dataset_id}/station-suggestions", {}),
    ("PATCH", "/api/datasets/{dataset_id}", {"json": {"display_name": "renamed"}}),
    ("POST", "/api/datasets/{dataset_id}/reprocess", {}),
    ("POST", "/api/datasets/{dataset_id}/station-merges", {"json": {"merges": []}}),
    ("DELETE", "/api/datasets/{dataset_id}", {}),
]


def _override_database(db):
    app.dependency_overrides[auth_api.get_database] = lambda: db
    app.dependency_overrides[analytics.get_database] = lambda: db
    app.dependency_overrides[export.get_database] = lambda: db
    app.dependency_overrides[datasets_api.get_database] = lambda: db


def _token_headers(doc):
    token = auth_service.create_access_token({
        "sub": str(doc["_id"]),
        "email": doc["email"],
        "tv": 0,
    })
    return {"Authorization": f"Bearer {token}"}


def _assert_foreign_routes_404(client, headers, dataset_id):
    for method, template, kwargs in FOREIGN_DATASET_REQUESTS:
        path = template.format(dataset_id=dataset_id)
        response = client.request(method, path, headers=headers, **kwargs)
        assert response.status_code == 404, (method, path, response.status_code, response.text)


def test_every_dataset_route_hides_foreign_datasets():
    db = FakeDB()
    owner_doc = user_doc("owner@example.com")
    db.users.docs.append(owner_doc)
    dataset_id = str(ObjectId())
    db.datasets.docs.append({
        "_id": ObjectId(dataset_id),
        "owner_id": "someone-else",
        "visibility": "private",
        "status": "completed",
    })
    headers = _token_headers(owner_doc)
    _override_database(db)
    try:
        _assert_foreign_routes_404(TestClient(app), headers, dataset_id)
    finally:
        app.dependency_overrides.clear()


def test_platform_admin_gets_404_for_foreign_dataset_routes():
    db = FakeDB()
    admin_doc = user_doc(
        "admin@example.com",
        platform_role="platform_admin",
        mfa_enabled=True,
    )
    db.users.docs.append(admin_doc)
    dataset_id = str(ObjectId())
    db.datasets.docs.append({
        "_id": ObjectId(dataset_id),
        "owner_id": "someone-else",
        "visibility": "private",
        "status": "completed",
    })
    headers = _token_headers(admin_doc)
    _override_database(db)
    try:
        _assert_foreign_routes_404(TestClient(app), headers, dataset_id)
    finally:
        app.dependency_overrides.clear()


def test_platform_admin_cannot_use_upload_routes():
    db = FakeDB()
    admin_doc = user_doc(
        "admin@example.com",
        platform_role="platform_admin",
        mfa_enabled=True,
    )
    db.users.docs.append(admin_doc)
    headers = _token_headers(admin_doc)
    _override_database(db)
    try:
        client = TestClient(app)
        for path, field in (
            ("/api/datasets/upload", "file"),
            ("/api/datasets/upload-imd", "files"),
            ("/api/datasets/upload-river-summary", "files"),
        ):
            files = {field: ("sample.csv", b"a,b\n1,2\n", "text/csv")}
            response = client.post(path, headers=headers, files=files)
            assert response.status_code == 403, (path, response.status_code, response.text)
        assert db.datasets.docs == []
    finally:
        app.dependency_overrides.clear()


def test_org_analyst_can_read_own_org_dataset_but_not_another_org():
    db = FakeDB()
    org_a, org_b = ObjectId(), ObjectId()
    for org_id in (org_a, org_b):
        db.organizations.docs.append({
            "_id": org_id,
            "status": "verified",
            "settings": {"require_mfa": False},
        })
    analyst_doc = user_doc(
        "analyst@a.edu", org_id=str(org_a), org_role="analyst",
    )
    db.users.docs.append(analyst_doc)
    own_id, foreign_id = str(ObjectId()), str(ObjectId())
    db.datasets.docs.extend([
        {
            "_id": ObjectId(own_id),
            "owner_id": "someone-else",
            "visibility": "org",
            "org_id": str(org_a),
            "status": "completed",
        },
        {
            "_id": ObjectId(foreign_id),
            "owner_id": "someone-else",
            "visibility": "org",
            "org_id": str(org_b),
            "status": "completed",
        },
    ])
    token = auth_service.create_access_token({
        "sub": str(analyst_doc["_id"]),
        "email": analyst_doc["email"],
        "tv": 0,
    })
    headers = {"Authorization": f"Bearer {token}"}
    app.dependency_overrides[auth_api.get_database] = lambda: db
    app.dependency_overrides[datasets_api.get_database] = lambda: db
    try:
        client = TestClient(app)
        assert client.get(f"/api/datasets/{own_id}", headers=headers).status_code == 200
        assert client.get(f"/api/datasets/{foreign_id}", headers=headers).status_code == 404
        assert client.patch(
            f"/api/datasets/{foreign_id}", headers=headers, json={"display_name": "x"},
        ).status_code == 404
    finally:
        app.dependency_overrides.clear()
