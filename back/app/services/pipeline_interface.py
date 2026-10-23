import csv
import json
import os
import re
import magic  # python-magic for content-type detection
import numpy as np
import pandas as pd
from typing import Tuple, Optional, Dict, List
from app.models.air_quality import AirQualityCreate
from app.models.water_quality import WaterQualityCreate
from app.services import dataset_config
from app.services.job_progress import report_counts, report_stage

# Validation limits
MAX_ROWS = 500_000
MAX_COLS = 200
MAX_CELL_LEN = 10_000
MAX_EXCEL_EXPANDED_BYTES = 100 * 1024 * 1024  # 100 MB expanded
MAX_EXCEL_SHEETS = 20
MAX_CSV_CELL_BYTES = 1_000_000  # 1 MB per cell (safety)

STANDARDIZED_AIR_QUALITY_COLUMNS: List[str] = [
    "timestamp",
    "location",
    "pm25",
    "pm10",
    "no2",
    "so2",
    "co",
    "o3",
    "us_aqi_max",
    "india_aqi",
    "temperature",
    "temp_min",
    "temp_max",
    "precipitation",
]

STANDARDIZED_WATER_QUALITY_COLUMNS: List[str] = [
    "timestamp",
    "location",
    "ph",
    "turbidity",
    "tds",
    "hardness",
    "chlorides",
    "sulfates",
    "nitrates",
    "fluorides",
    "iron",
    "manganese",
    "do",
    "bod",
    "ammonia",
    "total_coliform",
    "conductivity",
    "latitude",
    "longitude",
]

CAPABILITY_ORDER: Tuple[str, ...] = ("air_quality", "water_quality", "temperature", "rainfall")

_AIR_QUALITY_CAPABILITY_NAMES = {"pm25", "pm10", "no2", "so2", "o3", "co"}
_AIR_QUALITY_CAPABILITY_FRAGMENTS = (
    "pm2.5", "pm2_5", "pm25", "pm10", "no2", "so2", "o3", "nox", "nh3",
    "benzene", "toluene", "xylene", "aqi",
)
_WATER_QUALITY_CAPABILITY_NAMES = set(STANDARDIZED_WATER_QUALITY_COLUMNS) - {"timestamp", "location", "latitude", "longitude"}
_WATER_QUALITY_CAPABILITY_FRAGMENTS = (
    "turbidity", "dissolved_oxygen", "conductivity", "fecal", "sulphate",
    "sulfate", "chloride", "hardness", "fluoride", "coliform",
)
_TEMPERATURE_CAPABILITY_NAMES = {"temperature", "temp_max", "temp_min"}
_TEMPERATURE_CAPABILITY_FRAGMENTS = ("temperature", "temp_")
_RAINFALL_CAPABILITY_NAMES = {"precipitation", "rainfall", "rain"}
_RAINFALL_CAPABILITY_FRAGMENTS = ("precip", "rain")

# Water-quality files also use NO2/NH3/O3-looking names for nitrogen species
# (``no2_n`` nitrite-N, ``nh3_n`` ammonia-N, ``no2_no3``); those must never
# count as air-quality pollutants when capabilities are derived.
_WATER_NITROGEN_COLUMN_PREFIXES = (
    r"^no2_+n",
    r"^nh3_+n",
    r"^nitrite",
    r"^nitrate",
    r"^no3_+n",
)


def derive_capabilities(columns, dataset_type: Optional[str] = None) -> List[str]:
    """Which dashboards a dataset can feed, derived from its actual columns.

    One dataset can legitimately serve several dashboards (the IMD weather
    files carry both temperature and rainfall), so pages match datasets on
    capabilities instead of guessing from a single dataset_type. Aliased
    source columns are recognised (e.g. ``PM2.5``, ``temperature_2m_max``),
    and the upload's declared type is kept as a fallback for datasets whose
    column names are all unrecognised.
    """
    normalized = [str(column).strip().lower() for column in ([] if columns is None else columns)]

    def has_exact(names) -> bool:
        return any(name in normalized for name in names)

    def has_fragment(fragments) -> bool:
        return any(fragment in column for column in normalized for fragment in fragments)

    def has_air_fragment(fragments) -> bool:
        for column in normalized:
            if any(re.match(prefix, column) for prefix in _WATER_NITROGEN_COLUMN_PREFIXES):
                continue
            for fragment in fragments:
                if re.search(rf"(?<![a-z0-9]){re.escape(fragment)}(?![a-z0-9])", column):
                    return True
        return False

    capabilities = set()
    if has_exact(_AIR_QUALITY_CAPABILITY_NAMES) or has_air_fragment(_AIR_QUALITY_CAPABILITY_FRAGMENTS):
        capabilities.add("air_quality")
    if has_exact(_WATER_QUALITY_CAPABILITY_NAMES) or has_fragment(_WATER_QUALITY_CAPABILITY_FRAGMENTS):
        capabilities.add("water_quality")
    if has_exact(_TEMPERATURE_CAPABILITY_NAMES) or has_fragment(_TEMPERATURE_CAPABILITY_FRAGMENTS):
        capabilities.add("temperature")
    if has_exact(_RAINFALL_CAPABILITY_NAMES) or has_fragment(_RAINFALL_CAPABILITY_FRAGMENTS):
        capabilities.add("rainfall")
    if dataset_type in CAPABILITY_ORDER:
        capabilities.add(dataset_type)
    return [capability for capability in CAPABILITY_ORDER if capability in capabilities]


_AIR_QUALITY_COLUMN_PATTERNS: Dict[str, List[str]] = {
    "timestamp": [
        r"^timestamp$",
        r"^time$",
        r"^datetime$",
        r"^date_time$",
        r"^date$",
        r"^ts$",
        r"^reading_time$",
        r"^sampling_time$",
        r"^utc_time$",
        r"^datetime_utc$",
        r"^recorded_at$",
    ],
    "location": [
        r"^location$",
        r"^station$",
        r"^station_name$",
        r"^station_id$",
        r"^site$",
        r"^site_name$",
        r"^city$",
        r"^area$",
        r"^monitoring_station$",
        r"^device_id$",
        r"^sensor_id$",
    ],
    "pm25": [
        r"^pm25",
        r"^pm2\.5",
        r"^pm_25",
        r"^pm_2\.5",
        r"^pm2_5",
        r"^particulate.*2\.5",
    ],
    "pm10": [
        r"^pm10",
        r"^pm_10",
        r"^particulate.*10",
    ],
    "no2": [
        r"^no2",
        r"^no_2",
        r"^nitrogen_dioxide",
    ],
    "so2": [
        r"^so2",
        r"^so_2",
        r"^sulfur_dioxide",
        r"^sulphur_dioxide",
    ],
    "co": [
        r"^co$",
        r"^co_",
        r"^co\b",
        r"^carbon_monoxide",
    ],
    "o3": [
        r"^o3",
        r"^o_3",
        r"^ozone",
    ],
    "us_aqi_max": [
        r"^us_?aqi(?:_?max)?$",
        r"^us_?aqi_?max$",
    ],
    "india_aqi": [
        r"^india_?aqi$",
    ],
    "temperature": [
        r"^temperature$",
        r"^temp$",
        r"^temperature_2m$",
        r"^temp_2m$",
        r"^temperature_2m_mean$",
        r"^temp_mean$",
        r"^temperature_mean$",
    ],
    "temp_min": [
        r"^temperature_2m_min$",
        r"^temp_min$",
        r"^temperature_min$",
    ],
    "temp_max": [
        r"^temperature_2m_max$",
        r"^temp_max$",
        r"^temperature_max$",
    ],
    "precipitation": [
        r"^precipitation$",
        r"^precipitation_sum$",
        r"^precipitation_mm$",
        r"^rain$",
        r"^rainfall$",
        r"^rainfall_mm$",
    ],
}

