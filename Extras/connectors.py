"""
connectors.py: fetch environmental data from public APIs *inside the project*,
instead of downloading files by hand.

Each connector returns a FetchResult whose DataFrame already uses the column
layout your upload pipeline understands, so "fetch" can reuse the same
parse -> clean -> Mongo write -> ML steps as an uploaded file:

  OpenMeteoWeather       -> date, city, temperature_2m_max/min/mean, precipitation_sum
                            (same layout as weather_daily.csv)           [no key]
  OpenMeteoAirQuality    -> City, Datetime, PM2.5, PM10, NO2, SO2, CO, O3
                            MODELLED (CAMS) values, not station readings [no key]
  OpenAQ                 -> City, Datetime, PM2.5, PM10, NO2, SO2, CO, O3
                            real station data                  [free OPENAQ_API_KEY]
  WaterQualityPortal     -> location, timestamp, ph, do, turbidity, conductivity, ...
                            US Water Quality Portal (long format -> pivoted)  [no key]

Not covered (no API I could confirm): IMD gridded files and Indian water
quality (CPCB / India-WRIS). Keep those as file imports.

All HTTP goes through one injectable `get` function (timeouts, retries, clear
errors), which also makes the connectors testable without the network.
Units: CO is returned in mg/m3 and the other gases in ug/m3, as CPCB AQI needs.
Every connector is verified only against sample payloads; run one live call per
connector on your machine before relying on it.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Callable, Optional

import pandas as pd


class ConnectorError(Exception):
    """Message is safe to show to the user."""


@dataclass
class FetchResult:
    df: pd.DataFrame
    source: str
    suggested_type: str
    attribution: str
    params: dict
    notes: list = field(default_factory=list)
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def meta(self) -> dict:
        """Store this on the dataset record so every dataset says where it came from."""
        return {"source": self.source, "attribution": self.attribution, "params": self.params,
                "notes": self.notes, "fetched_at": self.fetched_at, "rows": int(len(self.df))}


# ---------------------------------------------------------------- HTTP

def default_get(url: str, params: Optional[dict] = None, headers: Optional[dict] = None,
                timeout: float = 30, retries: int = 3, as_text: bool = False) -> Any:
    """GET with timeout + retry on network errors, 429 and 5xx. 4xx fails fast."""
    import httpx  # imported lazily so tests do not need it
    last = "unknown error"
    for attempt in range(retries):
        try:
            r = httpx.get(url, params=params, headers=headers, timeout=timeout)
        except httpx.HTTPError as e:
            last = f"network error: {e}"
        else:
            if r.status_code == 429 or r.status_code >= 500:
                last = f"HTTP {r.status_code}"
            elif r.status_code >= 400:
                raise ConnectorError(f"{url.split('?')[0]} returned HTTP {r.status_code}: {r.text[:200]}")
            else:
                return r.text if as_text else r.json()
        time.sleep(1.5 * (attempt + 1))
    raise ConnectorError(f"{url.split('?')[0]} failed after {retries} tries ({last})")


# ---------------------------------------------------------------- helpers

CITIES = {  # name -> (lat, lon); lets the UI offer a dropdown with no geocoding call
    "Bengaluru": (12.9716, 77.5946), "Mysuru": (12.2958, 76.6394), "Delhi": (28.6139, 77.2090),
    "Mumbai": (19.0760, 72.8777), "Chennai": (13.0827, 80.2707), "Kolkata": (22.5726, 88.3639),
    "Hyderabad": (17.3850, 78.4867), "Pune": (18.5204, 73.8567), "Raipur": (21.2514, 81.6296),
    "Vadodara": (22.3072, 73.1812),
}


def _check_coords(lat, lon):
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        raise ConnectorError("latitude and longitude must be numbers")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ConnectorError("latitude must be in [-90, 90] and longitude in [-180, 180]")
    return lat, lon


def _as_date(v) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except ValueError:
        raise ConnectorError(f"invalid date '{v}', expected YYYY-MM-DD")


def _check_range(start, end, max_days: int, today: date):
    s, e = _as_date(start), _as_date(end)
    if s > e:
        raise ConnectorError("start date must not be after end date")
    if s > today:
        raise ConnectorError("start date is in the future")
    e = min(e, today)
    if (e - s).days + 1 > max_days:
        raise ConnectorError(f"date range too long (max {max_days} days for this source)")
    return s, e


def fetch_key(source: str, params: dict) -> str:
    """Stable id for a request, so the same fetch is served from the DB cache, not re-downloaded."""
    return hashlib.sha1(json.dumps([source, params], sort_keys=True, default=str).encode()).hexdigest()[:16]


def _norm_unit(u: Any) -> str:
    return str(u or "").replace("\u00b5", "u").replace("\u03bc", "u").replace("\u00b3", "3").strip().lower()


# ---------------------------------------------------------------- Open-Meteo weather

class OpenMeteoWeather:
    name = "open_meteo_weather"
    URL = "https://archive-api.open-meteo.com/v1/archive"
    DAILY = ["temperature_2m_max", "temperature_2m_min", "temperature_2m_mean", "precipitation_sum"]
    MAX_DAYS = 3660

    def __init__(self, get: Callable = default_get, today: Callable = date.today):
        self.get, self.today = get, today

    def fetch(self, city: str, lat, lon, start, end) -> FetchResult:
        lat, lon = _check_coords(lat, lon)
        s, e = _check_range(start, end, self.MAX_DAYS, self.today())
        data = self.get(self.URL, {"latitude": lat, "longitude": lon, "start_date": s.isoformat(),
                                   "end_date": e.isoformat(), "daily": ",".join(self.DAILY),
                                   "timezone": "Asia/Kolkata"}, {})
        daily = (data or {}).get("daily")
        if not daily or "time" not in daily:
            raise ConnectorError("Open-Meteo returned no daily data for this location/date range")
        df = pd.DataFrame(daily).rename(columns={"time": "date"})
        df.insert(1, "city", city)
        value_cols = [c for c in df.columns if c not in ("date", "city")]
        n0 = len(df)
        df = df.dropna(subset=value_cols, how="all").reset_index(drop=True)
        notes = []
        if len(df) < n0:
            notes.append(f"dropped {n0 - len(df)} day(s) with no data yet (the archive lags real time)")
        if df.empty:
            raise ConnectorError("no data available for this range yet")
        return FetchResult(df, self.name, "weather", "Weather data by Open-Meteo.com (ERA5 reanalysis, CC BY 4.0)",
                           {"city": city, "lat": lat, "lon": lon, "start": str(s), "end": str(e)}, notes)


# ---------------------------------------------------------------- Open-Meteo air quality (modelled)

class OpenMeteoAirQuality:
    name = "open_meteo_air_quality"
    URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
    HOURLY = {"pm2_5": "PM2.5", "pm10": "PM10", "nitrogen_dioxide": "NO2",
              "sulphur_dioxide": "SO2", "carbon_monoxide": "CO", "ozone": "O3"}
    MIN_HOURS = 16  # a daily mean needs >= 16 valid hours (CPCB-style completeness rule)

    def __init__(self, get: Callable = default_get, today: Callable = date.today):
        self.get, self.today = get, today

    def fetch(self, city: str, lat, lon, past_days: int = 30) -> FetchResult:
        lat, lon = _check_coords(lat, lon)
        if not (isinstance(past_days, int) and 1 <= past_days <= 92):
            raise ConnectorError("past_days must be an integer from 1 to 92 for this source")
        data = self.get(self.URL, {"latitude": lat, "longitude": lon, "hourly": ",".join(self.HOURLY),
                                   "past_days": past_days, "forecast_days": 1, "timezone": "Asia/Kolkata"}, {})
        hourly = (data or {}).get("hourly")
        if not hourly or "time" not in hourly:
            raise ConnectorError("Open-Meteo returned no hourly air-quality data for this location")
        df = pd.DataFrame(hourly)
        df["date"] = pd.to_datetime(df["time"]).dt.date
        df = df[df["date"] < self.today()]  # complete days only; no forecast hours
        cols = [c for c in self.HOURLY if c in df.columns]
        if not cols:
            raise ConnectorError("response contained none of the expected pollutants")
        g = df.groupby("date")
        daily = g[cols].mean().where(g[cols].count() >= self.MIN_HOURS)
        if "carbon_monoxide" in daily:
            daily["carbon_monoxide"] = daily["carbon_monoxide"] / 1000.0  # ug/m3 -> mg/m3
        out = daily.rename(columns=self.HOURLY).reset_index().rename(columns={"date": "Datetime"})
        out["Datetime"] = out["Datetime"].astype(str)
        out = out.dropna(subset=[c for c in self.HOURLY.values() if c in out], how="all").reset_index(drop=True)
        if out.empty:
            raise ConnectorError("no complete days of air-quality data returned")
        out.insert(0, "City", city)
        notes = ["MODELLED values (Copernicus CAMS, coarse global grid outside Europe), not station measurements",
                 "daily mean of hourly values; days with fewer than 16 valid hours are left blank",
                 "CO converted from ug/m3 to mg/m3"]
        return FetchResult(out, self.name, "air_quality",
                           "Air quality data by Open-Meteo.com, based on Copernicus CAMS (modelled)",
                           {"city": city, "lat": lat, "lon": lon, "past_days": past_days}, notes)


# ---------------------------------------------------------------- OpenAQ v3 (stations)

class OpenAQ:
    name = "openaq"
    BASE = "https://api.openaq.org/v3"
    TARGET = {"pm25": "PM2.5", "pm10": "PM10", "no2": "NO2", "so2": "SO2", "co": "CO", "o3": "O3"}
    PPB_TO_UGM3 = {"no2": 1.88, "so2": 2.62, "o3": 1.96}  # 25 C, 1 atm
    CO_PPM_TO_MGM3 = 1.145
    MAX_DAYS = 1000

    def __init__(self, api_key: Optional[str] = None, get: Callable = default_get, today: Callable = date.today):
        self.api_key = api_key or os.getenv("OPENAQ_API_KEY")
        self.get, self.today = get, today

    @staticmethod
    def _pname(sensor: dict) -> str:
        p = (sensor.get("parameter") or {}).get("name") or str(sensor.get("name", "")).split(" ")[0]
        return str(p).lower()

    def _pick_location(self, locations: list):
        best = None
        for loc in locations:
            found = {}
            for s in loc.get("sensors") or []:
                p = self._pname(s)
                if p in self.TARGET and p not in found:
                    found[p] = (s.get("id"), (s.get("parameter") or {}).get("units"))
            if not found:
                continue
            rank = (-len(found), loc.get("distance", float("inf")))
            if best is None or rank < best[0]:
                best = (rank, loc, found)
        if best is None:
            raise ConnectorError("no station with PM2.5/PM10/gas sensors found near this location; try a larger radius")
        return best[1], best[2]

    def _to_standard(self, p: str, value: float, units: str):
        u = _norm_unit(units)
        if p == "co":
            if u == "ppm":
                return value * self.CO_PPM_TO_MGM3
            if u == "ppb":
                return value * self.CO_PPM_TO_MGM3 / 1000
            if u in ("ug/m3",):
                return value / 1000.0
            if u in ("mg/m3",):
                return value
            return None
        if u in ("ug/m3", ""):
            return value
        if p in self.PPB_TO_UGM3 and u == "ppb":
            return value * self.PPB_TO_UGM3[p]
        if p in self.PPB_TO_UGM3 and u == "ppm":
            return value * self.PPB_TO_UGM3[p] * 1000
        return None

    def fetch(self, city: str, lat, lon, start, end, radius_m: int = 25000) -> FetchResult:
        if not self.api_key:
            raise ConnectorError("OpenAQ needs a free API key: register at https://explore.openaq.org "
                                 "and set the OPENAQ_API_KEY environment variable")
        lat, lon = _check_coords(lat, lon)
        s, e = _check_range(start, end, self.MAX_DAYS, self.today())
        hdr = {"X-API-Key": self.api_key}
        locs = (self.get(f"{self.BASE}/locations", {"coordinates": f"{lat},{lon}", "radius": radius_m, "limit": 50}, hdr)
                or {}).get("results", [])
        loc, sensors = self._pick_location(locs)
        records, notes = [], [f"station: {loc.get('name', loc.get('id'))} (OpenAQ location {loc.get('id')})"]
        for p, (sid, units) in sensors.items():
            res = (self.get(f"{self.BASE}/sensors/{sid}/days",
                            {"datetime_from": s.isoformat(), "datetime_to": e.isoformat(), "limit": 1000}, hdr)
                   or {}).get("results", [])
            dropped = 0
            for r in res:
                per = (r.get("period") or {}).get("datetimeFrom") or {}
                day = str(per.get("local") or per.get("utc") or "")[:10]
                v = r.get("value")
                if not day or v is None:
                    continue
                v = self._to_standard(p, float(v), (r.get("parameter") or {}).get("units") or units)
                if v is None:
                    dropped += 1
                    continue
                records.append({"Datetime": day, "param": self.TARGET[p], "value": v})
            if dropped:
                notes.append(f"{self.TARGET[p]}: skipped {dropped} value(s) in an unrecognised unit")
        if not records:
            raise ConnectorError("the nearest station returned no daily values for this date range")
        wide = pd.DataFrame(records).pivot_table(index="Datetime", columns="param", values="value", aggfunc="mean")
        wide = wide.reset_index()
        wide.columns.name = None
        wide.insert(0, "City", city)
        return FetchResult(wide, self.name, "air_quality", "Data from OpenAQ (government monitoring networks)",
                           {"city": city, "lat": lat, "lon": lon, "start": str(s), "end": str(e), "radius_m": radius_m}, notes)


# ---------------------------------------------------------------- US Water Quality Portal

class WaterQualityPortal:
    name = "water_quality_portal"
    LEGACY_URL = "https://www.waterqualitydata.us/data/Result/search"
    WQX3_URL = "https://www.waterqualitydata.us/wqx3/Result/search"  # newer USGS data; column names may differ
    CHARS = {"ph": "pH", "do": "Dissolved oxygen (DO)", "turbidity": "Turbidity",
             "conductivity": "Specific conductance", "temperature": "Temperature, water",
             "bod": "Biochemical oxygen demand, standard conditions"}
    UNIT_OK = {"ph": lambda u: u in ("", "std units", "none", "nan"),
               "do": lambda u: u == "mg/l",
               "turbidity": lambda u: u in ("ntu", "fnu", "ntru"),
               "conductivity": lambda u: u.startswith("us/cm") or u.startswith("umho"),
               "temperature": lambda u: u in ("deg c", "degc"),
               "bod": lambda u: u == "mg/l"}
    REQUIRED = ["MonitoringLocationIdentifier", "ActivityStartDate", "CharacteristicName", "ResultMeasureValue"]
    MAX_DAYS = 1830

    def __init__(self, get: Callable = default_get, today: Callable = date.today):
        self.get, self.today = get, today

    def fetch(self, start, end, lat=None, lon=None, within_miles=None, statecode=None,
              parameters=("ph", "do", "turbidity", "conductivity", "temperature"),
              base_url: Optional[str] = None, max_rows: int = 200000) -> FetchResult:
        s, e = _check_range(start, end, self.MAX_DAYS, self.today())
        bad = [p for p in parameters if p not in self.CHARS]
        if bad:
            raise ConnectorError(f"unknown parameter(s) {bad}; choose from {list(self.CHARS)}")
        q = {"mimeType": "csv", "zip": "no", "startDateLo": s.strftime("%m-%d-%Y"),
             "startDateHi": e.strftime("%m-%d-%Y"), "characteristicName": [self.CHARS[p] for p in parameters]}
        if lat is not None and lon is not None and within_miles is not None:
            lat, lon = _check_coords(lat, lon)
            if not 0 < float(within_miles) <= 25:
                raise ConnectorError("within_miles must be between 0 and 25 to keep the download small")
            q.update({"lat": lat, "long": lon, "within": within_miles})
        elif statecode:
            q["statecode"] = statecode
        else:
            raise ConnectorError("give either lat/lon/within_miles or a statecode (e.g. 'US:06')")
        text = self.get(base_url or self.LEGACY_URL, q, {}, as_text=True)
        if not text or not text.strip():
            raise ConnectorError("the Water Quality Portal returned no data for this query")
        raw = pd.read_csv(io.StringIO(text), dtype=str, nrows=max_rows)
        missing = [c for c in self.REQUIRED if c not in raw.columns]
        if missing:
            raise ConnectorError(f"unexpected response format, missing {missing}; got columns {list(raw.columns)[:15]}")
        notes = []
        if len(raw) >= max_rows:
            notes.append(f"result truncated at {max_rows} rows; narrow the area or dates")
        det = raw.get("ResultDetectionConditionText", pd.Series("", index=raw.index)).fillna("")
        n_det = int((det.str.strip() != "").sum())
        raw = raw[det.str.strip() == ""]
        if n_det:
            notes.append(f"dropped {n_det} below-detection / not-detected result(s)")
        rev = {v: k for k, v in self.CHARS.items()}
        raw = raw.assign(key=raw["CharacteristicName"].map(rev),
                         value=pd.to_numeric(raw["ResultMeasureValue"], errors="coerce"),
                         unit=raw.get("ResultMeasure/MeasureUnitCode", pd.Series("", index=raw.index)).map(_norm_unit))
        raw = raw.dropna(subset=["key", "value"])
        ok = raw.apply(lambda r: self.UNIT_OK[r["key"]](r["unit"]), axis=1) if len(raw) else pd.Series([], dtype=bool)
        n_unit = int((~ok).sum())
        raw = raw[ok]
        if n_unit:
            notes.append(f"dropped {n_unit} result(s) in units that are not comparable")
        if raw.empty:
            raise ConnectorError("no usable measurements after filtering")
        wide = raw.pivot_table(index=["MonitoringLocationIdentifier", "ActivityStartDate"],
                               columns="key", values="value", aggfunc="mean").reset_index()
        wide.columns.name = None
        wide = wide.rename(columns={"MonitoringLocationIdentifier": "location", "ActivityStartDate": "timestamp"})
        notes.append("US monitoring sites; sample-based (irregular dates), several results per day are averaged")
        return FetchResult(wide, self.name, "water_quality",
                           "Data from the Water Quality Portal (USGS, EPA, NWQMC)",
                           {k: v for k, v in q.items() if k not in ("mimeType", "zip")}, notes)


REGISTRY = {"weather": OpenMeteoWeather, "air_quality_model": OpenMeteoAirQuality,
            "air_quality_stations": OpenAQ, "water_quality_us": WaterQualityPortal}
