import pytest

from app.services.aqi_calculator import (
    CPCB_BREAKPOINTS,
    aqi_category,
    calculate_aqi,
    calculate_sub_index,
    sub_index,
)
from app.services.pipeline_interface import clean_dataframe
import pandas as pd


ALL_BREAKPOINTS = list(CPCB_BREAKPOINTS.values())


@pytest.mark.parametrize("c", [168.25, 30.5, 60.7, 100.4, 208.6])
def test_no_gaps(c):
    assert all(sub_index(c, bps) is not None for bps in ALL_BREAKPOINTS)


@pytest.mark.parametrize("value,category", [
    (0, "Good"),
    (50, "Good"),
    (50.01, "Satisfactory"),
    (100, "Satisfactory"),
    (100.5, "Moderate"),
    (200, "Moderate"),
    (200.5, "Poor"),
    (300, "Poor"),
    (300.5, "Very Poor"),
    (400, "Very Poor"),
    (400.5, "Severe"),
    (500, "Severe"),
])
def test_aqi_category_uses_inclusive_upper_bounds(value, category):
    assert aqi_category(value) == category


def test_category_boundaries_are_shared_not_gapped():
    # 50.26 used to miss Good and Satisfactory, falling through to Severe.
    assert aqi_category(50.26) == "Satisfactory"


def test_agartala_2026_09_16_aqi_is_201():
    # Exact values stored for Agartala on that date in air_quality_daily.csv.
    aqi, category, dominant, sub_indices = calculate_aqi({
        "pm25": 27.81,
        "pm10": 28.08,
        "no2": 10.63,
        "so2": 6.35,
        "o3": 168.25,
    })
    assert aqi == 201
    assert category == "Poor"
    assert dominant == "o3"
    assert sub_indices["o3"] == pytest.approx(200.62)


def test_gap_value_used_to_drop_o3_from_the_aqi():
    # Regression: 168.25 used to fall in the 168-169 gap, making O3 vanish
    # and leaving the lower PM2.5 sub-index as the headline AQI.
    assert calculate_sub_index(168.25, "o3") is not None
    aqi, _, dominant, _ = calculate_aqi({"pm25": 27.81, "o3": 168.25})
    assert aqi == 201
    assert dominant == "o3"


def test_pm25_uses_continuous_cpcb_breakpoints():
    # 47.62 ug/m3 lies in the 30-60 band, mapped continuously to 50-100.
    # The integer CPCB table edge (31-60 -> 51-100) would give 79.05; the
    # platform deliberately uses the continuous form so no concentration
    # falls into a gap.
    assert calculate_sub_index(47.62, "pm25") == pytest.approx(79.37)


def test_co_is_converted_from_ug_m3_to_mg_m3_breakpoints():
    # 483.5 ug/m3 = 0.4835 mg/m3 -> 24.18 on the 0-1 mg/m3 CPCB band.
    assert calculate_sub_index(483.5, "co") == pytest.approx(24.18)


def test_source_aqi_columns_are_capped_and_counted():
    df = pd.DataFrame({
        "date": ["2021-01-01", "2021-01-02"],
        "city": ["A", "A"],
        "pm2_5_mean": [10.0, 11.0],
        "us_aqi_max": [1709.0, 120.0],
        "india_aqi": [500.0, 120.0],
    })
    cleaned, report = clean_dataframe(df, "air_quality")
    assert pd.isna(cleaned.loc[0, "us_aqi_max"])
    assert cleaned.loc[1, "us_aqi_max"] == 120.0
    assert cleaned.loc[0, "india_aqi"] == 500.0
    assert report["out_of_range_values_set_to_nan"]["us_aqi_max"] == 1
    assert report["source_aqi_at_cap"]["india_aqi"] == 1