AIR_QUALITY_RANGES: Dict[str, Tuple[float, float]] = dataset_config.RANGES["air_quality"]

_WATER_QUALITY_COLUMN_PATTERNS: Dict[str, List[str]] = {
    "timestamp": [
        r"^timestamp$",
        r"^time$",
        r"^datetime$",
        r"^date_time$",
        r"^date$",
        r"^measured_at$",
        r"^sampling_time$",
    ],
    "location": [
        r"^location$",
        r"^station$",
        r"^station_name$",
        r"^site$",
        r"^site_name$",
        r"^city$",
        r"^area$",
    ],
    "ph": [
        r"^ph$",
        r"^ph_level$",
        r"^p_h$",
    ],
    "turbidity": [
        r"^turbidity$",
        r"^turbidity_ntu$",
        r"^turb$",
    ],
    "tds": [
        r"^tds$",
        r"^total_dissolved_solids$",
        r"^total_dissolved_solids_mg_l$",
    ],
    "hardness": [
        r"^hardness$",
        r"^total_hardness$",
        r"^total_hardness_mg_l$",
    ],
    "chlorides": [
        r"^chloride$",
        r"^chlorides$",
    ],
    "sulfates": [
        r"^sulfate$",
        r"^sulfates$",
        r"^sulphate$",
        r"^sulphates$",
    ],
    "nitrates": [
        r"^nitrate$",
        r"^nitrates$",
        r"^nitrates?(?![a-z0-9])",
        r"^no3$",
        r"^no3_n$",
        r"^no3(?![a-z0-9])",
        r"^nitrate_mg_l$",
        r"^nitrate_n_mg_l$",
        r"^nitrate_nitrogen_mg_l$",
    ],
    "fluorides": [
        r"^fluoride$",
        r"^fluorides$",
        r"^f$",
    ],
    "iron": [
        r"^iron$",
        r"^fe$",
    ],
    "manganese": [
        r"^manganese$",
        r"^mn$",
    ],
    "do": [
        r"^do$",
        r"^d_o$",
        r"^dissolved_oxygen$",
        r"^do_mg_l$",
        r"^d_o_mg_l$",
        r"^dissolved_oxygen_mg_l$",
        r"^d\.o\.$",
        r"^d\.o\._mg_l$",
        r"^do(?:_?mgl|_?mg_?l)$",
    ],
    "bod": [
        r"^bod$",
        r"^bod5$",
        r"^b_o_d$",
        r"^bod_mg_l$",
        r"^bod5_mg_l$",
        r"^biochemical_oxygen_demand$",
        r"^bio_chemical_oxygen_demand_mg_l$",
        r"^bod_?3_?27$",
    ],
    "total_coliform": [
        r"^tcol_mpn$",
        r"^tcol$",
        r"^total_coliform$",
        r"^total_coliform_mpn_100ml$",
    ],
    "ammonia": [
        r"^nh3_n$",
        r"^nh3$",
        r"^ammonia$",
        r"^ammonia_n$",
        r"^nh4_n$",
    ],
    "conductivity": [
        r"^conductivity$",
        r"^conductance$",
        r"^specific_conductance$",
        r"^electrical_conductivity$",
        r"^ec$",
        r"^ec_?(fld|gen|field|general)$",
        r"^cond$",
        r"^sp_?cond$",
    ],
    "latitude": [
        r"^latitude$",
        r"^lat$",
    ],
    "longitude": [
        r"^longitude$",
        r"^lon$",
        r"^long$",
    ],
}

# A synonym group matched too broadly: e.g. DO saturation (%) is not DO (mg/L)
# and must not be merged into the same canonical column.
_WATER_QUALITY_SYNONYM_EXCLUDES: Dict[str, List[str]] = {
    "do": [r"(?:^|_)sat(?:$|_)"],
}

# Nitrate dual units: the BIS 45 mg/L limit is defined for nitrate as NO3,
# but CPCB-style files report nitrate-N (columns like ``no3_n``,
# ``nitrate_n_mg_l``, ``nitrate nitrogen``). Values are converted to NO3 at
# import so one limit table applies to every file.
_NITRATE_N_TO_NO3 = 62.004 / 14.007  # ≈ 4.4266


def _nitrate_source_reports_as_n(source) -> bool:
    """True when a source column name marks nitrate as nitrogen (as N)."""
    token = _normalized_column_token(source)
    if "nitrogen" in token:
        return True
    if not re.search(r"(?:^|_)(?:no3|nitrate)(?:_|$)", token):
        return False
    return token.endswith("_n") or token.endswith("_n_mg_l")


def _apply_nitrate_unit_conversion(
    df: pd.DataFrame,
    report: dict,
    sources: Optional[List] = None,
) -> Tuple[pd.DataFrame, dict]:
    """Normalise nitrate-N to nitrate (NO3) so the BIS 45 mg/L limit applies."""
    if "nitrates" not in df.columns:
        return df, report

    if sources is None:
        sources = [
            src for src, canonical in report.get("columns_renamed", {}).items()
            if canonical == "nitrates"
        ]
        sources += report.get("synonym_columns_merged", {}).get("nitrates", [])

    if not any(_nitrate_source_reports_as_n(src) for src in sources):
        return df, report

    df = df.copy()
    df["nitrates"] = pd.to_numeric(df["nitrates"], errors="coerce") * _NITRATE_N_TO_NO3
    report.setdefault("unit_conversions", {})["nitrates"] = (
        "converted nitrate-N to nitrate (NO3) x 4.4266 because the source "
        f"column reports nitrate as N ({', '.join(str(s) for s in sources)})"
    )
    return df, report


WATER_QUALITY_RANGES: Dict[str, Tuple[float, float]] = dataset_config.RANGES["water_quality"]

_LONG_FORMAT_PARAMETER_COLUMNS = {
    "parameter",
    "pollutant",
    "parameter_name",
    "parameter_code",
    "metric",
    "variable",
    "measure",
    "element",
}

_LONG_FORMAT_VALUE_COLUMNS = {
    "value",
    "measurement",
    "reading",
    "concentration",
    "mean",
    "average",
}

_IMD_DATETIME_COLUMNS = {"datetime", "date", "time", "date_time"}

_IMD_COORDINATE_RE = re.compile(r"^-?\d{1,3}(?:\.\d{1,6})?\s+-?\d{1,3}(?:\.\d{1,6})?$")

