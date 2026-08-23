import numpy as np
from typing import Dict, Tuple, Optional


CPCB_BREAKPOINTS = {
    'pm25': [
        (0, 30, 0, 50),
        (31, 60, 51, 100),
        (61, 90, 101, 200),
        (91, 120, 201, 300),
        (121, 250, 301, 400),
        (251, 500, 401, 500),
    ],
    'pm10': [
        (0, 50, 0, 50),
        (51, 100, 51, 100),
        (101, 250, 101, 200),
        (251, 350, 201, 300),
        (351, 430, 301, 400),
        (431, 600, 401, 500),
    ],
    'no2': [
        (0, 40, 0, 50),
        (41, 80, 51, 100),
        (81, 180, 101, 200),
        (181, 280, 201, 300),
        (281, 400, 301, 400),
        (401, 600, 401, 500),
    ],
    'so2': [
        (0, 40, 0, 50),
        (41, 80, 51, 100),
        (81, 380, 101, 200),
        (381, 800, 201, 300),
        (801, 1600, 301, 400),
        (1601, 2400, 401, 500),
    ],
    'co': [
        (0, 1.0, 0, 50),
        (1.1, 2.0, 51, 100),
        (2.1, 10.0, 101, 200),
        (10.1, 17.0, 201, 300),
        (17.1, 34.0, 301, 400),
        (34.1, 50.0, 401, 500),
    ],
    'o3': [
        (0, 50, 0, 50),
        (51, 100, 51, 100),
        (101, 168, 101, 200),
        (169, 208, 201, 300),
        (209, 748, 301, 400),
        (749, 1000, 401, 500),
    ],
}

AQI_CATEGORIES = [
    (0, 50, "Good"),
    (51, 100, "Satisfactory"),
    (101, 200, "Moderate"),
    (201, 300, "Poor"),
    (301, 400, "Very Poor"),
    (401, 500, "Severe"),
]


def calculate_sub_index(value: float, pollutant: str) -> Optional[float]:
    if value is None or np.isnan(value):
        return None
    
    breakpoints = CPCB_BREAKPOINTS.get(pollutant)
    if not breakpoints:
        return None
    
    for bp_lo, bp_hi, i_lo, i_hi in breakpoints:
        if bp_lo <= value <= bp_hi:
            sub_index = ((i_hi - i_lo) / (bp_hi - bp_lo)) * (value - bp_lo) + i_lo
            return round(sub_index, 2)
    
    if value > breakpoints[-1][1]:
        return 500.0
    
    return None


def calculate_aqi(pollutant_values: Dict[str, float]) -> Tuple[Optional[float], Optional[str], Optional[str], Dict[str, float]]:
    sub_indices = {}
    
    for pollutant, value in pollutant_values.items():
        if value is not None and not np.isnan(value):
            sub_idx = calculate_sub_index(value, pollutant)
            if sub_idx is not None:
                sub_indices[pollutant] = sub_idx
    
    if not sub_indices:
        return None, None, None, {}
    
    aqi = max(sub_indices.values())
    dominant_pollutant = max(sub_indices, key=sub_indices.get)
    
    category = "Unknown"
    for lo, hi, cat in AQI_CATEGORIES:
        if lo <= aqi <= hi:
            category = cat
            break
    
    return round(aqi, 2), category, dominant_pollutant, sub_indices


def compute_aqi_for_record(record: dict) -> dict:
    pollutants = {
        'pm25': record.get('pm25'),
        'pm10': record.get('pm10'),
        'no2': record.get('no2'),
        'so2': record.get('so2'),
        'co': record.get('co'),
        'o3': record.get('o3'),
    }
    
    aqi, category, dominant, sub_indices = calculate_aqi(pollutants)
    
    return {
        'aqi': aqi,
        'aqi_category': category,
        'dominant_pollutant': dominant,
        'pollutant_values': pollutants,
        'sub_indices': sub_indices,
    }