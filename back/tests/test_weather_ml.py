"""Tests for ML features on weather series: anomaly detection and forecasting."""
import glob
import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest


def _reset_dataset_models(dataset_id: str) -> None:
    """Remove persisted artifacts for a test dataset so forecasts are freshly
    trained (stale metadata from previous runs would otherwise be reused)."""
    from app.services import forecaster

    pattern = os.path.join(forecaster.MODEL_DIR, f"{forecaster.FORECAST_MODEL_PREFIX}{dataset_id}_*")
    for path in glob.glob(pattern):
        os.remove(path)
    metadata = forecaster._load_metadata()
    for key in [k for k in metadata if k.startswith(f"{dataset_id}_")]:
        metadata.pop(key)
    forecaster._save_metadata(metadata)


def _weather_frame(location: str, periods: int = 730, start: str = '2023-01-01', seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    timestamps = pd.date_range(start, periods=periods, freq='D')
    days = np.arange(periods, dtype=float)
    temperature = 25.0 + 8.0 * np.sin(2 * np.pi * (days - 90) / 365.25) + rng.normal(0, 0.3, periods)
    return pd.DataFrame({
        'timestamp': timestamps,
        'location': [location] * periods,
        'temperature': temperature,
    })


class TestWeatherAnomalyDetection:
    def test_detect_temperature_anomalies(self):
        from app.services.anomaly_detector import detect_anomalies

        df = _weather_frame('Weather-City')
        spike_indices = [100, 250, 400, 520]
        df.loc[spike_indices, 'temperature'] += 20.0

        results = detect_anomalies(df, location='Weather-City', scope='weather_test_unit')
        assert len(results) == len(df)
        assert {r['parameter'] for r in results} == {'temperature'}
        assert all(r['location'] == 'Weather-City' for r in results)

        spike_timestamps = {df.loc[i, 'timestamp'] for i in spike_indices}
        flagged = {r['timestamp'] for r in results if r['is_anomaly']}
        assert len(flagged & spike_timestamps) >= len(spike_indices) // 2

    def test_reuse_guard_retrains_when_features_missing(self):
        from app.services.anomaly_detector import detect_anomalies, get_model_metadata

        scope = 'weather_reuse_unit'
        df = _weather_frame('Reuse-City', periods=120)
        detect_anomalies(df, location='Reuse-City', scope=scope)
        key = f"Reuse-City__{scope}"
        assert get_model_metadata()[key]['feature_columns'] == ['temperature']

        pollutant_df = pd.DataFrame({
            'timestamp': pd.date_range('2024-01-01', periods=120, freq='D'),
            'location': ['Reuse-City'] * 120,
            'pm25': np.random.default_rng(3).normal(50, 5, 120),
        })
        detect_anomalies(pollutant_df, location='Reuse-City', scope=scope)
        assert get_model_metadata()[key]['feature_columns'] == ['pm25']

    def test_pollutant_and_weather_models_stay_separate(self):
        from app.services.anomaly_detector import detect_anomalies, get_model_metadata

        weather_scope = 'weather_separation_unit'
        df = _weather_frame('Shared-City', periods=120)
        detect_anomalies(df, location='Shared-City', scope=weather_scope)

        metadata = get_model_metadata()
        assert f"Shared-City__{weather_scope}" in metadata
        assert 'Shared-City' not in metadata or metadata['Shared-City'] is not None


class TestWeatherResidualAnomalies:
    def test_deseasonalised_flags_are_rare_and_catch_spikes(self):
        from app.services.anomaly_detector import detect_weather_anomalies

        df = _weather_frame('Resid-City')
        spike_indices = [20, 300, 600]
        df.loc[spike_indices, 'temperature'] += 15.0

        results = detect_weather_anomalies(df, location='Resid-City', scope='weather_resid_unit')
        assert results
        assert {r['parameter'] for r in results} == {'temperature'}
        assert all(r['detector'] == 'seasonal_residual' for r in results)

        flagged = {r['timestamp'].replace(tzinfo=None) for r in results if r['is_anomaly']}
        spike_timestamps = {df.loc[i, 'timestamp'].to_pydatetime() for i in spike_indices}
        assert len(flagged & spike_timestamps) >= 2
        assert len(flagged) / len(results) < 0.02

    def test_heavy_rain_day_tagged_as_event_not_error(self):
        from app.services.anomaly_detector import detect_weather_anomalies

        periods = 400
        df = pd.DataFrame({
            'timestamp': pd.date_range('2024-01-01', periods=periods, freq='D'),
            'location': ['Rain-Resid-City'] * periods,
            'precipitation': np.zeros(periods),
        })
        df.loc[200, 'precipitation'] = 180.0

        results = detect_weather_anomalies(df, location='Rain-Resid-City')
        heavy = [r for r in results if r.get('kind') == 'heavy_rain']
        assert len(heavy) == 1
        assert heavy[0]['is_anomaly'] is True
        assert heavy[0]['value'] == 180.0
        emitted_kinds = {r.get('kind') for r in results}
        assert emitted_kinds == {'heavy_rain', None}


class TestTemperatureForecast:
    @pytest.fixture(autouse=True)
    def _fresh_forecast_artifacts(self):
        _reset_dataset_models('unittestds')
        yield

    def test_harmonic_forecast_future_timestamps(self):
        from app.services.forecaster import generate_forecast

        df = _weather_frame('Forecast-City')
        result = generate_forecast(df, 'Forecast-City', 'temperature', horizon=7, dataset_id='unittestds')

        assert result['model_used'] == 'HarmonicRegression'
        assert result['forecast_horizon'] == 7
        predictions = result['predictions']
        assert len(predictions) == 7

        last_observed = df['timestamp'].max().to_pydatetime()
        times = [datetime.fromisoformat(p['timestamp'].rstrip('Z')) for p in predictions]
        assert times[0] > last_observed
        for earlier, later in zip(times, times[1:]):
            assert (later - earlier) == timedelta(days=1)

        values = [p['predicted_value'] for p in predictions]
        assert all(10.0 < v < 40.0 for v in values)
        metrics = result['metrics']
        assert metrics['mae'] < 2.0
        assert metrics['training_samples'] > 500
        assert metrics['baseline_persistence_mae'] is not None
        assert 'rolling-origin' in metrics['evaluation']
        assert len(metrics['horizon_mae']) == 7
        assert len(metrics['horizon_persistence_mae']) == 7
        assert metrics['interval_coverage_pct'] is not None
        assert 70 <= metrics['interval_coverage_pct'] <= 95
        assert metrics['baseline_zero_mae'] is not None
        for p in predictions:
            assert p['lower_bound'] < p['predicted_value'] < p['upper_bound']

    def test_forecast_beats_persistence_baseline(self):
        """Regression guard: the seasonal model must beat 'repeat yesterday'
        on a series with clear trend and seasonality, evaluated rolling-origin."""
        from app.services.forecaster import generate_forecast

        rng = np.random.default_rng(21)
        periods = 730
        days = np.arange(periods, dtype=float)
        values = 22.0 + 0.015 * days + 7.0 * np.sin(2 * np.pi * (days - 100) / 365.25) + rng.normal(0, 0.6, periods)
        df = pd.DataFrame({
            'timestamp': pd.date_range('2022-01-01', periods=periods, freq='D'),
            'location': ['Skill-City'] * periods,
            'temperature': values,
        })
        result = generate_forecast(df, 'Skill-City', 'temperature', horizon=7, dataset_id='unittestds')
        metrics = result['metrics']
        assert metrics['mae'] <= metrics['baseline_persistence_mae'], (
            f"model MAE {metrics['mae']} should beat persistence {metrics['baseline_persistence_mae']}"
        )
        assert metrics['skill_vs_persistence_pct'] >= 0

    def test_short_series_falls_back_to_ses(self):
        from app.services.forecaster import generate_forecast

        df = _weather_frame('Short-City', periods=30)
        result = generate_forecast(df, 'Short-City', 'temperature', horizon=5, dataset_id='unittestds')

        assert result['model_used'] == 'SimpleExponentialSmoothing'
        assert 'fallback' in result['metrics']['model_note']
        assert result['metrics']['evaluation']
        values = [p['predicted_value'] for p in result['predictions']]
        assert len(set(values)) == 1

    def test_precipitation_forecast_carries_limitation(self):
        from app.services.forecaster import generate_forecast

        rng = np.random.default_rng(11)
        periods = 60
        rainfall = np.where(rng.random(periods) < 0.2, rng.uniform(5, 30, periods), 0.0)
        df = pd.DataFrame({
            'timestamp': pd.date_range('2024-01-01', periods=periods, freq='D'),
            'location': ['Rain-City'] * periods,
            'precipitation': rainfall,
        })
        result = generate_forecast(df, 'Rain-City', 'precipitation', horizon=7, dataset_id='unittestds')
        assert 'limitation' in result['metrics']
        assert 'intermittent' in result['metrics']['limitation'].lower()
        for p in result['predictions']:
            assert p['predicted_value'] >= 0.0
            assert p['lower_bound'] >= 0.0

    def test_rain_climatology_insufficient_history_is_not_published(self):
        from app.services.forecaster import generate_forecast

        # Four years is below the 10-year minimum: stats stay visible for
        # transparency, but no probability is published.
        timestamps = pd.date_range('2020-01-01', '2023-12-31', freq='D')
        rainfall = np.zeros(len(timestamps))
        rainfall[timestamps.get_loc('2020-01-03')] = 12.0
        rainfall[timestamps.get_loc('2022-01-05')] = 8.0
        df = pd.DataFrame({
            'timestamp': timestamps,
            'location': ['Week-City'] * len(timestamps),
            'precipitation': rainfall,
        })
        result = generate_forecast(df, 'Week-City', 'precipitation', horizon=7, dataset_id='unittestds')

        metrics = result['metrics']
        assert metrics['rain_climatology_years'] == 4
        assert metrics['rain_climatology_min_years'] == 10
        assert metrics['week_rain_probability_pct'] is None
        assert all('rain_probability' not in p for p in result['predictions'])

    def test_rain_climatology_publishes_with_enough_history(self):
        from app.services.forecaster import generate_forecast

        # Twelve full years; the Jan 1-7 window had a >=1mm day in exactly two
        # of them (2013 and 2015), so the published week probability is 17%.
        timestamps = pd.date_range('2013-01-01', '2024-12-31', freq='D')
        rainfall = np.zeros(len(timestamps))
        rainfall[timestamps.get_loc('2013-01-03')] = 12.0
        rainfall[timestamps.get_loc('2015-01-05')] = 8.0
        df = pd.DataFrame({
            'timestamp': timestamps,
            'location': ['Week-City'] * len(timestamps),
            'precipitation': rainfall,
        })
        result = generate_forecast(df, 'Week-City', 'precipitation', horizon=7, dataset_id='unittestds')

        metrics = result['metrics']
        assert metrics['rain_climatology_years'] == 12
        assert metrics['rain_climatology_wet_years'] == 2
        assert metrics['week_rain_probability_pct'] == 17
        assert metrics['rain_climatology_threshold_mm'] == 1.0
        assert metrics['rain_climatology_window_days'] == 7
        assert all('rain_probability' in p for p in result['predictions'])

    def test_multi_location_defaults_use_weather_columns(self):
        from app.services.forecaster import generate_multi_location_forecast

        periods = 60
        df = pd.DataFrame({
            'timestamp': pd.date_range('2024-01-01', periods=periods, freq='D'),
            'location': ['Multi-City'] * periods,
            'temperature': np.linspace(20, 30, periods),
            'precipitation': np.zeros(periods),
            'pm25': np.full(periods, np.nan),
        })
        results = generate_multi_location_forecast(df, dataset_id='unittestds')
        assert results, "expected forecasts for populated weather columns"
        assert all('error' not in r for r in results)
        assert {r['parameter'] for r in results} == {'temperature', 'precipitation'}