_IMD_FILENAME_HINTS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"tmax|max_?temp|temperature_?max", re.I), "temp_max"),
    (re.compile(r"tmin|min_?temp|temperature_?min", re.I), "temp_min"),
    (re.compile(r"rain|_?rf_?|precip", re.I), "precipitation"),
]

_MISSING_MARKERS = {
    "",
    "na",
    "n/a",
    "n.a.",
    "null",
    "none",
    "nan",
    "-",
    "--",
    "missing",
}

_NON_DETECT_MARKERS = {
    "bdl",
    "nd",
    "n.d.",
    "not detected",
    "below detection limit",
    "<lod",
    "<dl",
}

_SENTINEL_VALUES = {
    -999.0,
    -9999.0,
    -99999.0,
    9999.0,
    99999.0,
    999999.0,
}

_PREFIX_ALIASES = {
    "temperature": ["temperature", "temp"],
    "temp_min": ["temperature_min", "temp_min"],
    "temp_max": ["temperature_max", "temp_max"],
    "precipitation": ["precipitation", "rainfall", "rain"],
}

_AQ_DATASET_TYPES = ("air_quality", "temperature", "rainfall")

_AQ_REQUIRED_ANY = {
    "air_quality": ["pm25", "pm10", "no2", "so2", "co", "o3"],
    "temperature": ["temperature", "temp_min", "temp_max"],
    "rainfall": ["precipitation"],
}


def _match_column_name(
    raw_col: str,
    patterns: Optional[Dict[str, List[str]]] = None,
) -> Optional[str]:
    patterns = patterns or _AIR_QUALITY_COLUMN_PATTERNS
    cleaned = str(raw_col).strip().lower()
    norm = re.sub(r"[\s\-\/\(\)\[\]µ]+", "_", cleaned).strip("_")
    last_segment = cleaned.split(".")[-1]
    norm_segment = re.sub(r"[\s\-\/\(\)\[\]µ]+", "_", last_segment).strip("_")
    candidates = [c for c in {cleaned, norm, last_segment, norm_segment} if c]

    for canonical, pats in patterns.items():
        for candidate in candidates:
            if candidate == canonical:
                return canonical
        for pat in pats:
            for candidate in candidates:
                if re.search(pat, candidate):
                    return canonical

    alias_map = []
    for canonical in patterns.keys():
        for alias in _PREFIX_ALIASES.get(canonical, [canonical]):
            alias_map.append((alias, canonical))
    alias_map.sort(key=lambda pair: len(pair[0]), reverse=True)
    for alias, canonical in alias_map:
        for candidate in candidates:
            if re.match(rf"^{re.escape(alias)}(?![a-z0-9])", candidate):
                return canonical
    return None


def _detect_header_row(raw: pd.DataFrame, max_scan: int = 15) -> int:
    if raw.empty:
        return 0
    n = min(max_scan, len(raw))
    best_idx, best_score = 0, -1
    for i in range(n):
        score = int(raw.iloc[i].notna().sum())
        if score < 2:
            continue
        has_data_below = i + 1 <= len(raw) - 1 and int(raw.iloc[i + 1].notna().sum()) >= 1
        if has_data_below and score > best_score:
            best_score, best_idx = score, i
    return best_idx


def _read_csv_robust(file_path: str) -> pd.DataFrame:
    encoding_used = None
    last_error: Optional[Exception] = None
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            raw = pd.read_csv(file_path, header=None, encoding=encoding, nrows=25)
            encoding_used = encoding
            break
        except UnicodeDecodeError as exc:
            last_error = exc
    if encoding_used is None:
        raise ValueError(f"Could not decode CSV file (tried utf-8, latin-1): {last_error}")

    if raw.empty:
        raise ValueError("File contains no data rows")

    delimiter = ","
    try:
        sample = raw.to_csv(index=False, header=False)
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        pass

    raw = pd.read_csv(
        file_path, header=None, encoding=encoding_used,
        nrows=25, sep=delimiter,
    )
    if raw.empty:
        raise ValueError("File contains no data rows")

    header_idx = _detect_header_row(raw)
    df = pd.read_csv(
        file_path, header=header_idx, encoding=encoding_used, sep=delimiter
    )
    df = df.dropna(how="all")
    if df.empty:
        raise ValueError("File contains no data rows")
    return df


