"""Dataset rename (display_name) endpoint."""
from types import SimpleNamespace

from bson import ObjectId
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from app.api.datasets import get_database
from app.main import app

DATASET_ID = "6ad3cbfee69574480fc16e50"


class TestRenameDataset:
    def _client(self, fake):
        app.dependency_overrides[get_database] = lambda: fake
        return TestClient(app)

    def test_renames_dataset_and_trims_whitespace(self):
        fake = AsyncMock()
        fake.datasets.find_one = AsyncMock(return_value={"_id": ObjectId(DATASET_ID)})
        fake.datasets.update_one = AsyncMock(return_value=SimpleNamespace(matched_count=1))
        client = self._client(fake)
        try:
            response = client.patch(f"/api/datasets/{DATASET_ID}", json={"display_name": "  Bengaluru Monsoon  "})
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json()["display_name"] == "Bengaluru Monsoon"
        update_args = fake.datasets.update_one.await_args
        assert str(update_args.args[0]["_id"]) == DATASET_ID
        assert update_args.args[1]["$set"]["display_name"] == "Bengaluru Monsoon"

    def test_rejects_blank_name(self):
        fake = AsyncMock()
        client = self._client(fake)
        try:
            response = client.patch(f"/api/datasets/{DATASET_ID}", json={"display_name": "   "})
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 400
        fake.datasets.update_one.assert_not_awaited()

    def test_rejects_overlong_name(self):
        fake = AsyncMock()
        client = self._client(fake)
        try:
            response = client.patch(f"/api/datasets/{DATASET_ID}", json={"display_name": "x" * 81})
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 400

    def test_missing_dataset_is_404(self):
        fake = AsyncMock()
        fake.datasets.find_one = AsyncMock(return_value=None)
        fake.datasets.update_one = AsyncMock(return_value=SimpleNamespace(matched_count=0))
        client = self._client(fake)
        try:
            response = client.patch(f"/api/datasets/{DATASET_ID}", json={"display_name": "New name"})
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404

    def test_invalid_id_is_400(self):
        fake = AsyncMock()
        client = self._client(fake)
        try:
            response = client.patch("/api/datasets/not-an-object-id", json={"display_name": "New name"})
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 400
