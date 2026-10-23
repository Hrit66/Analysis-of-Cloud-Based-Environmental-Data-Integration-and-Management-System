"""River-year summary importer: CPCB-style wide sheets become water-quality records."""
from pathlib import Path
from unittest.mock import AsyncMock

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.api.datasets import get_database
from app.main import app
from app.services.pipeline_interface import (
    clean_dataframe,
    dataframe_to_records,
    merge_river_summary_files,
)

FIXTURES = Path(__file__).parent / "fixtures"
RIVER_CSV = FIXTURES / "river_summary_sample.csv"


class TestRiverSummaryParser:
    def test_merges_years_and_maps_cpcb_headers(self):
        merged, meta = merge_river_summary_files([str(RIVER_CSV)])

        assert meta["source_format"] == "river_summary"
        assert list(merged.columns) == ["timestamp", "location", "ph", "do", "bod", "conductivity", "total_coliform"]
        assert sorted(merged["location"].unique()) == ["Ganga", "Yamuna"]
        assert any(str(ts).startswith("2020-07-01") for ts in merged["timestamp"])
        assert meta["columns_not_imported"] == []
        assert meta["columns_mapped"]["Dissolved Oxygen (mg/L)"] == "do"
        assert meta["columns_mapped"]["Conductivity (µmhos/cm)"] == "conductivity"
        assert meta["columns_mapped"]["Total Coliform (MPN/100ml)"] == "total_coliform"

    def test_cleaned_records_are_water_quality_shaped(self):
        merged, meta = merge_river_summary_files([str(RIVER_CSV)])
        cleaned, report = clean_dataframe(merged, "water_quality", extra_report=meta)

        assert report["source_format"] == "river_summary"
        assert report["rows_kept"] == 4

        records = dataframe_to_records(cleaned, "ds", "water_quality")
        assert len(records) == 4
        assert records[0]["location"] == "Ganga"
        assert records[0]["ph"] == pytest.approx(8.1)
        assert records[0]["do"] == pytest.approx(7.4)
        assert records[0]["bod"] == pytest.approx(2.5)
        assert records[0]["total_coliform"] == pytest.approx(1700)

    def test_rejects_file_without_river_or_year_column(self, tmp_path):
        plain = tmp_path / "plain.csv"
        plain.write_text("timestamp,location,ph\n2020-01-01,X,7.0\n")

        with pytest.raises(ValueError, match="does not look like a river-year summary"):
            merge_river_summary_files([str(plain)])


class TestErrorMessages:
    def test_wrong_tab_suggests_river_importer(self):
        df = pd.DataFrame({"Name of the River": ["Ganga"], "Year": [2020], "pH": [8.0]})

        with pytest.raises(ValueError) as excinfo:
            clean_dataframe(df, "water_quality")

        message = str(excinfo.value)
        assert "river-year summary" in message
        assert "river-summary importer" in message
        assert "Name of the River, Year, pH" in message

    def test_missing_timestamp_message_lists_found_columns(self):
        df = pd.DataFrame({"ph": [8.0], "do": [7.0]})

        with pytest.raises(ValueError) as excinfo:
            clean_dataframe(df, "water_quality")

        assert "missing required columns: timestamp (found: ph, do)" in str(excinfo.value)


class TestRiverSummaryEndpoint:
    def _client(self, fake):
        app.dependency_overrides[get_database] = lambda: fake
        return TestClient(app)

    def test_upload_pivots_and_stores(self, monkeypatch):
        from app.api import datasets as datasets_module

        fake = AsyncMock()
        fake.datasets.find_one = AsyncMock(return_value=None)
        monkeypatch.setattr(datasets_module.db, "db", fake)

        client = self._client(fake)
        try:
            with open(RIVER_CSV, "rb") as handle:
                response = client.post(
                    "/api/datasets/upload-river-summary",
                    files=[("files", ("river_summary_sample.csv", handle.read(), "text/csv"))],
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["dataset_type"] == "water_quality"
        assert body["duplicate"] is False

        inserted = fake.datasets.insert_one.await_args.args[0]
        assert inserted["dataset_type"] == "water_quality"
        assert inserted["filename"].startswith("River summary: ")

        assert fake.water_quality.insert_many.await_count >= 1
        records = fake.water_quality.insert_many.await_args_list[0].args[0]
        assert len(records) == 4
        assert records[0]["dataset_id"] == body["dataset_id"]
        assert records[0]["wqi"] is not None

        completed = fake.datasets.update_one.await_args_list[-1].args[1]["$set"]
        assert completed["status"] == "completed"
        assert completed["capabilities"] == ["water_quality"]
        assert completed["display_name"].startswith("River year summary")

    def test_rejects_unsupported_extension(self):
        fake = AsyncMock()
        fake.datasets.find_one = AsyncMock(return_value=None)
        client = self._client(fake)
        try:
            response = client.post(
                "/api/datasets/upload-river-summary",
                files=[("files", ("summary.txt", b"Name of the River,Year\nGanga,2020\n", "text/plain"))],
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 400
        assert "CSV or Excel" in response.json()["detail"]