def _read_json_robust(file_path: str) -> pd.DataFrame:
    with open(file_path, "r", encoding="utf-8-sig", errors="replace") as handle:
        data = json.load(handle)

    if isinstance(data, dict):
        for key in ("data", "records", "results", "items", "rows"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = [data]

    if not isinstance(data, list):
        raise ValueError("JSON root must be a list of records or an object containing a 'data' list")
    if len(data) == 0:
        raise ValueError("File contains no data rows")
    if not isinstance(data[0], dict):
        raise ValueError("JSON records must be objects")

    return pd.json_normalize(data, max_level=1)


def _read_excel_robust(file_path: str) -> pd.DataFrame:
    """Read Excel with bomb protection: limit sheets, rows, cols, expanded size."""
    # Check expanded size (XLSX is zip-based)
    file_size = os.path.getsize(file_path)
    if file_size > MAX_EXCEL_EXPANDED_BYTES:
        raise ValueError(f"Excel file too large ({file_size / 1024 / 1024:.1f} MB > {MAX_EXCEL_EXPANDED_BYTES / 1024 / 1024:.0f} MB limit)")

    sheets = pd.ExcelFile(file_path)
    if len(sheets.sheet_names) > MAX_EXCEL_SHEETS:
        raise ValueError(f"Too many sheets ({len(sheets.sheet_names)} > {MAX_EXCEL_SHEETS})")

    best: Optional[pd.DataFrame] = None
    best_area = -1

    for sheet in sheets.sheet_names:
        raw = pd.read_excel(sheets, sheet_name=sheet, header=None, nrows=MAX_ROWS)
        if raw.shape[0] < 2:
            continue
        header_idx = _detect_header_row(raw)
        df = pd.read_excel(sheets, sheet_name=sheet, header=header_idx, nrows=MAX_ROWS)
        df = df.dropna(how="all").dropna(axis=1, how="all")
        if df.empty:
            continue
        if df.shape[1] > MAX_COLS:
            raise ValueError(f"Sheet '{sheet}' has too many columns ({df.shape[1]} > {MAX_COLS})")
        area = df.shape[0] * df.shape[1]
        if area > best_area:
            best_area, best = area, df

    if best is None:
        raise ValueError("No usable data sheet found in Excel file")
    return best


def _sniff_and_read(file_path: str) -> pd.DataFrame:
    with open(file_path, "rb") as handle:
        head = handle.read(8192)

    if head.startswith(b"PK\x03\x04"):
        return _read_excel_robust(file_path)

    stripped = head.lstrip(b"\xef\xbb\xbf").lstrip()
    if stripped.startswith((b"{", b"[")):
        return _read_json_robust(file_path)

    try:
        return _read_csv_robust(file_path)
    except Exception as exc:
        raise ValueError(f"Could not detect file format: {exc}")


def parse_file(file_path: str, dataset_type: str) -> pd.DataFrame:
    """
    Parse an uploaded file (CSV, JSON, Excel) into a raw DataFrame.
    Survives wrong extensions, encodings, title rows, and JSON shape variants.
    Validates content matches extension (magic bytes).
    """
    if not os.path.exists(file_path):
        raise ValueError(f"File not found: {file_path}")
    if os.path.getsize(file_path) == 0:
        raise ValueError("Uploaded file is empty")

    # Content-type validation via magic bytes
    _validate_content_type(file_path)

    extension = os.path.splitext(file_path)[1].lower()
    extension_readers = {
        ".csv": _read_csv_robust,
        ".json": _read_json_robust,
        ".xlsx": _read_excel_robust,
        ".xls": _read_excel_robust,
    }
    reader = extension_readers.get(extension)
    errors: List[str] = []

    if reader is not None:
        try:
            return reader(file_path)
        except Exception as exc:
            errors.append(f"{extension} parsing failed: {exc}")

    try:
        return _sniff_and_read(file_path)
    except Exception as exc:
        errors.append(f"content sniffing failed: {exc}")

    if reader is None:
        errors.insert(0, f"Unsupported file format: {extension or 'unknown'}")
    raise ValueError("Could not parse uploaded file — " + "; ".join(errors))


def _validate_content_type(file_path: str) -> None:
    """Verify file content matches allowed types (CSV, JSON, XLSX/XLS)."""
    mime = magic.from_file(file_path, mime=True)
    allowed = {
        "text/csv",
        "text/plain",          # CSV often detected as plain
        "application/json",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
        "application/vnd.ms-excel",  # .xls
        "application/zip",     # .xlsx is zip-based
    }
    if mime not in allowed:
        raise ValueError(f"File content type '{mime}' not allowed (expected CSV, JSON, or Excel)")


def _empty_report() -> dict:
    return {
        "rows_read": 0,
        "rows_kept": 0,
        "rows_dropped": {},
        "original_shape": (0, 0),
        "cleaned_shape": (0, 0),
        "layout": "wide",
        "source_format": "tabular",
        "location_source": None,
        "derived_columns": {},
        "derived_values_imputed": {},
        "columns_renamed": {},
        "synonym_columns_merged": {},
        "columns_dropped": [],
        "duplicates_removed": 0,
        "duplicates_averaged": 0,
        "missing_markers_found": {},
        "missing_values_count": {},
        "sentinel_values_detected": {},
        "below_detection_limit_converted": {},
        "below_detection_limit_treated_missing": {},
        "out_of_range_values_set_to_nan": {},
        "ambiguous_date_strings": 0,
        "date_format": {},
        "plausibility_ranges": {},
        "units_detected": {},
        "unit_conversions": {},
    }


def _imd_coordinate_of(df: pd.DataFrame) -> Optional[str]:
    """Return the coordinate header of an IMD two-column export, e.g. '12.97 77.59'."""
    if df.shape[1] != 2:
        return None
    first = str(df.columns[0]).strip().lower()
    second = str(df.columns[1]).strip()
    if first in _IMD_DATETIME_COLUMNS and _IMD_COORDINATE_RE.match(second):
        return second
    return None


def imd_parameter_from_source(source_name: Optional[str]) -> Optional[str]:
    """Derive the IMD parameter (precipitation/temp_max/temp_min) from a filename."""
    if not source_name:
        return None
    name = os.path.basename(str(source_name))
    for pattern, parameter in _IMD_FILENAME_HINTS:
        if pattern.search(name):
            return parameter
    return None


def _apply_source_context(
    df: pd.DataFrame,
    source_name: Optional[str],
    default_location: Optional[str],
    dataset_type: str,
    report: dict,
) -> pd.DataFrame:
    """Normalize IMD exports and attach a location from file, upload field, or coordinate header."""
    coordinate = _imd_coordinate_of(df)
    if coordinate is not None:
        parameter = imd_parameter_from_source(source_name)
        if parameter is None:
            raise ValueError(
                "IMD two-column format detected, but the parameter cannot be derived from the filename — "
                "include 'rain', 'tmax' or 'tmin' in the filename, or upload the rain/tmax/tmin files together"
            )
        df = df.rename(columns={df.columns[0]: "timestamp", df.columns[1]: parameter})
        report["source_format"] = "imd"
        report["imd_coordinate"] = coordinate
        report["imd_parameter"] = parameter
    elif (
        dataset_type in (*_AQ_DATASET_TYPES, "water_quality")
        and df.shape[1] == 1
        and str(df.columns[0]).strip().lower() in _IMD_DATETIME_COLUMNS
    ):
        raise ValueError("IMD file appears to be missing its value column")

    has_location = any(_match_column_name(col) == "location" for col in df.columns)
    if has_location:
        report.setdefault("location_source", "file")
    elif default_location:
        df = df.copy()
        df["location"] = str(default_location)
        report["location_source"] = "upload_field"
    elif coordinate is not None:
        df = df.copy()
        df["location"] = coordinate
        report["location_source"] = "imd_coordinate"
    return df


def clean_dataframe(
    df: pd.DataFrame,
    dataset_type: str,
    source_name: Optional[str] = None,
    default_location: Optional[str] = None,
    extra_report: Optional[dict] = None,
    range_overrides: Optional[Dict[str, Tuple[float, float]]] = None,
) -> Tuple[pd.DataFrame, dict]:
    """
    Clean and normalize a DataFrame for the given dataset_type.
    Returns (cleaned_df, cleaning_report).

    The cleaning report covers: rows read/kept/dropped and why, duplicate rows
    removed, missing-value markers, sentinel values, below-detection-limit
    handling, out-of-range values cleared, and ambiguous date strings.
    """
    if df is None or len(df) == 0:
        raise ValueError("File contains no data rows")

    # Structural limits
    if df.shape[0] > MAX_ROWS:
        raise ValueError(f"Too many rows ({df.shape[0]} > {MAX_ROWS})")
    if df.shape[1] > MAX_COLS:
        raise ValueError(f"Too many columns ({df.shape[1]} > {MAX_COLS})")
    # Check cell lengths (sample first 1000 rows for performance)
    sample = df.head(1000).astype(str)
    max_len = sample.applymap(len).max().max()
    if max_len > MAX_CELL_LEN:
        raise ValueError(f"Cell content too long ({max_len} > {MAX_CELL_LEN} characters)")

    report = _empty_report()
    if extra_report:
        report.update(extra_report)
    report["rows_read"] = int(df.shape[0])
    report["original_shape"] = df.shape
    report_stage("removing_duplicate_headers", counts={"rows_read": report["rows_read"]})

    df = df.copy()
    df = _apply_source_context(df, source_name, default_location, dataset_type, report)
    effective_ranges = dataset_config.ranges_for(dataset_type, range_overrides)
    report["plausibility_ranges"] = {
        column: list(bounds) for column, bounds in effective_ranges.items()
    }

    if dataset_type in _AQ_DATASET_TYPES:
        df = _maybe_pivot_long(df, _AIR_QUALITY_COLUMN_PATTERNS, report)
        report["units_detected"] = detect_units(
            df, dataset_type, _AIR_QUALITY_COLUMN_PATTERNS
        )
        df, report = _clean_timeseries(
            df,
            report,
            patterns=_AIR_QUALITY_COLUMN_PATTERNS,
            ranges=effective_ranges,
            standardized=STANDARDIZED_AIR_QUALITY_COLUMNS,
            required_any=_AQ_REQUIRED_ANY[dataset_type],
            required_label=dataset_type,
        )
    elif dataset_type == "water_quality":
        df = _maybe_pivot_long(df, _WATER_QUALITY_COLUMN_PATTERNS, report)
        report["units_detected"] = detect_units(
            df, dataset_type, _WATER_QUALITY_COLUMN_PATTERNS
        )
        df, report = _clean_timeseries(
            df,
            report,
            patterns=_WATER_QUALITY_COLUMN_PATTERNS,
            ranges=effective_ranges,
            standardized=STANDARDIZED_WATER_QUALITY_COLUMNS,
            required_any=[
                c
                for c in STANDARDIZED_WATER_QUALITY_COLUMNS
                if c not in ("timestamp", "location", "latitude", "longitude")
            ],
            required_label="water_quality",
            synonym_excludes=_WATER_QUALITY_SYNONYM_EXCLUDES,
            average_duplicates=True,
        )
        df, report = _apply_nitrate_unit_conversion(df, report)
    else:
        df, report = _clean_generic(df, report)

    report["rows_kept"] = int(df.shape[0])
    report["cleaned_shape"] = df.shape
    report_counts({
        "rows_read": report.get("rows_read", 0),
        "rows_kept": report.get("rows_kept", 0),
    })
    return df, report


def _maybe_pivot_long(df: pd.DataFrame, patterns: Dict[str, List[str]], report: dict) -> pd.DataFrame:
    """Convert one-row-per-parameter (long) layouts into one-column-per-parameter (wide)."""
    columns_lower = {str(c).strip().lower(): c for c in df.columns}

    parameter_col = next((columns_lower[c] for c in columns_lower if c in _LONG_FORMAT_PARAMETER_COLUMNS), None)
    value_col = next((columns_lower[c] for c in columns_lower if c in _LONG_FORMAT_VALUE_COLUMNS), None)
    if parameter_col is None or value_col is None:
        return df

    timestamp_col = next((c for c in df.columns if _match_column_name(c, patterns) == "timestamp"), None)
    location_col = next((c for c in df.columns if _match_column_name(c, patterns) == "location"), None)
    if timestamp_col is None or location_col is None:
        return df

    work = df[[timestamp_col, location_col, parameter_col, value_col]].copy()
    work["__canonical_parameter__"] = work[parameter_col].astype("string").map(
        lambda p: _match_column_name(str(p), patterns) if pd.notna(p) else None
    )
    work = work.dropna(subset=["__canonical_parameter__", timestamp_col])
    if work.empty:
        raise ValueError(
            f"Long-format file has no recognizable parameters under '{parameter_col}'"
        )

    wide = work.pivot_table(
        index=[timestamp_col, location_col],
        columns="__canonical_parameter__",
        values=value_col,
        aggfunc="mean",
    ).reset_index()
    wide.columns.name = None
    wide = wide.rename(columns={timestamp_col: "timestamp", location_col: "location"})

    report["layout"] = "long_pivoted"
    report["long_format_parameters"] = sorted(work["__canonical_parameter__"].unique().tolist())
    return wide


def _normalize_timezone_strings(series: pd.Series) -> pd.Series:
    normalized = series.str.replace(r"\s+IST$", "+05:30", regex=True, case=False)
    normalized = normalized.str.replace(r"\s+UTC$", "+00:00", regex=True, case=False)
    return normalized


def infer_date_format(ts_raw: pd.Series) -> dict:
    """Infer day-first vs month-first for ambiguous ``01/02/2021`` style dates.

    ISO timestamps are unambiguous; they set ``confidence="iso"`` and dayfirst
    stays False. For day/month/year strings, any value above 12 in the first
    position proves day-first, any value above 12 in the second proves
    month-first. If every row is ambiguous we choose month-first (the pandas
    default) and attach a warning so the user can override by supplying ISO
    dates or re-uploading after fixing the file.
    """
    parts = ts_raw.str.extract(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})")
    if parts.dropna(how="all").empty:
        return {
            "dayfirst": False,
            "confidence": "iso",
            "reason": "ISO-8601 or non-numeric date format; day/month order is explicit.",
            "warning": None,
            "ambiguous_count": 0,
        }
    first = pd.to_numeric(parts[0], errors="coerce")
    second = pd.to_numeric(parts[1], errors="coerce")
    valid = first.notna() & second.notna()
    day_evidence = int(((first > 12) & (second <= 12) & valid).sum())
    month_evidence = int(((second > 12) & (first <= 12) & valid).sum())
    ambiguous = int(
        ((first <= 12) & (second <= 12) & (first != second) & valid).sum()
    )

    if day_evidence and month_evidence:
        return {
            "dayfirst": False,
            "confidence": "conflicting",
            "reason": (
                f"Both day-first ({day_evidence}) and month-first ({month_evidence}) "
                "dates were found; interpreted month-first."
            ),
            "warning": (
                "Date format is inconsistent across rows; month-first was applied. "
                "Check the dates or re-upload with ISO-8601 timestamps."
            ),
            "ambiguous_count": ambiguous,
        }
    if day_evidence:
        return {
            "dayfirst": True,
            "confidence": "inferred",
            "reason": f"{day_evidence} row(s) have a day value above 12.",
            "warning": None,
            "ambiguous_count": ambiguous,
        }
    if month_evidence:
        return {
            "dayfirst": False,
            "confidence": "inferred",
            "reason": f"{month_evidence} row(s) have a month value above 12.",
            "warning": None,
            "ambiguous_count": ambiguous,
        }
    return {
        "dayfirst": False,
        "confidence": "ambiguous",
        "reason": "Every date could be read either way; month-first was chosen.",
        "warning": (
            "Date format is ambiguous (all day/month values are 12 or below); "
            "interpreted month-first (MM/DD/YYYY). Re-upload with ISO-8601 dates "
            "if the file is day-first."
        ),
        "ambiguous_count": ambiguous,
    }


