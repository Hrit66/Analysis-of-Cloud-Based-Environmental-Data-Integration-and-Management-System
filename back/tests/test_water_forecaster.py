"""Monthly coliform outlook (log1p space) - unit + real-file anchors."""
import math
from pathlib import Path

import pandas as pd
import pytest

from app.services.water_forecaster import (
    MIN_MONTHS_FOR_OUTLOOK,
    _monthly_log_series,
    forecast_coliform,
    forecast_water_parameter,
    generate_coliform_forecasts,
    generate_water_forecasts,
)

REAL_FILE = Path("/home/vergil/Downloads/waterKarna.csv")


def _monthly_frame(location, values, start="2018-01-01"):
    stamps = pd.date_range(start, periods=len(values), freq="MS")
    return pd.DataFrame({"timestamp": stamps, "location": location, "total_coliform": values})


def _monthly_frame_for(location, values, parameter, start="2018-01-01"):
    stamps = pd.date_range(start, periods=len(values), freq="MS")
    return pd.DataFrame({"timestamp": stamps, "location": location, parameter: values})


class TestMonthlyAggregation:
    def test_multiple_samples_in_a_month_are_averaged_in_log_space(self):
        df = pd.DataFrame({
            "timestamp": pd.to_datetime(["2018-01-05", "2018-01-25", "2018-02-10"]),
            "location": ["Lake"] * 3,
            "total_coliform": [100.0, 10000.0, 500.0],
        })
        values, days, months, raw = _monthly_log_series(df, "Lake")

        assert raw == 3
        assert len(values) == 2
        assert values[0] == pytest.approx((math.log1p(100.0) + math.log1p(10000.0)) / 2)
        assert values[1] == pytest.approx(math.log1p(500.0))
        assert days[0] == 0.0 and days[1] > 0

    def test_rows_without_coliform_are_ignored(self):
        df = pd.DataFrame({
            "timestamp": pd.to_datetime(["2018-01-05", "2018-02-10"]),
            "location": ["Lake"] * 2,
            "total_coliform": [100.0, None],
        })
        values, *_ = _monthly_log_series(df, "Lake")
        assert len(values) == 1


class TestOutlookShape:
    def test_insufficient_history_is_rejected(self):
        df = _monthly_frame("Short-Lake", [1000.0] * (MIN_MONTHS_FOR_OUTLOOK - 1))
        with pytest.raises(ValueError, match="Insufficient monthly coliform history"):
            forecast_coliform(df, "Short-Lake")

    def test_predictions_are_future_month_starts_with_ordered_bounds(self):
        values = [1000.0 * (1.02 ** i) for i in range(30)]
        df = _monthly_frame("Rising-Lake", values, start="2018-01-01")
        result = forecast_coliform(df, "Rising-Lake")

        assert result["model_used"] in {
            "SimpleExponentialSmoothing_log1p", "persistence_baseline",
        }
        assert result["metrics"]["selection_reason"]
        assert result["forecast_horizon"] == 3
        predictions = result["predictions"]
        assert [p["timestamp"][:7] for p in predictions] == ["2020-07", "2020-08", "2020-09"]
        for point in predictions:
            assert point["lower_bound"] >= 0.0
            assert point["lower_bound"] <= point["predicted_value"] <= point["upper_bound"]

    def test_flat_series_triggers_the_persistence_note(self):
        df = _monthly_frame("Flat-Lake", [50000.0] * 30)
        result = forecast_coliform(df, "Flat-Lake")
        metrics = result["metrics"]
        assert "persistence" in metrics["limitation"]
        assert "broad level indicator" in metrics["limitation"]
        assert metrics["horizon_mae"][0] >= metrics["horizon_persistence_mae"][0]
        assert len(metrics["horizon_mae"]) == 3
        assert len(metrics["horizon_persistence_mae"]) == 3

    def test_billion_scale_mpn_values_are_supported(self):
        values = [1000.0] * 29 + [9.2e9]
        df = _monthly_frame("Big-Lake", values)
        result = forecast_coliform(df, "Big-Lake")
        assert len(result["predictions"]) == 3
        assert result["predictions"][0]["upper_bound"] > 0

    def test_generate_skips_short_stations_and_attaches_dataset_id(self):
        long_df = _monthly_frame("Long-Lake", [1000.0] * 30)
        short_df = _monthly_frame("Short-Lake", [1000.0] * 12)
        df = pd.concat([long_df, short_df], ignore_index=True)

        docs = generate_coliform_forecasts(df, dataset_id="ds-1")
        assert [doc["location"] for doc in docs] == ["Long-Lake"]
        assert docs[0]["dataset_id"] == "ds-1"
        assert docs[0]["created_at"]


