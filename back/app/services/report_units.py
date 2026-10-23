"""Shared report vocabulary: units, labels and dataset tags.

Used by the dashboard queries, the report builder and all three renderers so a
parameter is spelled and labelled the same way everywhere.
"""
from typing import List

PARAMETER_UNITS = {
    "aqi": "index",
    "wqi": "index",
    "ph": "pH",
    "do": "mg/L",
    "bod": "mg/L",
    "turbidity": "NTU",
    "tds": "mg/L",
    "hardness": "mg/L",
    "chlorides": "mg/L",
    "sulfates": "mg/L",
    "nitrates": "mg/L as NO3",
    "fluorides": "mg/L",
    "iron": "mg/L",
    "manganese": "mg/L",
    "total_coliform": "MPN/100 mL",
    "ammonia": "mg/L",
    "conductivity": "\u00b5S/cm",
    "pm25": "\u00b5g/m\u00b3",
    "pm10": "\u00b5g/m\u00b3",
    "no2": "\u00b5g/m\u00b3",
    "so2": "\u00b5g/m\u00b3",
    "o3": "\u00b5g/m\u00b3",
    "co": "\u00b5g/m\u00b3",
    "us_aqi_max": "index",
    "india_aqi": "index",
    "temperature": "\u00b0C",
    "temp_min": "\u00b0C",
    "temp_max": "\u00b0C",
    "precipitation": "mm",
}

PARAMETER_LABELS = {
    "aqi": "AQI",
    "wqi": "WQI",
    "ph": "pH",
    "do": "Dissolved oxygen",
    "bod": "BOD (5-day)",
    "turbidity": "Turbidity",
    "tds": "TDS",
    "hardness": "Total hardness",
    "chlorides": "Chlorides",
    "sulfates": "Sulfates",
    "nitrates": "Nitrates",
    "fluorides": "Fluorides",
    "iron": "Iron",
    "manganese": "Manganese",
    "total_coliform": "Total coliform",
    "ammonia": "Ammonia (as N)",
    "conductivity": "Conductivity",
    "pm25": "PM2.5",
    "pm10": "PM10",
    "no2": "NO2",
    "so2": "SO2",
    "o3": "O3",
    "co": "CO",
    "us_aqi_max": "US AQI (source max)",
    "india_aqi": "India AQI (source)",
    "temperature": "Temperature",
    "temp_min": "Daily minimum temperature",
    "temp_max": "Daily maximum temperature",
    "precipitation": "Precipitation",
}

TYPE_LABELS = {
    "air_quality": "Air quality",
    "water_quality": "Water quality",
    "temperature": "Temperature",
    "rainfall": "Rainfall",
}

TYPE_ORDER = ["air_quality", "water_quality", "temperature", "rainfall"]


def header_with_unit(label: str, unit: str) -> str:
    if not unit:
        return label
    return f"{label} ({unit})"


def dataset_tags(dataset: dict) -> List[str]:
    """Tags shown on the cover/About sheet: synthetic, modelled, merged."""
    tags: List[str] = []
    label = f"{dataset.get('display_name') or ''} {dataset.get('filename') or ''}".lower()
    if "synthetic" in label:
        tags.append("synthetic")

    cleaning_report = dataset.get("cleaning_report") or {}
    derived = cleaning_report.get("derived_columns") or {}
    imputed = cleaning_report.get("derived_values_imputed") or {}
    if derived:
        tags.append("modelled")
    if any((value or 0) > 0 for value in imputed.values()):
        if "modelled" not in tags:
            tags.append("modelled")
    if cleaning_report.get("source_format", "").startswith("imd"):
        tags.append("merged")
    if dataset.get("data_nature") == "modelled":
        if "modelled" not in tags:
            tags.append("modelled")
    if dataset.get("dataset_type") == "water_quality":
        tags.append("WQI computed")
    if dataset.get("dataset_type") == "air_quality":
        tags.append("AQI computed")
    return tags