def _count_ambiguous_dates(ts_raw: pd.Series) -> int:
    return int(infer_date_format(ts_raw).get("ambiguous_count") or 0)


_FAHRENHEIT_RE = re.compile(r"(?:°\s*f\b|fahrenheit|_f\b|\(f\))", re.IGNORECASE)
_CELSIUS_RE = re.compile(r"(?:°\s*c\b|celsius|\(c\))", re.IGNORECASE)
_MG_PER_M3_RE = re.compile(r"mg\s*/\s*m(?:3|³)", re.IGNORECASE)
_UG_PER_M3_RE = re.compile(r"(?:µ|u|μ)g\s*/\s*m(?:3|³)", re.IGNORECASE)


def detect_units(
    df: pd.DataFrame,
    dataset_type: str,
    patterns: Dict[str, List[str]],
) -> Dict[str, dict]:
    """Record the unit each source column declares (or the assumed default).

    Only explicit, unambiguous declarations are converted. When the header
    carries no unit the canonical default is kept and ``confidence`` is
    ``"assumed"``, so the data-quality report can ask the user to verify it.
    """
    water_units = {
        "total_coliform": "MPN/100 mL",
        "conductivity": "µS/cm",
        "turbidity": "NTU",
        "ph": "pH units",
    }
    air_units = {
        "pm25": "µg/m³", "pm10": "µg/m³", "no2": "µg/m³", "so2": "µg/m³",
        "co": "µg/m³", "o3": "µg/m³", "precipitation": "mm",
        "us_aqi_max": "index", "india_aqi": "index",
        "temperature": "°C", "temp_min": "°C", "temp_max": "°C",
    }
    detected: Dict[str, dict] = {}
    for raw_col in df.columns:
        canonical = _match_column_name(raw_col, patterns)
        if canonical is None or canonical in ("timestamp", "location", "latitude", "longitude"):
            continue
        header = str(raw_col).strip()
        entry = {
            "unit": water_units.get(canonical, "mg/L") if dataset_type == "water_quality"
            else air_units.get(canonical, "unknown"),
            "source_unit": None,
            "source_column": header,
            "confidence": "assumed",
            "converted": False,
        }
        if canonical in ("temperature", "temp_min", "temp_max"):
            if _FAHRENHEIT_RE.search(header):
                entry.update({
                    "unit": "°C", "source_unit": "°F", "confidence": "explicit",
                    "converted": True, "conversion": "fahrenheit",
                })
            elif _CELSIUS_RE.search(header):
                entry.update({"unit": "°C", "confidence": "explicit"})
        elif canonical in ("pm25", "pm10", "no2", "so2", "co", "o3"):
            if _MG_PER_M3_RE.search(header):
                entry.update({
                    "unit": "µg/m³", "source_unit": "mg/m³", "confidence": "explicit",
                    "converted": True, "conversion": "mg_per_m3_to_ug_per_m3", "factor": 1000.0,
                })
            elif _UG_PER_M3_RE.search(header):
                entry.update({"unit": "µg/m³", "confidence": "explicit"})
        if canonical not in detected:
            detected[canonical] = entry
    return detected


