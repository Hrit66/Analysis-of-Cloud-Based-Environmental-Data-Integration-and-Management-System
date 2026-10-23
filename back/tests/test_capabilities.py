"""Capability derivation + dataset guards.

Dashboards and analytics endpoints must match a dataset by what it actually
contains; a dataset that lacks the requested data fails with a clear 4xx
instead of returning (or showing) another dataset's numbers.
"""
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.api.analytics import get_database
from app.main import app
from app.services.pipeline_interface import derive_capabilities

DATASET_ID = "6ad3cbfee69574480fc16e50"


class TestDeriveCapabilities:
    def test_imd_weather_columns_serve_both_weather_pages(self):
        columns = ["timestamp", "precipitation", "temp_max", "temp_min", "location"]
        assert derive_capabilities(columns) == ["temperature", "rainfall"]

    def test_original_kaggle_pollutant_names_detected(self):
        columns = ["City", "Datetime", "PM2.5", "PM10", "NO2", "SO2", "CO", "O3", "AQI"]
        assert derive_capabilities(columns) == ["air_quality"]

    def test_open_meteo_weather_column_names_detected(self):
        columns = ["date", "city", "temperature_2m_max", "temperature_2m_min", "precipitation_sum"]
        assert derive_capabilities(columns) == ["temperature", "rainfall"]

    def test_pandas_index_and_none_inputs_are_supported(self):
        import pandas as pd

        assert derive_capabilities(pd.Index(["timestamp", "ph", "do", "bod", "location"])) == ["water_quality"]
        assert derive_capabilities(pd.Index([]), "water_quality") == ["water_quality"]
        assert derive_capabilities(None) == []

    def test_water_nitrogen_columns_do_not_trigger_air_quality(self):
        columns = [
            "State", "Station_Name", "Date", "ph", "_do", "bod3_27", "turb",
            "ec_gen", "no3_n", "nh3_n", "no2_n", "no2__n", "no2_no3", "sio3",
            "tcol_mpn", "fcol_mpn", "Latitude", "Longitude",
        ]
        assert derive_capabilities(columns) == ["water_quality"]

    def test_water_quality_columns_detected(self):
        assert derive_capabilities(["timestamp", "ph", "turbidity", "bod"]) == ["water_quality"]

    def test_conductivity_is_not_mistaken_for_carbon_monoxide(self):
        assert derive_capabilities(["conductivity", "turbidity"]) == ["water_quality"]

    def test_declared_type_is_used_only_as_fallback(self):
        assert derive_capabilities(["value_a", "value_b"], "air_quality") == ["air_quality"]
        assert derive_capabilities([], None) == []


class TestDatasetGuards:
    def _client(self, fake):
        app.dependency_overrides[get_database] = lambda: fake
        return TestClient(app)

    def _fake_db(self, dataset):
        fake = AsyncMock()
        fake.datasets.find_one = AsyncMock(return_value=dataset)
        return fake

    def test_wrong_capability_is_rejected(self):
        fake = self._fake_db({
            "_id": DATASET_ID,
            "dataset_type": "rainfall",
            "capabilities": ["temperature", "rainfall"],
        })
        client = self._client(fake)
        try:
            response = client.get(f"/api/analytics/wqi/{DATASET_ID}")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 400
        assert "water_quality" in response.json()["detail"]

    def test_missing_dataset_is_404(self):
        client = self._client(self._fake_db(None))
        try:
            response = client.get(f"/api/analytics/aqi/{DATASET_ID}")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404

    def test_capabilities_fall_back_to_derivation_from_columns(self):
        """Datasets stored before the capability migration stay protected."""
        fake = self._fake_db({
            "_id": DATASET_ID,
            "dataset_type": "rainfall",
            "original_columns": ["timestamp", "precipitation", "temp_max", "temp_min"],
        })
        client = self._client(fake)
        try:
            response = client.get(f"/api/analytics/wqi/{DATASET_ID}")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 400
        assert "water_quality" in response.json()["detail"]

    def test_invalid_dataset_id_is_400(self):
        client = self._client(self._fake_db(None))
        try:
            response = client.get("/api/analytics/aqi/not-an-object-id")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 400
