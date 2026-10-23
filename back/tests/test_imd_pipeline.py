from pathlib import Path

import numpy as np
import pytest

from app.services.pipeline_interface import (
    clean_dataframe,
    imd_parameter_from_source,
    merge_imd_files,
    parse_file,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"

IMD_TRIO = ("imd_rain_testcity.csv", "imd_tmax_testcity.csv", "imd_tmin_testcity.csv")


def load(name: str, dataset_type: str = "rainfall", **kwargs):
    return clean_dataframe(
        parse_file(str(FIXTURES / name), dataset_type),
        dataset_type,
        source_name=name,
        **kwargs,
    )


class TestIMDParameterDetection:
    def test_parameter_from_filename(self):
        assert imd_parameter_from_source("rain_bengaluru_12.97_77.59.csv") == "precipitation"
        assert imd_parameter_from_source("tmax_bengaluru_12.97_77.59.csv") == "temp_max"
        assert imd_parameter_from_source("tmin_kolkata.csv") == "temp_min"
        assert imd_parameter_from_source("imd_station_data.csv") is None


class TestIMDSingleFile:
    def test_tmax_file_maps_to_temp_max_with_coordinate_location(self):
        df, report = load("imd_tmax_testcity.csv", "temperature")
        assert "temp_max" in df.columns
        assert list(df["temp_max"]) == [29.0, 30.0, 31.0]
        assert df["location"].iloc[0] == "12.97 77.59"
        assert report["source_format"] == "imd"
        assert report["imd_parameter"] == "temp_max"
        assert report["imd_coordinate"] == "12.97 77.59"
        assert report["location_source"] == "imd_coordinate"

    def test_upload_location_field_overrides_coordinate(self):
        df, report = load("imd_tmax_testcity.csv", "temperature", default_location="Test City")
        assert set(df["location"]) == {"Test City"}
        assert report["location_source"] == "upload_field"

    def test_corrupt_rain_file_sentinels_and_negatives_cleared(self):
        df, report = load("imd_rain_corrupt_bengaluru.csv")
        values = df.set_index("timestamp")["precipitation"]
        assert values.loc["2023-01-01T00:00:00Z"] == 0.0
        assert np.isnan(values.loc["2023-01-02T00:00:00Z"])
        assert np.isnan(values.loc["2023-01-03T00:00:00Z"])
        assert values.loc["2023-01-04T00:00:00Z"] == 10.2
        assert report["sentinel_values_detected"]["precipitation"] == 1
        assert report["out_of_range_values_set_to_nan"]["precipitation"] == 1

    def test_broken_file_missing_value_column_is_rejected(self):
        with pytest.raises(ValueError, match="missing its value column"):
            load("imd_broken_missing_column.csv")

    def test_coordinate_file_without_parameter_name_is_rejected(self):
        with pytest.raises(ValueError, match="parameter cannot be derived"):
            load("imd_station_data.csv")


class TestIMDMerge:
    def test_three_files_merge_on_date(self):
        paths = [str(FIXTURES / name) for name in IMD_TRIO]
        merged, meta = merge_imd_files(paths)
        assert len(merged) == 4
        assert meta["source_format"] == "imd_merged"
        assert meta["imd_parameters"] == ["precipitation", "temp_max", "temp_min"]

        cleaned, report = clean_dataframe(merged, "rainfall", extra_report=meta)
        rows = cleaned.set_index("timestamp")

        assert rows.loc["2023-01-02T00:00:00Z", "precipitation"] == 12.5
        assert np.isnan(rows.loc["2023-01-03T00:00:00Z", "precipitation"])
        assert np.isnan(rows.loc["2023-01-04T00:00:00Z", "precipitation"])
        assert report["sentinel_values_detected"]["precipitation"] == 1
        assert report["out_of_range_values_set_to_nan"]["precipitation"] == 1
        assert report["source_format"] == "imd_merged"
        assert report["location_source"] == "imd_coordinate"
        assert cleaned["location"].iloc[0] == "12.97 77.59"

    def test_derived_temperature_mean_is_labeled_as_derived(self):
        paths = [str(FIXTURES / name) for name in IMD_TRIO]
        merged, meta = merge_imd_files(paths)
        cleaned, report = clean_dataframe(merged, "rainfall", extra_report=meta)
        rows = cleaned.set_index("timestamp")

        assert rows.loc["2023-01-01T00:00:00Z", "temperature"] == pytest.approx(22.0)
        assert rows.loc["2023-01-02T00:00:00Z", "temperature"] == pytest.approx(23.0)
        assert rows.loc["2023-01-03T00:00:00Z", "temperature"] == pytest.approx(24.0)
        assert np.isnan(rows.loc["2023-01-04T00:00:00Z", "temperature"])
        assert "approximation" in report["derived_columns"]["temperature"]
        assert report["derived_values_imputed"]["temperature"] == 3

    def test_explicit_location_used_when_given(self):
        paths = [str(FIXTURES / name) for name in IMD_TRIO]
        merged, meta = merge_imd_files(paths, location="Bengaluru (IMD)")
        cleaned, report = clean_dataframe(merged, "rainfall", extra_report=meta)
        assert set(cleaned["location"]) == {"Bengaluru (IMD)"}
        assert report["location_source"] == "upload_field"

    def test_duplicate_parameter_across_files_rejected(self):
        paths = [
            str(FIXTURES / "imd_rain_testcity.csv"),
            str(FIXTURES / "imd_rain_corrupt_bengaluru.csv"),
        ]
        with pytest.raises(ValueError, match="Duplicate IMD parameter"):
            merge_imd_files(paths)

    def test_no_files_rejected(self):
        with pytest.raises(ValueError, match="No IMD files"):
            merge_imd_files([])


class TestIMDUploadEndpoint:
    def _imd_files(self):
        return [
            ("files", (name, (FIXTURES / name).read_bytes(), "text/csv")) for name in IMD_TRIO
        ]

    def _client(self, fake):
        from fastapi.testclient import TestClient

        from app.main import app
        from app.api.datasets import get_database

        app.dependency_overrides[get_database] = lambda: fake
        return TestClient(app), app

    def test_upload_imd_merges_and_stores_dataset(self, monkeypatch):
        from unittest.mock import AsyncMock

        from app.api import datasets as datasets_module

        fake = AsyncMock()
        fake.datasets.find_one = AsyncMock(return_value=None)
        monkeypatch.setattr(datasets_module.db, "db", fake)

        client, app = self._client(fake)
        try:
            response = client.post(
                "/api/datasets/upload-imd",
                files=self._imd_files(),
                data={"location": "Bengaluru Test"},
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["duplicate"] is False
        assert body["dataset_type"] == "rainfall"

        inserted = fake.datasets.insert_one.await_args.args[0]
        assert inserted["dataset_type"] == "rainfall"
        assert inserted["filename"].startswith("IMD:")
        assert inserted["file_hash"]

        assert fake.air_quality.insert_many.await_count >= 1
        records = fake.air_quality.insert_many.await_args_list[0].args[0]
        assert len(records) == 4
        assert records[0]["location"] == "Bengaluru Test"
        assert records[0]["dataset_id"] == body["dataset_id"]

        completed = fake.datasets.update_one.await_args_list[-1].args[1]["$set"]
        assert completed["status"] == "completed"
        assert completed["capabilities"] == ["temperature", "rainfall"]
        assert completed["display_name"].startswith("IMD · Bengaluru Test")

    def test_upload_imd_duplicate_returns_existing(self):
        from unittest.mock import AsyncMock

        from bson import ObjectId

        existing_id = ObjectId()
        fake = AsyncMock()
        fake.datasets.find_one = AsyncMock(return_value={"_id": existing_id, "status": "completed"})

        client, app = self._client(fake)
        try:
            response = client.post("/api/datasets/upload-imd", files=self._imd_files())
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["duplicate"] is True
        assert body["dataset_id"] == str(existing_id)
        fake.datasets.insert_one.assert_not_called()

    def test_upload_imd_ambiguous_names_rejected(self):
        from unittest.mock import AsyncMock

        fake = AsyncMock()

        client, app = self._client(fake)
        try:
            response = client.post(
                "/api/datasets/upload-imd",
                files=[
                    ("files", ("data_a.csv", b"DateTime,12.97 77.59\n2023-01-01,1.0\n", "text/csv")),
                ],
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 400
        assert "rain" in response.json()["detail"]
