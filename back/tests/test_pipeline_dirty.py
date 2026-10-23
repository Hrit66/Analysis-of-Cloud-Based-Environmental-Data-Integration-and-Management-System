import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import numpy as np
import pandas as pd
import pytest

from app.services.pipeline_interface import parse_file, clean_dataframe

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load(name: str, dataset_type: str = "air_quality"):
    return clean_dataframe(parse_file(str(FIXTURES / name), dataset_type), dataset_type)


class TestColumnNameVariants:
    def test_variants_map_to_canonical_columns(self):
        df, report = load("column_variants.csv")
        assert len(df) == 2
        assert list(df["pm25"]) == [45.0, 52.0]
        assert list(df["pm10"]) == [80.0, 91.0]
        assert list(df["no2"]) == [30.0, 33.0]
        assert list(df["so2"]) == [10.0, 11.0]
        assert list(df["co"]) == [1.2, 1.4]
        assert list(df["o3"]) == [40.0, 44.0]
        assert list(df["temperature"]) == [28.5, 29.1]
        assert list(df["precipitation"]) == [0.0, 2.5]

    def test_report_records_every_rename(self):
        _, report = load("column_variants.csv")
        renames = report["columns_renamed"]
        assert renames["Date"] == "timestamp"
        assert renames["city"] == "location"
        assert renames["PM2.5 (µg/m³)"] == "pm25"
        assert renames["pm_10"] == "pm10"
        assert renames["Temperature (°C)"] == "temperature"
        assert report["missing_values_count"] == {}


class TestMissingValueMarkers:
    def test_all_markers_become_null(self):
        df, report = load("missing_markers.csv")
        assert len(df) == 7
        assert df["pm25"].isna().all()
        assert list(df["pm10"]) == [80.0] * 7
        assert report["missing_markers_found"]["pm25"] == 7
        assert report["missing_values_count"]["pm25"] == 7
        assert "pm10" not in report["missing_values_count"]


class TestSentinelAndImpossibleValues:
    def test_sentinels_and_out_of_range_are_cleared(self):
        df, report = load("sentinels_impossible.csv")

        assert np.isnan(df.loc[0, "pm25"]) and np.isnan(df.loc[0, "pm10"])
        assert df.loc[0, "temperature"] == 25.0
        assert df.loc[0, "precipitation"] == 5.0

        assert df.loc[1, ["pm25", "pm10", "temperature", "precipitation"]].isna().all()

        assert report["sentinel_values_detected"] == {"pm25": 1, "pm10": 1}
        assert report["out_of_range_values_set_to_nan"] == {
            "pm25": 1,
            "pm10": 1,
            "temperature": 1,
            "precipitation": 1,
        }

    def test_impossible_water_values_are_cleared(self):
        df, report = load("impossible_water.csv", "water_quality")
        assert df.loc[0, "ph"] == 7.2
        assert df.loc[0, "do"] == 6.5
        assert df.loc[1, ["ph", "turbidity", "tds", "do"]].isna().all()
        assert report["out_of_range_values_set_to_nan"]["ph"] == 1
        assert report["out_of_range_values_set_to_nan"]["turbidity"] == 1
        assert report["out_of_range_values_set_to_nan"]["do"] == 1
        assert report["sentinel_values_detected"]["tds"] == 1


class TestBelowDetectionLimit:
    def test_less_than_values_are_halved_and_markers_become_null(self):
        df, report = load("below_detection.csv")
        assert df.loc[0, "pm25"] == 1.0
        assert np.isnan(df.loc[0, "pm10"])
        assert df.loc[1, "pm10"] == 0.75
        assert np.isnan(df.loc[1, "pm25"])
        assert list(df["no2"]) == [30.0, 32.0]

        assert report["below_detection_limit_converted"] == {"pm25": 1, "pm10": 1}
        assert report["below_detection_limit_treated_missing"] == {"pm25": 1, "pm10": 1}


