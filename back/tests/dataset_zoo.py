"""Generated fixture zoo for importer/ML contracts.

Each fixture is intentionally awkward in a different way. They are written at
test time (not committed as binaries) so the expected shape is visible next to
the data. No fixture depends on a particular local dataset.
"""
from pathlib import Path

import numpy as np
import pandas as pd


def _write_csv(directory: Path, name: str, frame: pd.DataFrame) -> Path:
    path = directory / name
    frame.to_csv(path, index=False)
    return path


def _write_text(directory: Path, name: str, text: str) -> Path:
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def build_zoo(directory: Path) -> dict:
    """Create the zoo and return {name: path}."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    zoo: dict[str, Path] = {}

    zoo["clean_water_wide"] = _write_csv(directory, "clean_water_wide.csv", pd.DataFrame({
        "timestamp": [
            "2021-01-01T00:00:00Z", "2021-01-01T00:00:00Z",
            "2021-02-01T00:00:00Z", "2021-03-01T00:00:00Z",
            "2021-04-01T00:00:00Z", "2021-05-01T00:00:00Z",
            "2021-06-01T00:00:00Z",
        ],
        "station": ["Zoo Lake"] * 7,
        "ph": [7.2, 7.2, 7.4, 7.1, 7.6, 7.3, 7.0],
        "Dissolved Oxygen (mg/L)": [6.5, 7.5, 5.8, 6.2, 7.0, 4.9, 6.6],
        "BOD": [5.0, 5.0, 6.0, 4.0, 3.5, 8.0, 5.5],
        "Total Coliform": [1200, 1200, 1500, 900, 2000, 2500, 1100],
        "Nitrate": [2.0, 2.0, "<0.5", 1.5, "ND", 3.0, 2.2],
    }))

    zoo["water_long"] = _write_csv(directory, "water_long.csv", pd.DataFrame({
        "timestamp": ["2021-01-01", "2021-01-01", "2021-01-01",
                      "2021-02-01", "2021-02-01", "2021-02-01"],
        "station": ["Long Lake"] * 6,
        "parameter": ["DO_mgl", "Nitrate as N", "pH",
                      "DO_mgl", "Nitrate as N", "pH"],
        "value": [6.5, 2.0, 7.2, 5.8, 2.5, 7.4],
    }))

    zoo["water_synonyms"] = _write_csv(directory, "water_synonyms.csv", pd.DataFrame({
        "timestamp": ["2021-01-01", "2021-02-01"],
        "station": ["Syn Lake", "Syn Lake"],
        "DO_mgl": [6.5, 6.1],
        "d.o.": [None, None],
        "Dissolved Oxygen (mg/L)": [None, None],
        "f": [1.2, 1.4],
        "BOD": [4.0, 5.0],
    }))

    zoo["air_quality_units"] = _write_csv(directory, "air_quality_units.csv", pd.DataFrame({
        "Date": pd.date_range("2024-01-01", periods=5, freq="D").strftime("%Y-%m-%d"),
        "station": ["Air Zoo"] * 5,
        "PM2.5 (µg/m³)": [35.0, 42.0, 55.0, 28.0, 61.0],
        "PM10 (mg/m³)": [0.08, 0.09, 0.11, 0.07, 0.12],
        "NO2": [24.0, 26.0, 31.0, 20.0, 33.0],
    }))

    zoo["imd_rain"] = _write_text(
        directory, "rain_2021.txt",
        "Date,12.97 77.59\n"
        "2021-01-01,0.0\n2021-01-02,12.5\n2021-01-03,0.0\n",
    )
    zoo["imd_tmax"] = _write_text(
        directory, "tmax_2021.txt",
        "Date,12.97 77.59\n"
        "2021-01-01,28.0\n2021-01-02,27.5\n2021-01-03,29.0\n",
    )

    zoo["no_station"] = _write_csv(directory, "no_station.csv", pd.DataFrame({
        "Date": ["2024-02-01", "2024-02-02", "2024-02-03"],
        "PM2.5": [30.0, 31.0, 29.0],
        "PM10": [60.0, 62.0, 59.0],
    }))

    zoo["tiny_air"] = _write_csv(directory, "tiny_air.csv", pd.DataFrame({
        "timestamp": pd.date_range("2024-03-01", periods=5, freq="D").strftime("%Y-%m-%d"),
        "location": ["Tiny"] * 5,
        "pm25": [10.0, 11.0, 9.0, 12.0, 10.5],
    }))

    wide = {"timestamp": pd.date_range("2024-04-01", periods=4, freq="D").strftime("%Y-%m-%d"),
            "station": ["Wide"] * 4, "PM2.5": [20.0, 21.0, 19.0, 22.0]}
    for index in range(197):
        wide[f"junk_{index}"] = [index, index + 1, index + 2, index + 3]
    zoo["wide_200"] = _write_csv(directory, "wide_200.csv", pd.DataFrame(wide))

    zoo["garbage_text"] = _write_csv(directory, "garbage_text.csv", pd.DataFrame({
        "alpha": ["not", "a", "dataset"],
        "beta": ["42?", "maybe", "??"],
    }))

    zoo["duplicate_headers"] = _write_text(
        directory, "duplicate_headers.csv",
        "Date,station,PM2.5,PM2.5\n"
        "2024-05-01,A,20,21\n2024-05-01,A,20,21\n2024-05-02,A,22,23\n",
    )

    zoo["mixed_headers"] = _write_csv(directory, "mixed_headers.csv", pd.DataFrame({
        "timestamp": ["2024-06-01", "2024-06-02"],
        "station": ["Mixed"] * 2,
        "PM2.5": [20.0, 21.0],
        "PM10": [45.0, 46.0],
        "pH": [7.2, 7.3],
        "DO": [6.5, 6.4],
    }))

    zoo["ambiguous_dates"] = _write_csv(directory, "ambiguous_dates.csv", pd.DataFrame({
        "timestamp": ["01/02/2021", "02/03/2021", "03/04/2021"],
        "station": ["Ambiguous"] * 3,
        "PM2.5": [20.0, 21.0, 22.0],
    }))

    zoo["day_first_dates"] = _write_csv(directory, "day_first_dates.csv", pd.DataFrame({
        "timestamp": ["13/01/2021", "14/01/2021", "15/01/2021"],
        "station": ["DayFirst"] * 3,
        "PM2.5": [20.0, 21.0, 22.0],
    }))

    zoo["temperature_f"] = _write_csv(directory, "temperature_f.csv", pd.DataFrame({
        "timestamp": ["2024-07-01", "2024-07-02", "2024-07-03"],
        "station": ["Hot"] * 3,
        "Temp (°F)": [68.0, 77.0, 50.0],
    }))

    zoo["irregular_dates"] = _write_csv(directory, "irregular_dates.csv", pd.DataFrame({
        "timestamp": ["2024-01-01", "2024-01-03", "2024-01-10", "2024-02-15", "2024-03-30"],
        "location": ["Irregular"] * 5,
        "pm25": [20.0, 25.0, 22.0, 30.0, 18.0],
    }))

    stamps = pd.date_range("2018-01-01", periods=36, freq="MS")
    phase = np.arange(36)
    zoo["monthly_water"] = _write_csv(directory, "monthly_water.csv", pd.DataFrame({
        "timestamp": stamps.strftime("%Y-%m-%d"),
        "station": ["Monthly Lake"] * 36,
        "do": 7.5 + 1.2 * np.sin(2 * np.pi * phase / 12) + 0.05 * phase,
        "total_coliform": 1000.0 * (1.015 ** phase),
        "BOD": 4.0 + 0.5 * np.cos(2 * np.pi * phase / 12),
        "pH": 7.3 + 0.1 * np.sin(2 * np.pi * phase / 12),
    }))

    return zoo