def _apply_unit_conversions(df: pd.DataFrame, report: dict) -> pd.DataFrame:
    conversions = report.get("units_detected") or {}
    for column, info in conversions.items():
        if column not in df.columns or not info.get("converted"):
            continue
        series = pd.to_numeric(df[column], errors="coerce")
        if info.get("conversion") == "fahrenheit":
            df[column] = (series - 32.0) * 5.0 / 9.0
            report.setdefault("unit_conversions", {})[column] = "converted °F to °C"
        elif info.get("conversion") == "mg_per_m3_to_ug_per_m3":
            factor = float(info.get("factor") or 1000.0)
            df[column] = series * factor
            report.setdefault("unit_conversions", {})[column] = (
                f"converted mg/m³ to µg/m³ (x {factor:g})"
            )
    return df


def _parse_numeric_series(series: pd.Series, col: str, report: dict) -> pd.Series:
    """Numeric coercion handling missing markers, sentinels, and below-detection-limit values."""
    text = series.astype("string").str.strip()
    lowered = text.str.lower()

    missing_mask = lowered.isin(_MISSING_MARKERS) | text.isna()
    if missing_mask.any():
        report["missing_markers_found"][col] = int(missing_mask.sum())

    nondetect_mask = lowered.isin(_NON_DETECT_MARKERS)
    if nondetect_mask.any():
        report["below_detection_limit_treated_missing"][col] = int(nondetect_mask.sum())

    values = pd.to_numeric(text, errors="coerce")

    sentinel_mask = values.isin(_SENTINEL_VALUES)
    if sentinel_mask.any():
        report["sentinel_values_detected"][col] = int(sentinel_mask.sum())
        values = values.mask(sentinel_mask)

    bdl_match = text.str.extract(r"^<\s*(\d+(?:\.\d+)?)$")[0]
    bdl_values = pd.to_numeric(bdl_match, errors="coerce")
    converted = bdl_values.notna() & values.isna()
    if converted.any():
        report["below_detection_limit_converted"][col] = int(converted.sum())
        values = values.fillna(bdl_values / 2.0)

    return values.astype(float)


def _apply_ranges(df: pd.DataFrame, report: dict, ranges: Dict[str, Tuple[float, float]]) -> pd.DataFrame:
    for col, (min_val, max_val) in ranges.items():
        if col not in df.columns:
            continue
        series = pd.to_numeric(df[col], errors="coerce")
        invalid_mask = (series < min_val) | (series > max_val)
        invalid_count = int(invalid_mask.sum())
        if invalid_count > 0:
            df[col] = series.mask(invalid_mask)
            report["out_of_range_values_set_to_nan"][col] = invalid_count
    return df


def _derive_temperature_mean(df: pd.DataFrame, report: dict) -> pd.DataFrame:
    """Fill missing daily temperature as (temp_min + temp_max) / 2 — an approximation, not a true daily mean."""
    if "temp_min" not in df.columns or "temp_max" not in df.columns:
        return df
    mean = (
        pd.to_numeric(df["temp_min"], errors="coerce")
        + pd.to_numeric(df["temp_max"], errors="coerce")
    ) / 2.0
    if "temperature" in df.columns:
        mask = df["temperature"].isna() & mean.notna()
    else:
        df["temperature"] = np.nan
        mask = mean.notna()
    count = int(mask.sum())
    if count:
        df.loc[mask, "temperature"] = mean[mask].astype(float)
        report["derived_columns"]["temperature"] = (
            "mean of temp_min and temp_max (approximation, not a true daily mean)"
        )
        report["derived_values_imputed"]["temperature"] = count
    return df


_RIVER_SUMMARY_RIVER_COLUMNS = {
    "name_of_the_river",
    "name_of_river",
    "river",
    "river_name",
    "name_of_the_water_body",
    "water_body",
}


def _normalized_column_token(column) -> str:
    cleaned = str(column).strip().lower()
    return re.sub(r"[\s\-\/\(\)\[\]µ]+", "_", cleaned).strip("_")


def _found_columns_text(columns, limit: int = 8) -> str:
    names = [str(c).strip() for c in columns]
    shown = ", ".join(names[:limit])
    return f"{shown}, …" if len(names) > limit else shown


def looks_like_river_summary(columns) -> bool:
    """Wide river-year summary sheets key on a river-name column plus a Year column."""
    tokens = {_normalized_column_token(c) for c in columns}
    has_year = any(token == "year" for token in tokens)
    has_river = any(token in _RIVER_SUMMARY_RIVER_COLUMNS or "river" in token for token in tokens)
    return has_year and has_river


