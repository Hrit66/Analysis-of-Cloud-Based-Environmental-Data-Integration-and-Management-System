"""Upload endpoint contracts: detection, validation, overrides, reprocess."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api import datasets as datasets_module
from app.api.datasets import compute_file_hash, get_database
from app.main import app
from app.services import dataset_config


WATER_CSV = (
    b"timestamp,station,ph,DO,BOD\n"
    b"2021-01-01,A,7.2,6.0,4\n"
    b"2021-02-01,A,7.3,6.1,5\n"
    b"2021-03-01,A,7.1,6.5,4\n"
)


class FakeCursor:
    def __init__(self, rows):
        self.rows = list(rows)

    def __aiter__(self):
        self._iterator = iter(self.rows)
        return self

    async def __anext__(self):
        try:
            return next(self._iterator)
        except StopIteration:
            raise StopAsyncIteration


def _client(fake):
    app.dependency_overrides[get_database] = lambda: fake
    return TestClient(app)


class TestAutoDetection:
    def test_water_headers_are_detected_without_a_form_type(self, monkeypatch):
        fake = AsyncMock()
        fake.datasets.find_one = AsyncMock(return_value=None)
        monkeypatch.setattr(datasets_module.db, "db", fake)
        client = _client(fake)
        try:
            response = client.post(
                "/api/datasets/upload",
                files={"file": ("auto.csv", WATER_CSV, "text/csv")},
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["dataset_type"] == "water_quality"
        assert body["dataset_type_source"] == "detected"
        assert body["type_detection"]["scores"]["water_quality"] == 3
        assert body["pipeline_version"] == dataset_config.PIPELINE_VERSION

    def test_explicit_type_wins_over_detection(self, monkeypatch):
        fake = AsyncMock()
        fake.datasets.find_one = AsyncMock(return_value=None)
        monkeypatch.setattr(datasets_module.db, "db", fake)
        client = _client(fake)
        try:
            response = client.post(
                "/api/datasets/upload",
                files={"file": ("auto.csv", WATER_CSV, "text/csv")},
                data={"dataset_type": "water_quality"},
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json()["dataset_type_source"] == "override"

    def test_bad_explicit_type_is_a_clear_400(self):
        fake = AsyncMock()
        client = _client(fake)
        try:
            response = client.post(
                "/api/datasets/upload",
                files={"file": ("auto.csv", WATER_CSV, "text/csv")},
                data={"dataset_type": "not_a_type"},
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 400
        assert "Unsupported dataset_type" in response.json()["detail"]

    def test_long_format_file_is_typed_from_parameter_values(self, monkeypatch):
        fake = AsyncMock()
        fake.datasets.find_one = AsyncMock(return_value=None)
        monkeypatch.setattr(datasets_module.db, "db", fake)
        client = _client(fake)
        csv = (
            b"timestamp,station,parameter,value\n"
            b"2021-01-01,A,DO_mgl,6.5\n"
            b"2021-01-01,A,Nitrate as N,2.0\n"
            b"2021-01-01,A,pH,7.2\n"
        )
        try:
            response = client.post(
                "/api/datasets/upload",
                files={"file": ("data.csv", csv, "text/csv")},
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["dataset_type"] == "water_quality"
        assert body["type_detection"]["long_format"] is True
        assert body["type_detection"]["ambiguous"] is False

    def test_garbage_file_returns_400_not_500(self):
        fake = AsyncMock()
        client = _client(fake)
        try:
            response = client.post(
                "/api/datasets/upload",
                files={"file": ("junk.csv", b"alpha,beta\nnot,a,dataset\n", "text/csv")},
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 400
        assert "Could not" in response.json()["detail"]


class TestConfigOverrides:
    def test_override_is_applied_and_changes_ingested_values(self, monkeypatch):
        fake = AsyncMock()
        fake.datasets.find_one = AsyncMock(return_value=None)
        monkeypatch.setattr(datasets_module.db, "db", fake)
        client = _client(fake)
        csv = WATER_CSV.replace(b"DO", b"DO")
        csv = b"timestamp,station,ph,DO,BOD\n2021-01-01,A,7.2,20.0,4\n"
        try:
            response = client.post(
                "/api/datasets/upload",
                files={"file": ("override.csv", csv, "text/csv")},
                data={"config_overrides": json.dumps({"do": [0, 50]})},
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json()["config_overrides"] == {"do": [0.0, 50.0]}
        inserted = fake.water_quality.insert_many.await_args.args[0]
        assert inserted[0]["do"] == 20.0

    def test_without_override_the_same_value_is_blanked(self, monkeypatch):
        fake = AsyncMock()
        fake.datasets.find_one = AsyncMock(return_value=None)
        monkeypatch.setattr(datasets_module.db, "db", fake)
        client = _client(fake)
        csv = b"timestamp,station,ph,DO,BOD\n2021-01-01,A,7.2,20.0,4\n"
        try:
            response = client.post(
                "/api/datasets/upload",
                files={"file": ("default.csv", csv, "text/csv")},
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        inserted = fake.water_quality.insert_many.await_args.args[0]
        assert inserted[0]["do"] is None

    def test_unknown_override_column_is_rejected(self):
        fake = AsyncMock()
        client = _client(fake)
        try:
            response = client.post(
                "/api/datasets/upload",
                files={"file": ("override.csv", WATER_CSV, "text/csv")},
                data={"config_overrides": json.dumps({"not_a_column": [0, 1]})},
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 400
        assert "unknown columns" in response.json()["detail"]

    def test_malformed_override_json_is_rejected(self):
        fake = AsyncMock()
        client = _client(fake)
        try:
            response = client.post(
                "/api/datasets/upload",
                files={"file": ("override.csv", WATER_CSV, "text/csv")},
                data={"config_overrides": "{not json"},
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 400
        assert "not valid JSON" in response.json()["detail"]


class TestVersionedHash:
    def test_type_and_pipeline_version_change_the_key(self):
        content = b"timestamp,location,pm25\n2021-01-01,A,10\n"
        base = compute_file_hash(content, "air_quality")
        assert base != compute_file_hash(content, "water_quality")
        assert base != compute_file_hash(content, "air_quality", "1999.01.1")
        assert base != compute_file_hash(content, "air_quality", location="Station A")


class TestReprocess:
    def test_missing_sources_return_409_with_guidance(self):
        fake = AsyncMock()
        fake.datasets.find_one = AsyncMock(return_value={
            "_id": datasets_module.ObjectId("6ad3cbfee69574480fc16e50"),
            "dataset_type": "air_quality",
            "source_paths": ["/tmp/definitely-not-here.csv"],
            "filename": "gone.csv",
        })
        client = _client(fake)
        try:
            response = client.post("/api/datasets/6ad3cbfee69574480fc16e50/reprocess")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 409
        assert "Re-upload" in response.json()["detail"]

    def test_retained_source_schedules_reprocessing(self, tmp_path, monkeypatch):
        source = tmp_path / "retained.csv"
        source.write_bytes(WATER_CSV)
        dataset_id = "6ad3cbfee69574480fc16e50"
        fake = AsyncMock()
        fake.datasets.find_one = AsyncMock(return_value={
            "_id": datasets_module.ObjectId(dataset_id),
            "dataset_type": "water_quality",
            "source_paths": [str(source)],
            "filename": "retained.csv",
            "import_mode": "generic",
            "config_overrides": {},
            "type_detection": {},
        })
        monkeypatch.setattr(datasets_module.db, "db", fake)
        client = _client(fake)
        try:
            response = client.post(f"/api/datasets/{dataset_id}/reprocess")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 202
        assert response.json()["status"] == "uploaded"
        fake.air_quality.delete_many.assert_awaited()
        fake.forecasts.delete_many.assert_awaited()
        fake.datasets.update_one.assert_awaited()
        updates = [
            call.args[1].get("$set", {})
            for call in fake.datasets.update_one.await_args_list
        ]
        reprocess_update = next(item for item in updates if "file_hash" in item)
        assert reprocess_update["file_hash"] == compute_file_hash(WATER_CSV, "water_quality")
        assert reprocess_update["pipeline_version"] == dataset_config.PIPELINE_VERSION


class TestStationEndpoints:
    def _fake(self):
        fake = AsyncMock()
        fake.datasets.find_one = AsyncMock(return_value={
            "_id": datasets_module.ObjectId("6ad3cbfee69574480fc16e50"),
        })
        fake.air_quality.aggregate = lambda *args, **kwargs: FakeCursor([
            {"_id": "JIGANI TNAK"}, {"_id": "JIGANI TANK"},
        ])
        fake.water_quality.aggregate = lambda *args, **kwargs: FakeCursor([])
        return fake

    def test_suggestions_are_reported_without_writing(self):
        fake = self._fake()
        client = _client(fake)
        try:
            response = client.get(
                "/api/datasets/6ad3cbfee69574480fc16e50/station-suggestions"
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["suggestions"]
        assert body["suggestions"][0]["variants"]
        fake.air_quality.update_many.assert_not_awaited()

    def test_confirmed_merge_updates_only_that_dataset(self):
        fake = self._fake()
        fake.air_quality.update_many = AsyncMock(return_value=SimpleNamespace(modified_count=3))
        fake.water_quality.update_many = AsyncMock(return_value=SimpleNamespace(modified_count=0))
        fake.anomalies.update_many = AsyncMock(return_value=SimpleNamespace(modified_count=0))
        fake.forecasts.update_many = AsyncMock(return_value=SimpleNamespace(modified_count=0))
        client = _client(fake)
        try:
            response = client.post(
                "/api/datasets/6ad3cbfee69574480fc16e50/station-merges",
                json={"merges": [{
                    "canonical": "JIGANI TANK",
                    "aliases": ["JIGANI TNAK"],
                }]},
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json()["applied"][0]["records_updated"] == 3
        query = fake.air_quality.update_many.await_args.args[0]
        assert query["dataset_id"] == "6ad3cbfee69574480fc16e50"
        assert query["location"] == {"$in": ["JIGANI TNAK"]}
