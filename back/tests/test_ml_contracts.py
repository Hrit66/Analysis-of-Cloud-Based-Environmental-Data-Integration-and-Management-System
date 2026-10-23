"""ML contracts: eligibility, honest model choice, leakage, determinism."""
import numpy as np
import pandas as pd
import pytest

from app.services.anomaly_detector import (
    detect_water_anomalies,
    detect_weather_anomalies,
)
from app.services.forecaster import (
    generate_forecast,
    purge_dataset_models,
    train_forecast_model,
)
from app.services.water_forecaster import forecast_water_parameter


def _monthly(parameter, values, location="Contract Lake"):
    return pd.DataFrame({
        "timestamp": pd.date_range("2018-01-01", periods=len(values), freq="MS"),
        "location": [location] * len(values),
        parameter: values,
    })


class TestEligibilityGates:
    def test_water_short_history_is_skipped_with_reason(self):
        with pytest.raises(ValueError, match="only 23 months"):
            forecast_water_parameter(_monthly("total_coliform", [1000.0] * 23), "Contract Lake")

    def test_water_gappy_monthly_series_is_skipped_with_reason(self):
        stamps = pd.date_range("2015-01-01", periods=70, freq="MS")[::3][:24]
        df = pd.DataFrame({
            "timestamp": stamps,
            "location": ["Gappy"] * 24,
            "total_coliform": [1000.0] * 24,
        })
        with pytest.raises(ValueError, match="missing share"):
            forecast_water_parameter(df, "Gappy")

    def test_water_eligible_series_publishes_a_reason(self):
        values = [1000.0 * (1.01 ** i) for i in range(36)]
        result = forecast_water_parameter(_monthly("total_coliform", values), "Contract Lake")
        assert result["metrics"]["series_eligibility"] == "eligible"
        assert result["metrics"]["selection_reason"]

    def test_air_short_series_is_skipped_with_reason(self):
        df = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=5, freq="D"),
            "location": ["Short"] * 5,
            "temperature": np.arange(5.0),
        })
        with pytest.raises(ValueError, match="5 points"):
            train_forecast_model(df, "Short", "temperature")

    def test_air_short_span_is_skipped_with_reason(self):
        df = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=24, freq="5h"),
            "location": ["Span"] * 24,
            "temperature": np.arange(24.0),
        })
        with pytest.raises(ValueError, match="span 5 days"):
            train_forecast_model(df, "Span", "temperature")

    def test_air_mostly_missing_series_is_skipped_with_reason(self):
        values = np.arange(100.0)
        values[20:] = np.nan
        df = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=100, freq="D"),
            "location": ["Missing"] * 100,
            "temperature": values,
        })
        with pytest.raises(ValueError, match="missing share 80%"):
            train_forecast_model(df, "Missing", "temperature")


class TestHonestModelChoice:
    def test_water_model_that_loses_to_persistence_publishes_persistence(self):
        values = [1000.0 * (1.02 ** i) for i in range(60)]
        result = forecast_water_parameter(_monthly("total_coliform", values), "Contract Lake")

        assert result["model_used"] == "persistence_baseline"
        assert result["metrics"]["skill_claimed"] is False
        assert result["metrics"]["skill_vs_persistence_pct"] == 0.0
        assert "worse than persistence" in result["metrics"]["selection_reason"]
        assert len({point["predicted_value"] for point in result["predictions"]}) == 1

    def test_air_random_walk_does_not_claim_skill(self):
        rng = np.random.default_rng(42)
        values = 30 + np.cumsum(rng.normal(0, 0.3, 500))
        df = pd.DataFrame({
            "timestamp": pd.date_range("2023-01-01", periods=500, freq="D"),
            "location": ["Random Walk"] * 500,
            "temperature": values,
        })
        purge_dataset_models("rwcontract")
        try:
            result = generate_forecast(
                df, "Random Walk", "temperature", horizon=7, dataset_id="rwcontract"
            )
        finally:
            purge_dataset_models("rwcontract")

        assert result["model_used"] == "persistence_baseline"
        assert result["metrics"]["skill_claimed"] is False
        assert "worse than persistence" in result["metrics"]["selection_reason"]
        assert len({p["predicted_value"] for p in result["predictions"]}) == 1


class TestSyntheticGroundTruth:
    def test_seasonal_model_beats_persistence_and_covers_future(self):
        rng = np.random.default_rng(21)
        days = np.arange(760, dtype=float)
        values = (
            22 + 0.012 * days + 7 * np.sin(2 * np.pi * (days - 100) / 365.25)
            + rng.normal(0, 0.5, 760)
        )
        stamps = pd.date_range("2022-01-01", periods=760, freq="D")
        train = pd.DataFrame({
            "timestamp": stamps[:730],
            "location": ["Ground Truth"] * 730,
            "temperature": values[:730],
        })

        purge_dataset_models("truthcontract")
        try:
            result = generate_forecast(
                train, "Ground Truth", "temperature", horizon=30,
                dataset_id="truthcontract",
            )
        finally:
            purge_dataset_models("truthcontract")

        predicted = np.array([p["predicted_value"] for p in result["predictions"]])
        actual = values[730:]
        persistence = np.full(30, values[729])
        assert np.mean(np.abs(predicted - actual)) < np.mean(np.abs(persistence - actual))
        assert result["metrics"]["skill_claimed"] is True
        assert result["metrics"]["skill_vs_persistence_pct"] > 0

        covered = sum(
            p["lower_bound"] <= truth <= p["upper_bound"]
            for p, truth in zip(result["predictions"], actual)
        ) / len(actual)
        assert 0.7 <= covered <= 0.95