class TestDateFormats:
    def test_mixed_formats_parse_to_utc_iso(self):
        df, report = load("date_formats.csv")
        by_location = dict(zip(df["location"], df["timestamp"]))
        assert by_location["DateA"] == "2026-10-11T00:00:00Z"
        assert by_location["DateB"] == "2026-11-10T00:00:00Z"
        assert by_location["DateC"] == "2026-10-11T00:00:00Z"
        assert by_location["DateD"] == "2026-10-11T14:00:00Z"
        assert report["ambiguous_date_strings"] == 2

    def test_ist_and_utc_and_offsets_normalize(self):
        df, _ = load("timezones.csv")
        by_location = dict(zip(df["location"], df["timestamp"]))
        assert by_location["TZ-Z"] == "2026-10-11T10:00:00Z"
        assert by_location["TZ-IST"] == "2026-10-11T10:00:00Z"
        assert by_location["TZ-UTC"] == "2026-10-11T10:00:00Z"
        assert by_location["TZ-OFFSET"] == "2026-10-11T04:30:00Z"
        assert by_location["TZ-NAIVE"] == "2026-10-11T10:00:00Z"


class TestDuplicates:
    def test_duplicate_rows_are_dropped_keeping_first(self):
        df, report = load("duplicates.csv")
        assert len(df) == 2
        assert report["duplicates_removed"] == 2
        first = df[df["location"] == "DupCity"].iloc[0]
        assert first["pm25"] == 10.0


class TestTypeValidation:
    def test_weather_file_rejected_as_air_quality(self):
        with pytest.raises(ValueError, match=r"missing required columns: pm25, pm10"):
            load("wrong_type_weather.csv", "air_quality")

    def test_weather_file_rejected_as_water_quality(self):
        with pytest.raises(ValueError, match=r"missing required columns: ph"):
            load("wrong_type_weather.csv", "water_quality")

    def test_weather_file_accepted_as_temperature(self):
        df, _ = load("wrong_type_weather.csv", "temperature")
        assert len(df) == 2
        assert df.loc[0, "temperature"] == 28.5

    def test_weather_file_accepted_as_rainfall(self):
        df, _ = load("wrong_type_weather.csv", "rainfall")
        assert list(df["precipitation"]) == [0.0, 2.5]


class TestExcelQuirks:
    def test_title_rows_merged_cells_and_multiple_sheets(self):
        df, report = load("excel_quirks.xlsx")
        assert len(df) == 2
        assert list(df["pm25"]) == [42.0, 47.0]
        assert list(df["location"].unique()) == ["ExcelCity"]
        assert report["columns_renamed"]["Date"] == "timestamp"
        assert report["columns_renamed"]["Station"] == "location"


class TestJsonShapes:
    def test_list_of_records(self):
        df, _ = load("json_records.json")
        assert len(df) == 2
        assert list(df["pm25"]) == [18.0, 21.0]

    def test_nested_objects_are_flattened(self):
        df, _ = load("json_nested.json")
        assert list(df["pm25"]) == [12.0, 15.0]
        assert list(df["no2"]) == [7.0, 9.0]

    def test_data_key_wrapper(self):
        df, _ = load("json_data_key.json")
        assert len(df) == 1
        assert df.loc[0, "pm25"] == 33.0


class TestLongFormat:
    def test_openaq_long_layout_is_pivoted(self):
        df, report = load("long_format.csv")
        assert report["layout"] == "long_pivoted"
        assert report["long_format_parameters"] == ["no2", "o3", "pm10", "pm25"]
        assert len(df) == 2
        assert list(df["pm25"]) == [12.0, 13.0]
        assert list(df["pm10"]) == [24.0, 26.0]
        assert list(df["no2"]) == [8.0, 9.0]
        assert list(df["o3"]) == [40.0, 42.0]
        assert "pressure" not in df.columns


class TestEncodings:
    def test_utf8_bom(self):
        df, _ = load("bom_utf8.csv")
        assert df.loc[0, "pm25"] == 25.0

    def test_mojibake_column_names(self):
        df, _ = load("mojibake_utf8.csv")
        assert df.loc[0, "pm25"] == 30.0

    def test_latin1_fallback(self):
        df, _ = load("latin1_encoded.csv")
        assert df.loc[0, "pm25"] == 25.0
        assert df.loc[0, "temperature"] == 28.0


