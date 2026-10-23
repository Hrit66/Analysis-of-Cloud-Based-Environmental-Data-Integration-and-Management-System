"""Generated-fixture zoo: every awkward shape has a known contract."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.services.pipeline_interface import (
    clean_dataframe,
    merge_imd_files,
    parse_file,
)
from app.services.type_detector import detect_dataset_type
from tests.dataset_zoo import build_zoo


@pytest.fixture(scope="module")
def zoo(tmp_path_factory):
    return build_zoo(tmp_path_factory.mktemp("dataset_zoo"))


def _load(zoo, name, dataset_type, **kwargs):
    return clean_dataframe(
        parse_file(str(zoo[name]), dataset_type), dataset_type, **kwargs
    )


class TestWaterShapes:
    def test_wide_duplicate_rows_are_averaged_not_silently_kept(self, zoo):
        df, report = _load(zoo, "clean_water_wide", "water_quality")

        assert report["rows_read"] == 7
        assert report["duplicates_removed"] == 1
        assert report["duplicates_averaged"] == 1
        assert len(df) == 6
        first = df.iloc[0]
        assert first["do"] == pytest.approx(7.0)  # (6.5 + 7.5) / 2
        assert first["ph"] == 7.2
        assert df.iloc[1]["nitrates"] == pytest.approx(0.25)  # "<0.5" halved
        assert np.isnan(df.iloc[3]["nitrates"])  # "ND"

    def test_long_layout_is_pivoted_before_cleaning(self, zoo):
        df, report = _load(zoo, "water_long", "water_quality", source_name="water_long.csv")

        assert report["layout"] == "long_pivoted"
        assert len(df) == 2
        assert set(report["long_format_parameters"]) == {"do", "nitrates", "ph"}
        assert df.iloc[0]["do"] == 6.5
        assert df.iloc[0]["nitrates"] == 2.0

    def test_header_synonyms_merge_into_one_parameter_column(self, zoo):
        df, report = _load(zoo, "water_synonyms", "water_quality")

        assert report["synonym_columns_merged"]["do"] == [
            "DO_mgl", "d.o.", "Dissolved Oxygen (mg/L)",
        ]
        assert report["columns_renamed"]["f"] == "fluorides"
        assert list(df["do"]) == [6.5, 6.1]
        assert list(df["fluorides"]) == [1.2, 1.4]

    def test_unknown_columns_are_reported_not_dropped_silently(self, zoo):
        df, report = _load(zoo, "wide_200", "air_quality")

        assert len(df) == 4
        assert len(report["columns_dropped"]) == 197
        assert all(column.startswith("junk_") for column in report["columns_dropped"])


class TestTypeDetection:
    def test_air_columns_win_over_a_water_filename(self, zoo):
        raw = parse_file(str(zoo["air_quality_units"]), "air_quality")
        detection = detect_dataset_type(raw.columns, "water_export.csv")

        assert detection["dataset_type"] == "air_quality"
        assert detection["scores"]["air_quality"] == 3

    def test_ambiguous_mixed_file_is_flagged_for_override(self, zoo):
        raw = parse_file(str(zoo["mixed_headers"]), "water_quality")
        detection = detect_dataset_type(raw.columns, "mixed.csv")

        assert detection["ambiguous"] is True
        assert detection["scores"]["air_quality"] == 2
        assert detection["scores"]["water_quality"] == 2

    def test_garbage_headers_have_no_recognised_type(self, zoo):
        raw = parse_file(str(zoo["garbage_text"]), "air_quality")
        detection = detect_dataset_type(raw.columns, "garbage.csv")

        assert detection["ambiguous"] is True
        assert detection["confidence"] == 0.0
        with pytest.raises(ValueError, match="does not look like air_quality"):
            clean_dataframe(raw, "air_quality")


class TestDatesAndUnits:
    def test_ambiguous_dates_warn_and_choose_month_first(self, zoo):
        df, report = _load(zoo, "ambiguous_dates", "air_quality")

        assert report["date_format"]["confidence"] == "ambiguous"
        assert report["date_format"]["warning"]
        assert report["ambiguous_date_strings"] == 3
        assert df.iloc[0]["timestamp"] == "2021-01-02T00:00:00Z"

    def test_day_above_twelve_proves_day_first(self, zoo):
        df, report = _load(zoo, "day_first_dates", "air_quality")

        assert report["date_format"]["dayfirst"] is True
        assert report["date_format"]["confidence"] == "inferred"
        assert report["date_format"]["confidence"] == "inferred"
        assert df.iloc[0]["timestamp"] == "2021-01-13T00:00:00Z"

    def test_fahrenheit_is_converted_before_range_checks(self, zoo):
        df, report = _load(zoo, "temperature_f", "temperature")

        assert report["units_detected"]["temperature"]["source_unit"] == "°F"
        assert report["unit_conversions"]["temperature"] == "converted °F to °C"
        assert list(df["temperature"]) == [20.0, 25.0, 10.0]

    def test_mg_per_m3_is_converted_to_ug_per_m3(self, zoo):
        df, report = _load(zoo, "air_quality_units", "air_quality")

        assert report["units_detected"]["pm10"]["conversion"] == "mg_per_m3_to_ug_per_m3"
        assert list(df["pm10"]) == [80.0, 90.0, 110.0, 70.0, 120.0]
        assert list(df["pm25"]) == [35.0, 42.0, 55.0, 28.0, 61.0]

    def test_missing_units_are_recorded_as_assumed(self, zoo):
        _, report = _load(zoo, "tiny_air", "air_quality")

        entry = report["units_detected"]["pm25"]
        assert entry["unit"] == "µg/m³"
        assert entry["confidence"] == "assumed"
        assert entry["converted"] is False


class TestMissingStationAndTinyFiles:
    def test_missing_station_uses_the_upload_location_and_says_so(self, zoo):
        df, report = _load(
            zoo, "no_station", "air_quality", default_location="Fallback Site"
        )

        assert report["location_source"] == "upload_field"
        assert set(df["location"]) == {"Fallback Site"}
        assert len(df) == 3

    def test_tiny_five_row_file_still_imports(self, zoo):
        df, report = _load(zoo, "tiny_air", "air_quality")

        assert len(df) == 5
        assert report["rows_read"] == 5

    def test_irregular_timestamps_are_kept(self, zoo):
        df, report = _load(zoo, "irregular_dates", "air_quality")

        assert len(df) == 5
        assert report["rows_dropped"] == {}


class TestAdversarialFiles:
    def test_duplicate_headers_merge_without_crashing(self, zoo):
        df, report = _load(zoo, "duplicate_headers", "air_quality")

        assert len(df) == 2
        assert report["duplicates_removed"] == 1
        assert report["synonym_columns_merged"]["pm25"] == ["PM2.5", "PM2.5.1"]

    def test_all_text_garbage_fails_with_a_clear_value_error(self, zoo):
        raw = parse_file(str(zoo["garbage_text"]), "water_quality")
        with pytest.raises(ValueError, match="does not look like water_quality"):
            clean_dataframe(raw, "water_quality")


class TestIMD:
    def test_two_column_imd_files_merge_by_date(self, zoo):
        merged, meta = merge_imd_files(
            [str(zoo["imd_rain"]), str(zoo["imd_tmax"])]
        )
        df, report = clean_dataframe(merged, "temperature", extra_report=meta)

        assert report["source_format"] == "imd_merged"
        assert report["imd_parameters"] == ["precipitation", "temp_max"]
        assert len(df) == 3
        assert set(df["location"]) == {"12.97 77.59"}
        assert list(df["precipitation"]) == [0.0, 12.5, 0.0]
        assert list(df["temp_max"]) == [28.0, 27.5, 29.0]


class TestRealWaterRegression:
    def test_waterkarna_still_imports_when_present(self, zoo):
        source = Path("/home/vergil/Downloads/waterKarna.csv")
        if not source.exists():
            pytest.skip("waterKarna.csv not present on this machine")

        raw = parse_file(str(source), "water_quality")
        df, report = clean_dataframe(raw, "water_quality", source_name=source.name)

        assert len(df) > 3000
        assert report["columns_renamed"]
        assert "fluorides" in df.columns
        assert df["fluorides"].notna().sum() > 800
        assert report["date_format"]["confidence"] == "iso"