def _clean_timeseries(
    df: pd.DataFrame,
    report: dict,
    patterns: Dict[str, List[str]],
    ranges: Dict[str, Tuple[float, float]],
    standardized: List[str],
    required_any: List[str],
    required_label: str,
    synonym_excludes: Optional[Dict[str, List[str]]] = None,
    average_duplicates: bool = False,
) -> Tuple[pd.DataFrame, dict]:
    original_columns = [str(c) for c in df.columns]
    synonym_excludes = synonym_excludes or {}

    # A file can spell the same parameter several ways (``_do``, ``d_o``,
    # ``d_o_``). All of them are grouped under one canonical name and merged
    # into a single column *before* renaming — otherwise the rename would
    # produce duplicated column names and e.g. ``df["do"]`` would return a
    # whole DataFrame instead of a Series.
    synonym_groups: Dict[str, List] = {}
    for col in df.columns:
        matched = _match_column_name(col, patterns)
        if not matched:
            continue
        token = _normalized_column_token(col)
        if any(re.search(pattern, token) for pattern in synonym_excludes.get(matched, ())):
            continue
        synonym_groups.setdefault(matched, []).append(col)

    rename_map: Dict[str, str] = {}
    merged_report: Dict[str, List[str]] = {}
    for canonical, sources in synonym_groups.items():
        if len(sources) == 1:
            rename_map[sources[0]] = canonical
            continue
        block = df.loc[:, sources].replace("", np.nan)
        merged = block.bfill(axis=1).iloc[:, 0]  # first non-null value per row, in column order
        df = df.drop(columns=[s for s in sources if s != canonical])
        df[canonical] = merged
        merged_report[canonical] = [str(s) for s in sources]

    df = df.rename(columns=rename_map)
    report["columns_renamed"] = {k: v for k, v in rename_map.items() if k != v}
    if merged_report:
        report["synonym_columns_merged"] = merged_report

    if df.columns.duplicated().any():  # defensive: never let a rename leave duplicate columns
        seen = set()
        frames = []
        for name in list(df.columns):
            if name in seen:
                continue
            seen.add(name)
            block = df.loc[:, df.columns == name]
            frames.append(block.bfill(axis=1).iloc[:, 0].rename(name) if block.shape[1] > 1 else block.iloc[:, 0])
        df = pd.concat(frames, axis=1)

    if not any(col in df.columns for col in required_any):
        raise ValueError(
            f"Uploaded file does not look like {required_label} data — "
            f"missing required columns: {', '.join(required_any)} "
            f"(found: {_found_columns_text(original_columns)})"
        )
    for required in ("timestamp", "location"):
        if required not in df.columns:
            if looks_like_river_summary(original_columns):
                raise ValueError(
                    "This looks like a river-year summary "
                    f"(columns: {_found_columns_text(original_columns)}). "
                    "Use the river-summary importer."
                )
            raise ValueError(
                f"missing required columns: {required} (found: {_found_columns_text(original_columns)})"
            )

    report_stage("converting_missing_values")
    ts_raw = _normalize_timezone_strings(df["timestamp"].astype("string").str.strip())
    date_info = infer_date_format(ts_raw)
    report["date_format"] = date_info
    ambiguous = date_info.get("ambiguous_count") or 0
    if ambiguous:
        report["ambiguous_date_strings"] = ambiguous

    parsed = pd.to_datetime(
        ts_raw,
        utc=True,
        format="mixed",
        dayfirst=bool(date_info.get("dayfirst")),
        errors="coerce",
    )
    dropped_invalid = int(parsed.isna().sum())
    if dropped_invalid:
        report["rows_dropped"]["invalid_timestamp"] = dropped_invalid
    df["timestamp"] = parsed.dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    df = df.dropna(subset=["timestamp"])

    if df.empty:
        raise ValueError("No rows with a valid timestamp after cleaning")

    df["location"] = df["location"].astype("string").fillna("").str.strip()

    parameter_cols = [c for c in standardized if c not in ("timestamp", "location")]
    present_parameter_cols = [c for c in parameter_cols if c in df.columns]
    for col in present_parameter_cols:
        df[col] = _parse_numeric_series(df[col], col, report)
    if "india_aqi" in df.columns:
        capped = int((pd.to_numeric(df["india_aqi"], errors="coerce") >= 500).sum())
        if capped:
            report.setdefault("source_aqi_at_cap", {})["india_aqi"] = capped
    df = _apply_unit_conversions(df, report)

    report_stage("checking_ranges")
    report_stage("removing_duplicate_station_dates")
    duplicates = int(df.duplicated(subset=["timestamp", "location"]).sum())
    if duplicates > 0:
        if average_duplicates:
            # Repeated sampling at one station on one day: average the numeric
            # parameters instead of silently keeping the first reading.
            numeric_cols = [
                c for c in df.columns
                if c not in ("timestamp", "location") and pd.api.types.is_numeric_dtype(df[c])
            ]
            aggregations = {
                c: ("mean" if c in numeric_cols else "first")
                for c in df.columns if c not in ("timestamp", "location")
            }
            df = df.groupby(["timestamp", "location"], as_index=False, sort=False).agg(aggregations)
            report["duplicates_averaged"] = duplicates
        else:
            df = df.drop_duplicates(subset=["timestamp", "location"], keep="first")
        report["duplicates_removed"] = duplicates

    report_stage("normalizing_timestamps")
    df = _apply_ranges(df, report, ranges)
    df = _derive_temperature_mean(df, report)
    if "temperature" in df.columns and "temperature" not in present_parameter_cols:
        present_parameter_cols.append("temperature")

    dropped_columns = [c for c in df.columns if c not in standardized]
    report["columns_dropped"] = dropped_columns
    df = df.reindex(columns=standardized)

    for col in present_parameter_cols:
        missing = int(df[col].isna().sum())
        if missing > 0:
            report["missing_values_count"][col] = missing

    return df, report


def _clean_generic(df: pd.DataFrame, report: dict) -> Tuple[pd.DataFrame, dict]:
    report_stage("removing_duplicate_headers")
    df.columns = df.columns.astype(str).str.lower().str.strip()

    report_stage("converting_missing_values")
    report_stage("checking_ranges")
    report_stage("removing_duplicate_station_dates")
    duplicates = int(df.duplicated().sum())
    if duplicates > 0:
        df = df.drop_duplicates(keep="first")
        report["duplicates_removed"] = duplicates

    report_stage("normalizing_timestamps")
    for col in df.select_dtypes(include=["number"]).columns:
        missing = int(df[col].isna().sum())
        if missing > 0:
            report["missing_values_count"][col] = missing

    return df, report