class TestEdgeCases:
    def test_empty_file(self):
        with pytest.raises(ValueError, match="empty"):
            load("empty.csv")

    def test_header_only_file(self):
        with pytest.raises(ValueError, match="no data rows"):
            load("header_only.csv")

    def test_single_row_file(self):
        df, report = load("single_row.csv")
        assert len(df) == 1
        assert df.loc[0, "pm25"] == 17.0
        assert report["rows_read"] == 1

    def test_excel_renamed_as_csv_is_sniffed(self):
        df, _ = load("renamed_excel.csv")
        assert len(df) == 2
        assert list(df["pm25"]) == [42.0, 47.0]

    def test_json_with_txt_extension_is_sniffed(self):
        df, _ = load("actually_json.txt")
        assert df.loc[0, "pm25"] == 5.0

    def test_500k_rows(self, tmp_path):
        path = tmp_path / "large.csv"
        n = 500_000
        timestamps = pd.date_range("2026-01-01", periods=n, freq="min").strftime("%Y-%m-%dT%H:%M:%SZ")
        pd.DataFrame(
            {
                "timestamp": timestamps,
                "location": "MegaCity",
                "pm25": (np.arange(n) % 100) + 1.0,
                "pm10": (np.arange(n) % 200) + 1.0,
            }
        ).to_csv(path, index=False)

        df, report = clean_dataframe(parse_file(str(path), "air_quality"), "air_quality")
        assert report["rows_read"] == n
        assert report["rows_kept"] == n
        assert len(df) == n


class TestUploadIdempotency:
    def test_file_hash_is_stable(self):
        from app.api.datasets import compute_file_hash

        assert compute_file_hash(b"abc") == compute_file_hash(b"abc")
        assert compute_file_hash(b"abc") != compute_file_hash(b"abd")

    def test_find_active_duplicate_queries_by_hash(self):
        from app.api.datasets import _find_active_duplicate

        fake = AsyncMock()
        fake.datasets.find_one = AsyncMock(return_value={"_id": "x", "status": "completed"})
        result = asyncio.run(_find_active_duplicate(fake, "deadbeef"))
        assert result["status"] == "completed"
        query = fake.datasets.find_one.await_args.args[0]
        assert query["file_hash"] == "deadbeef"

    def test_reupload_returns_existing_dataset(self):
        from bson import ObjectId
        from fastapi.testclient import TestClient

        from app.main import app
        from app.api.datasets import get_database

        existing_id = ObjectId()
        fake = AsyncMock()
        fake.datasets.find_one = AsyncMock(return_value={"_id": existing_id, "status": "completed"})
        app.dependency_overrides[get_database] = lambda: fake
        try:
            client = TestClient(app)
            response = client.post(
                "/api/datasets/upload",
                files={"file": ("again.csv", b"timestamp,location,pm25\n2026-10-01 00:00:00,X,1\n", "text/csv")},
                data={"dataset_type": "air_quality"},
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["duplicate"] is True
        assert body["dataset_id"] == str(existing_id)
        fake.datasets.insert_one.assert_not_called()

    def test_fresh_upload_stores_hash(self, monkeypatch):
        from fastapi.testclient import TestClient

        from app.main import app
        from app.api import datasets as datasets_module
        from app.api.datasets import get_database, compute_file_hash

        hours = 60
        rows = "\n".join(
            f"2026-10-{1 + i // 24:02d}T{i % 24:02d}:00:00Z,IdemCity,{10 + i % 10}.0,20.0"
            for i in range(hours)
        )
        content = f"timestamp,location,pm25,pm10\n{rows}\n".encode()

        fake = AsyncMock()
        fake.datasets.find_one = AsyncMock(return_value=None)
        monkeypatch.setattr(datasets_module.db, "db", fake)
        app.dependency_overrides[get_database] = lambda: fake
        try:
            client = TestClient(app)
            response = client.post(
                "/api/datasets/upload",
                files={"file": ("fresh.csv", content, "text/csv")},
                data={"dataset_type": "air_quality"},
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json()["duplicate"] is False
        inserted = fake.datasets.insert_one.await_args.args[0]
        assert inserted["file_hash"] == compute_file_hash(content, "air_quality")
        assert inserted["pipeline_version"]

    def test_empty_upload_rejected(self):
        from fastapi.testclient import TestClient

        from app.main import app
        from app.api.datasets import get_database

        fake = AsyncMock()
        app.dependency_overrides[get_database] = lambda: fake
        try:
            client = TestClient(app)
            response = client.post(
                "/api/datasets/upload",
                files={"file": ("nothing.csv", b"", "text/csv")},
                data={"dataset_type": "air_quality"},
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()
