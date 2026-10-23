import numpy as np
from typing import Dict, Tuple, Optional


# CPCB breakpoints, made continuous: each band starts where the previous one
# ends. The old tables had 1-unit gaps (30->31, 60->61, 168->169, ...), so a
# value inside a gap produced no sub-index and silently dropped that pollutant
# from the AQI. Boundaries are inclusive at the lower edge and map linearly
# within the band; ``sub_index`` assigns the shared boundary to the new band.
CPCB_BREAKPOINTS = {
    'pm25': [
        (0, 30, 0, 50),
        (30, 60, 50, 100),
        (60, 90, 100, 200),
        (90, 120, 200, 300),
        (120, 250, 300, 400),
        (250, 500, 400, 500),
    ],
    'pm10': [
        (0, 50, 0, 50),
        (50, 100, 50, 100),
        (100, 250, 100, 200),
        (250, 350, 200, 300),
        (350, 430, 300, 400),
        (430, 600, 400, 500),
    ],
    'no2': [
        (0, 40, 0, 50),
        (40, 80, 50, 100),
        (80, 180, 100, 200),
        (180, 280, 200, 300),
        (280, 400, 300, 400),
        (400, 600, 400, 500),
    ],
    'so2': [
        (0, 40, 0, 50),
        (40, 80, 50, 100),
        (80, 380, 100, 200),
        (380, 800, 200, 300),
        (800, 1600, 300, 400),
        (1600, 2400, 400, 500),
    ],
    # CO is published in mg/m3; stored CO is converted from ug/m3 first.
    'co': [
        (0, 1.0, 0, 50),
        (1.0, 2.0, 50, 100),
        (2.0, 10.0, 100, 200),
        (10.0, 17.0, 200, 300),
        (17.0, 34.0, 300, 400),
        (34.0, 50.0, 400, 500),
    ],
    'o3': [
        (0, 50, 0, 50),
        (50, 100, 50, 100),
        (100, 168, 100, 200),
        (168, 208, 200, 300),
        (208, 748, 300, 400),
        (748, 1000, 400, 500),
    ],
}

# Stored concentrations are µg/m³ for particulates/gases. CPCB's CO
# breakpoints are in mg/m³, so only CO needs scaling before lookup.
_CO_STORAGE_TO_BREAKPOINT = 1.0 / 1000.0

# Upper bounds are inclusive and shared between adjacent categories. The old
# table started the next band at 51/101/... leaving values such as 50.26 with no
# category at all.
AQI_CATEGORIES = [
    (0, 50, "Good"),
    (50, 100, "Satisfactory"),
    (100, 200, "Moderate"),
    (200, 300, "Poor"),
    (300, 400, "Very Poor"),
    (400, 500, "Severe"),
]


def aqi_category(value) -> str:
    """Return the CPCB category for an AQI value, using upper-bound bands."""
    if value is None:
        return "Unknown"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "Unknown"
    if np.isnan(number) or number < 0:
        return "Unknown"
    for _, high, category in AQI_CATEGORIES:
        if number <= high:
            return category
    return AQI_CATEGORIES[-1][2]


def sub_index(c: float, bps) -> Optional[float]:
    """Piecewise-linear CPCB sub-index.

    ``bps`` is a list of ``(lo, hi, aqi_lo, aqi_hi)`` bands. A value falls in
    the band whose next lower edge is above it; because consecutive bands share
    their boundary, no valid concentration can fall into a gap. Values above
    the last band are clamped to its top (AQI 500) and negatives are missing.
    """
    if c is None:
        return None
    try:
        c = float(c)
    except (TypeError, ValueError):
        return None
    if np.isnan(c) or c < 0:
        return None
    for i, (lo, hi, a, b) in enumerate(bps):
        top = bps[i + 1][0] if i + 1 < len(bps) else float("inf")
        if c < top:
            return a + (b - a) * (min(c, hi) - lo) / (hi - lo)
    return None


def calculate_sub_index(value: float, pollutant: str) -> Optional[float]:
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if np.isnan(value) or value < 0:
        return None

    breakpoints = CPCB_BREAKPOINTS.get(pollutant)
    if not breakpoints:
        return None
    if pollutant == 'co':
        value *= _CO_STORAGE_TO_BREAKPOINT
    result = sub_index(value, breakpoints)
    return None if result is None else round(result, 2)


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

    # CPCB publishes AQI as an integer; keep the decimal sub-indices, round the
    # headline once so a value like 200.6 is reported as 201 (Poor), not 200.
    aqi = int(round(aqi))

    category = aqi_category(aqi)

    return aqi, category, dominant_pollutant, sub_indices


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