class TestNativeUnitOutlooks:
    """DO and WQI are modelled in native units, not log1p."""

    def test_do_outlook_is_native_and_bounded(self):
        values = [5.0 + 0.01 * i for i in range(30)]
        result = forecast_water_parameter(_monthly_frame_for("DO-Lake", values, "do"), "DO-Lake", "do")

        assert result["parameter"] == "do"
        assert result["model_used"] in {
            "SimpleExponentialSmoothing", "persistence_baseline",
        }
        metrics = result["metrics"]
        assert metrics["selection_reason"]
        assert metrics["scale"] == "native"
        assert metrics["units"] == "mg/L"
        assert metrics["mae_multiplicative_factor"] is None
        assert "dissolved oxygen" in metrics["model_note"]
        assert result["predictions"][0]["timestamp"][:7] == "2020-07"
        for point in result["predictions"]:
            assert 0.0 <= point["lower_bound"] <= point["predicted_value"] <= point["upper_bound"]
            assert round(point["predicted_value"], 2) == point["predicted_value"]

    def test_wqi_outlook_units_and_precision(self):
        values = [100.0 + (i % 5) for i in range(30)]
        result = forecast_water_parameter(_monthly_frame_for("WQI-Lake", values, "wqi"), "WQI-Lake", "wqi")

        assert result["parameter"] == "wqi"
        assert result["metrics"]["units"] == "index points (0-200)"
        assert result["metrics"]["scale"] == "native"
        for point in result["predictions"]:
            assert point["lower_bound"] >= 0.0
            assert round(point["upper_bound"], 2) == point["upper_bound"]

    def test_persistence_note_is_used_for_native_series_too(self):
        result = forecast_water_parameter(
            _monthly_frame_for("Flat-DO", [6.0] * 30, "do"), "Flat-DO", "do"
        )
        metrics = result["metrics"]
        assert metrics["horizon_mae"][0] >= metrics["horizon_persistence_mae"][0]
        assert "broad level indicator" in metrics["limitation"]

    def test_insufficient_history_is_rejected_per_parameter(self):
        df = _monthly_frame_for("Short-DO", [6.0] * (MIN_MONTHS_FOR_OUTLOOK - 1), "do")
        with pytest.raises(ValueError, match="Insufficient monthly dissolved oxygen history"):
            forecast_water_parameter(df, "Short-DO", "do")

    def test_unsupported_parameter_is_rejected(self):
        df = _monthly_frame_for("Lake", [6.0] * 30, "ph")
        with pytest.raises(ValueError, match="Unsupported water forecast parameter"):
            forecast_water_parameter(df, "Lake", "ph")

    def test_generate_covers_all_three_parameters(self):
        long_df = _monthly_frame_for("Long-Lake", [1000.0 * (1.01 ** i) for i in range(30)], "total_coliform")
        long_df["do"] = [5.0 + 0.01 * i for i in range(30)]
        long_df["wqi"] = [100.0 + (i % 5) for i in range(30)]
        short_df = _monthly_frame_for("Short-Lake", [6.0] * 12, "do")
        df = pd.concat([long_df, short_df], ignore_index=True)

        docs = generate_water_forecasts(df, dataset_id="ds-2")
        assert sorted((doc["location"], doc["parameter"]) for doc in docs) == [
            ("Long-Lake", "do"), ("Long-Lake", "total_coliform"), ("Long-Lake", "wqi"),
        ]
        assert all(doc["dataset_id"] == "ds-2" for doc in docs)


@pytest.mark.skipif(not REAL_FILE.exists(), reason="local CPCB file not present on this machine")
class TestRealAllasandraOutlook:
    """Anchors: log1p monthly outlook on the user's own CPCB file."""

    @pytest.fixture(scope="class")
    def result(self):
        from app.services.pipeline_interface import clean_dataframe

        cleaned, _ = clean_dataframe(pd.read_csv(REAL_FILE), "water_quality")
        return forecast_coliform(cleaned, "ALLASANDRA TANK")

    def test_monthly_series_shape(self, result):
        metrics = result["metrics"]
        assert metrics["monthly_points"] == 44
        assert metrics["sample_count"] == 44
        assert metrics["first_month"] == "2018-01"
        assert metrics["last_month"] == "2021-12"

    def test_rolling_origin_vs_persistence_numbers(self, result):
        metrics = result["metrics"]
        assert metrics["rolling_origins"] == 15
        assert metrics["horizon_mae"] == pytest.approx([2.202, 2.406, 2.481], abs=0.03)
        assert metrics["horizon_persistence_mae"] == pytest.approx([2.148, 2.885, 2.988], abs=0.03)
        # Persistence wins at the 1-month horizon on this data; the honest note says so.
        assert metrics["horizon_mae"][0] >= metrics["horizon_persistence_mae"][0]
        assert "no meaningful gain over persistence" in metrics["limitation"]
        # The model still wins on the longer horizons, but errors are large.
        assert metrics["mae_multiplicative_factor"] > 5

    def test_next_three_months_predictions(self, result):
        predictions = result["predictions"]
        assert [p["timestamp"][:7] for p in predictions] == ["2022-01", "2022-02", "2022-03"]
        assert all(p["predicted_value"] == pytest.approx(103230, rel=0.01) for p in predictions)
        assert result["metrics"]["interval_coverage_pct"] == 80.0
