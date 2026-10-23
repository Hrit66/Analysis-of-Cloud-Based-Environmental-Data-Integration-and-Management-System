"""Robust z-score anomaly detection for DO and WQI water series."""
import numpy as np
import pandas as pd

from app.services.anomaly_detector import (
    WATER_MIN_POINTS,
    WATER_Z_THRESHOLD,
    detect_water_anomalies,
    get_model_metadata,
)


def _series_frame(location, values, parameter="do", start="2018-01-05", freq="MS"):
    stamps = pd.date_range(start, periods=len(values), freq=freq)
    return pd.DataFrame({"timestamp": stamps, "location": location, parameter: values})


def _baseline_with_extremes(extreme_low, extreme_high, n=18):
    values = [4.8 if i % 2 == 0 else 5.2 for i in range(n)]
    values.append(extreme_low)
    values.append(extreme_high)
    return values


class TestDoAnomalies:
    def test_extremes_are_flagged_with_direction(self):
        values = _baseline_with_extremes(1.5, 9.0)
        results = detect_water_anomalies(_series_frame("Lake-A", values), location="Lake-A")

        assert len(results) == len(values)
        flagged = [r for r in results if r["is_anomaly"]]
        assert len(flagged) == 2
        by_value = {r["value"]: r for r in flagged}
        assert by_value[1.5]["kind"] == "unusually_low"
        assert by_value[1.5]["anomaly_score"] < -WATER_Z_THRESHOLD
        assert by_value[9.0]["kind"] == "unusually_high"
        assert by_value[9.0]["anomaly_score"] > WATER_Z_THRESHOLD

    def test_entry_schema_matches_weather_anomalies(self):
        results = detect_water_anomalies(
            _series_frame("Lake-A", _baseline_with_extremes(1.5, 9.0)), location="Lake-A"
        )
        entry = results[0]

        assert entry["detector"] == "robust_zscore"
        assert entry["threshold"] == WATER_Z_THRESHOLD
        assert entry["parameter"] == "do"
        assert entry["location"] == "Lake-A"
        assert entry["is_anomaly"] is False
        assert "kind" not in entry  # only flagged samples carry a direction tag

    def test_short_series_are_skipped(self):
        values = [5.0] * (WATER_MIN_POINTS - 1)
        assert detect_water_anomalies(_series_frame("Lake-Short", values), location="Lake-Short") == []


class TestWqiAnomalies:
    def test_wqi_column_is_scored_too(self):
        values = _baseline_with_extremes(1.5, 9.0)
        frame = _series_frame("Lake-B", [v * 20 for v in values], parameter="wqi")
        results = detect_water_anomalies(frame, location="Lake-B")

        assert {r["parameter"] for r in results} == {"wqi"}
        assert sum(r["is_anomaly"] for r in results) == 2

    def test_both_parameters_are_emitted_when_both_columns_exist(self):
        frame = _series_frame("Lake-C", _baseline_with_extremes(1.5, 9.0), parameter="do")
        frame["wqi"] = [v * 20 for v in frame["do"]]
        results = detect_water_anomalies(frame, location="Lake-C")

        assert {r["parameter"] for r in results} == {"do", "wqi"}
        assert len(results) == 2 * len(frame)


class TestScopeMetadata:
    def test_scope_records_series_methods(self):
        scope = "water_unit_scope"
        values = _baseline_with_extremes(1.5, 9.0)
        results = detect_water_anomalies(_series_frame("Lake-D", values), location="Lake-D", scope=scope)
        metadata = get_model_metadata()["Lake-D__" + scope]

        assert metadata["method"] == "robust_zscore_threshold"
        series = metadata["series"]["do"]
        assert series["points"] == len(values)
        assert series["flagged"] == 2
        assert series["z_threshold"] == WATER_Z_THRESHOLD
        assert sum(r["is_anomaly"] for r in results) == 2