class TestNoLeakage:
    def _frame(self):
        rng = np.random.default_rng(21)
        days = np.arange(730, dtype=float)
        values = (
            22 + 0.015 * days + 7 * np.sin(2 * np.pi * (days - 100) / 365.25)
            + rng.normal(0, 0.6, 730)
        )
        return pd.DataFrame({
            "timestamp": pd.date_range("2022-01-01", periods=730, freq="D"),
            "location": ["Leak City"] * 730,
            "temperature": values,
        })

    def test_row_shuffle_cannot_improve_or_change_the_forecast(self):
        frame = self._frame()
        purge_dataset_models("leakA")
        purge_dataset_models("leakB")
        try:
            original = generate_forecast(
                frame, "Leak City", "temperature", horizon=14, dataset_id="leakA"
            )
            shuffled = generate_forecast(
                frame.sample(frac=1, random_state=3), "Leak City",
                "temperature", horizon=14, dataset_id="leakB",
            )
        finally:
            purge_dataset_models("leakA")
            purge_dataset_models("leakB")

        assert [p["predicted_value"] for p in original["predictions"]] == [
            p["predicted_value"] for p in shuffled["predictions"]
        ]
        assert original["metrics"]["mae"] == shuffled["metrics"]["mae"]

    def test_repeated_runs_are_deterministic(self):
        frame = self._frame()
        purge_dataset_models("determinism")
        try:
            first = generate_forecast(
                frame, "Leak City", "temperature", horizon=14,
                dataset_id="determinism",
            )
            second = generate_forecast(
                frame, "Leak City", "temperature", horizon=14,
                dataset_id="determinism",
            )
        finally:
            purge_dataset_models("determinism")

        assert first["predictions"] == second["predictions"]
        assert first["metrics"]["mae"] == second["metrics"]["mae"]


class TestSyntheticAnomalies:
    def test_weather_injected_spikes_are_found_with_few_false_positives(self):
        rng = np.random.default_rng(7)
        days = np.arange(400, dtype=float)
        values = 25 + 6 * np.sin(2 * np.pi * days / 365.25) + rng.normal(0, 0.4, 400)
        injected = [100, 200, 300]
        for index in injected:
            values[index] += 15

        stamps = pd.date_range("2022-01-01", periods=400, freq="D")
        df = pd.DataFrame({
            "timestamp": stamps,
            "location": ["Spike City"] * 400,
            "temperature": values,
        })

        results = detect_weather_anomalies(df, location="Spike City")
        flagged = {
            result["timestamp"].date().isoformat()
            for result in results if result["is_anomaly"]
        }
        injected_days = {stamps[index].date().isoformat() for index in injected}
        false_positives = flagged - injected_days

        assert injected_days <= flagged
        assert len(false_positives) <= 2

    def test_water_injected_do_extremes_are_found(self):
        rng = np.random.default_rng(8)
        values = 6.5 + rng.normal(0, 0.3, 36)
        values[10] = 0.2
        values[25] = 12.0
        df = pd.DataFrame({
            "timestamp": pd.date_range("2020-01-01", periods=36, freq="MS"),
            "location": ["DO Lake"] * 36,
            "do": values,
        })

        results = detect_water_anomalies(df, location="DO Lake")
        flagged = {
            result["timestamp"].date().isoformat()
            for result in results if result["is_anomaly"]
        }
        injected = {
            df["timestamp"].iloc[10].date().isoformat(),
            df["timestamp"].iloc[25].date().isoformat(),
        }
        assert injected <= flagged


def test_air_anomaly_default_contamination_is_conservative():
    from app.services.anomaly_detector import DEFAULT_CONTAMINATION

    assert 0.01 <= DEFAULT_CONTAMINATION <= 0.05


def test_anomaly_entries_use_real_datetimes():
    import numpy as np
    import pandas as pd

    from app.services.anomaly_detector import detect_anomalies

    rng = np.random.default_rng(7)
    n = 140
    frame = pd.DataFrame({
        "timestamp": pd.date_range("2021-01-01", periods=n, freq="D").astype(str),
        "location": ["A"] * n,
        "pm25": 40 + rng.normal(0, 2, n),
        "pm10": 70 + rng.normal(0, 3, n),
    })
    frame.loc[n - 1, ["pm25", "pm10"]] = [400, 700]
    results = detect_anomalies(frame, location="A", scope="test_time_types")
    assert results
    assert all(hasattr(item["timestamp"], "year") for item in results)
