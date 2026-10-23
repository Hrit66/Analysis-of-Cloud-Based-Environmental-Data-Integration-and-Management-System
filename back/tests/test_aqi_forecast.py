import glob
import os

import numpy as np
import pandas as pd
import pytest

from app.services.forecaster import (
    AQI_FORECAST_MIN_DAYS,
    FORECAST_MODEL_PREFIX,
    MODEL_DIR,
    _load_metadata,
    _save_metadata,
    aqi_category_chances,
    generate_forecast,
    train_forecast_model,
)


def _cleanup(dataset_id: str) -> None:
    for path in glob.glob(os.path.join(MODEL_DIR, f"{FORECAST_MODEL_PREFIX}{dataset_id}_*")):
        os.remove(path)
    metadata = _load_metadata()
    for key in [key for key in metadata if key.startswith(f"{dataset_id}_")]:
        metadata.pop(key)
    _save_metadata(metadata)


def _seasonal_aqi_frame(location: str, periods: int = 800) -> pd.DataFrame:
    days = np.arange(periods, dtype=float)
    rng = np.random.default_rng(11)
    values = 150 + 40 * np.sin(2 * np.pi * days / 365.25) + rng.normal(0, 4, periods)
    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=periods, freq="D"),
        "location": [location] * periods,
        "aqi": values,
    })


def test_category_chances_are_a_distribution():
    chances = aqi_category_chances(195, 45)
    assert sum(chances.values()) == pytest.approx(100.0, abs=0.01)
    assert "Moderate" in chances
    assert "Poor" in chances
    assert all(0 < value <= 100 for value in chances.values())


def test_category_chances_rounding_still_totals_100():
    for value in (50.26, 100.5, 178, 201, 399.9, 500):
        chances = aqi_category_chances(value, 45)
        assert sum(chances.values()) == pytest.approx(100.0, abs=0.01)
        assert all(0 < chance <= 100 for chance in chances.values())


def test_aqi_forecast_requires_two_years():
    dataset_id = "unittest_aqi_short"
    df = _seasonal_aqi_frame("Short", periods=AQI_FORECAST_MIN_DAYS - 1)
    try:
        train_forecast_model(df, "Short", "aqi", dataset_id=dataset_id)
    except ValueError as exc:
        assert "2 years" in str(exc)
    else:
        raise AssertionError("short AQI history should not train")
    finally:
        _cleanup(dataset_id)


def test_aqi_forecast_publishes_ranges_and_category_chances():
    dataset_id = "unittest_aqi_publish"
    df = _seasonal_aqi_frame("Seasonal")
    try:
        _, metrics = train_forecast_model(df, "Seasonal", "aqi", dataset_id=dataset_id)
        assert metrics["forecast_published"] is True
        assert metrics["baseline_last7_mean_mae"] is not None
        assert metrics["horizon_last7_mean_mae"]
        result = generate_forecast(df, "Seasonal", "aqi", dataset_id=dataset_id)
        assert result["metrics"]["skill_vs_better_baseline_pct"] > 0
        for point in result["predictions"]:
            assert point["lower_bound"] <= point["predicted_value"] <= point["upper_bound"]
            assert sum(point["category_probabilities"].values()) == pytest.approx(100.0, abs=0.5)
    finally:
        _cleanup(dataset_id)


def test_aqi_forecast_hidden_without_skill_over_both_baselines():
    dataset_id = "unittest_aqi_hidden"
    periods = AQI_FORECAST_MIN_DAYS + 30
    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=periods, freq="D"),
        "location": ["Flat"] * periods,
        "aqi": np.full(periods, 100.0),
    })
    try:
        _, metrics = train_forecast_model(df, "Flat", "aqi", dataset_id=dataset_id)
        assert metrics["forecast_published"] is False
        assert metrics["baseline_persistence_mae"] == 0.0
        with pytest.raises(ValueError, match="hidden"):
            generate_forecast(df, "Flat", "aqi", dataset_id=dataset_id)
    finally:
        _cleanup(dataset_id)
