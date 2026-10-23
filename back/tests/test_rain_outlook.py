import numpy as np
import pandas as pd

from app.services.forecaster import rain_outlook_from_frame


def _rain_frame(start, end, wet_dates):
    timestamps = pd.date_range(start, end, freq='D')
    rainfall = np.zeros(len(timestamps))
    for wet_date in wet_dates:
        rainfall[timestamps.get_loc(pd.Timestamp(wet_date))] = 10.0
    return pd.DataFrame({
        'timestamp': timestamps,
        'location': ['Rain-Outlook-City'] * len(timestamps),
        'precipitation': rainfall,
    })


def test_rain_outlook_exposes_daily_and_monthly_probabilities():
    df = _rain_frame('2013-01-01', '2024-12-31', ['2013-01-03', '2015-01-05'])

    outlook = rain_outlook_from_frame(df, 'Rain-Outlook-City')

    assert outlook['probability_only'] is True
    assert outlook['week_probability_pct'] == 17
    assert outlook['week_probability_estimate_pct'] == 17
    assert outlook['week_probability_publishable'] is True
    assert len(outlook['daily']) == 7
    assert outlook['daily'][0]['date'] == '2025-01-01'
    assert outlook['daily'][0]['rain_probability_pct'] is not None
    assert len(outlook['monthly']) == 12
    assert outlook['monthly'][0]['month'] == 1
    assert outlook['monthly'][0]['wet_days'] == 2
    assert 0 <= outlook['brier_score'] <= 1
    assert 0 <= outlook['brier_reference'] <= 1
    assert outlook['brier_samples'] == len(df)
    assert outlook['week_probability_ci_low_pct'] is not None
    assert outlook['week_probability_ci_low_pct'] <= outlook['week_probability_estimate_pct']
    assert outlook['week_probability_ci_high_pct'] >= outlook['week_probability_estimate_pct']


def test_rain_outlook_keeps_short_history_estimate_private():
    df = _rain_frame('2020-01-01', '2023-12-31', ['2020-01-03', '2022-01-05'])

    outlook = rain_outlook_from_frame(df, 'Rain-Outlook-City')

    assert outlook['years_observed'] == 4
    assert outlook['week_probability_pct'] is None
    assert outlook['week_probability_estimate_pct'] == 50
    assert outlook['week_probability_publishable'] is False


def test_rain_outlook_suppresses_model_that_loses_dry_baseline():
    df = _rain_frame('2013-01-01', '2024-12-31', ['2013-01-03', '2015-01-05'])

    losing = rain_outlook_from_frame(
        df, 'Rain-Outlook-City',
        model_metrics={'mae': 5.83, 'baseline_zero_mae': 5.23},
    )
    winning = rain_outlook_from_frame(
        df, 'Rain-Outlook-City',
        model_metrics={'mae': 4.0, 'baseline_zero_mae': 5.23},
    )

    assert losing['model']['suppressed'] is True
    assert losing['model']['beats_zero_baseline'] is False
    assert 'always-dry baseline' in losing['model']['reason']
    assert winning['model']['suppressed'] is False
    assert winning['model']['beats_zero_baseline'] is True