def merge_imd_files(
    file_paths: List[str],
    location: Optional[str] = None,
) -> Tuple[pd.DataFrame, dict]:
    """
    Merge separately-published IMD CSV exports (rain, tmax, tmin) into one wide
    weather frame by outer-joining on date. Returns (merged_df, report_meta).
    """
    if not file_paths:
        raise ValueError("No IMD files provided")

    frames = []
    parameters: List[str] = []
    coordinate: Optional[str] = None

    total_files = len(file_paths)
    for index, path in enumerate(file_paths, start=1):
        report_stage(
            "merging_files",
            label=f"Merging files (file {index} of {total_files})",
            counts={"files_done": index - 1, "files_total": total_files},
        )
        parameter = imd_parameter_from_source(path)
        if parameter is None:
            raise ValueError(
                f"Cannot tell the IMD parameter from the filename: {os.path.basename(path)} "
                "(expected 'rain', 'tmax' or 'tmin' in the name)"
            )
        if parameter in parameters:
            raise ValueError(f"Duplicate IMD parameter across files: {parameter}")

        raw = parse_file(path, "rainfall")
        file_coordinate = _imd_coordinate_of(raw)
        if file_coordinate is None:
            raise ValueError(
                f"{os.path.basename(path)} is not an IMD two-column export (expected 'DateTime,<lat> <lon>')"
            )
        coordinate = coordinate or file_coordinate

        part = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(raw.iloc[:, 0], errors="coerce"),
                parameter: pd.to_numeric(raw.iloc[:, 1], errors="coerce"),
            }
        ).dropna(subset=["timestamp"]).set_index("timestamp")
        frames.append(part)
        parameters.append(parameter)

    report_counts({"files_done": total_files, "files_total": total_files})
    merged = pd.concat(frames, axis=1, join="outer").reset_index()
    merged["location"] = str(location) if location else (coordinate or "")

    meta = {
        "source_format": "imd_merged",
        "imd_files": [os.path.basename(p) for p in file_paths],
        "imd_parameters": sorted(parameters),
        "imd_coordinate": coordinate,
        "location_source": "upload_field" if location else "imd_coordinate",
    }
    return merged, meta


def merge_river_summary_files(
    file_paths: List[str],
    location: Optional[str] = None,
) -> Tuple[pd.DataFrame, dict]:
    """
    Convert CPCB-style river-year summary sheets into one wide water-quality frame.

    These files hold one row per river-year with parameters as columns
    ('Name of the River', 'Year', pH, DO, BOD, …). River names become the
    location, each row is anchored to July 1 of its year (the summaries carry
    no sampling date), and columns without a canonical water-quality match are
    recorded in the report and dropped.
    """
    if not file_paths:
        raise ValueError("No river-summary files provided")

    frames: List[pd.DataFrame] = []
    mapped: Dict[str, str] = {}
    not_imported = set()
    file_names: List[str] = []

    for path in file_paths:
        raw = parse_file(path, "water_quality")
        if not looks_like_river_summary(raw.columns):
            raise ValueError(
                f"{os.path.basename(path)} does not look like a river-year summary — "
                f"expected a river-name column and a 'Year' column "
                f"(found: {_found_columns_text(raw.columns)})"
            )

        river_col = next(
            (
                column
                for column in raw.columns
                if _normalized_column_token(column) in _RIVER_SUMMARY_RIVER_COLUMNS
                or "river" in _normalized_column_token(column)
            ),
            None,
        )
        year_col = next(
            (column for column in raw.columns if _normalized_column_token(column) == "year"),
            None,
        )

        years = pd.to_numeric(raw[year_col], errors="coerce").astype("Int64").astype("string")
        part = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(years + "-07-01", errors="coerce"),
                "location": raw[river_col].astype("string").str.strip(),
            }
        )

        for column in raw.columns:
            if column in (river_col, year_col):
                continue
            canonical = _match_column_name(column, _WATER_QUALITY_COLUMN_PATTERNS)
            if canonical and canonical not in ("timestamp", "location") and canonical not in part.columns:
                part[canonical] = raw[column]
                if str(column) != canonical:
                    mapped[str(column)] = canonical
            else:
                not_imported.add(str(column))

        frames.append(part)
        file_names.append(os.path.basename(path))

    merged = pd.concat(frames, ignore_index=True)
    merged["location"] = merged["location"].fillna("")
    if location:
        blank = merged["location"].str.strip() == ""
        merged.loc[blank, "location"] = str(location)

    nitrate_sources = [src for src, canonical in mapped.items() if canonical == "nitrates"]
    merged, units_report = _apply_nitrate_unit_conversion(merged, {}, sources=nitrate_sources)

    meta = {
        "source_format": "river_summary",
        "river_files": file_names,
        "columns_mapped": mapped,
        "columns_not_imported": sorted(not_imported),
        "year_anchor": "July 1 (annual river summaries carry no sampling date)",
        "location_source": "file",
    }
    if units_report.get("unit_conversions"):
        meta["unit_conversions"] = units_report["unit_conversions"]

    return merged, meta


def _clean_value(v):
    """Convert pandas NaN/NaT to None so MongoDB stores null instead of NaN."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def dataframe_to_records(df: pd.DataFrame, dataset_id: str, dataset_type: str) -> list:
    """Convert cleaned DataFrame to list of model instances for DB insertion."""
    records = []

    if dataset_type in _AQ_DATASET_TYPES:
        for _, row in df.iterrows():
            timestamp = row['timestamp']
            if isinstance(timestamp, str):
                timestamp = pd.to_datetime(timestamp, utc=True).to_pydatetime()

            record = AirQualityCreate(
                timestamp=timestamp,
                location=str(row['location']),
                pm25=_clean_value(row.get('pm25')),
                pm10=_clean_value(row.get('pm10')),
                no2=_clean_value(row.get('no2')),
                so2=_clean_value(row.get('so2')),
                co=_clean_value(row.get('co')),
                o3=_clean_value(row.get('o3')),
                us_aqi_max=_clean_value(row.get('us_aqi_max')),
                india_aqi=_clean_value(row.get('india_aqi')),
                temperature=_clean_value(row.get('temperature')),
                temp_min=_clean_value(row.get('temp_min')),
                temp_max=_clean_value(row.get('temp_max')),
                precipitation=_clean_value(row.get('precipitation')),
                dataset_id=dataset_id,
                dataset_type=dataset_type,
            )
            records.append(record.model_dump())
        return records

    if dataset_type == "water_quality":
        for _, row in df.iterrows():
            timestamp = row['timestamp']
            if isinstance(timestamp, str):
                timestamp = pd.to_datetime(timestamp, utc=True).to_pydatetime()

            record = WaterQualityCreate(
                timestamp=timestamp,
                location=str(row['location']),
                ph=_clean_value(row.get('ph')),
                turbidity=_clean_value(row.get('turbidity')),
                tds=_clean_value(row.get('tds')),
                hardness=_clean_value(row.get('hardness')),
                chlorides=_clean_value(row.get('chlorides')),
                sulfates=_clean_value(row.get('sulfates')),
                nitrates=_clean_value(row.get('nitrates')),
                fluorides=_clean_value(row.get('fluorides')),
                iron=_clean_value(row.get('iron')),
                manganese=_clean_value(row.get('manganese')),
                do=_clean_value(row.get('do')),
                bod=_clean_value(row.get('bod')),
                ammonia=_clean_value(row.get('ammonia')),
                total_coliform=_clean_value(row.get('total_coliform')),
                conductivity=_clean_value(row.get('conductivity')),
                latitude=_clean_value(row.get('latitude')),
                longitude=_clean_value(row.get('longitude')),
                dataset_id=dataset_id,
                dataset_type=dataset_type,
            )
            records.append(record.model_dump())
        return records

    return records
