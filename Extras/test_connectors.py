"""Offline tests: the network is replaced by fake payloads shaped like the real APIs."""
from datetime import date

import pytest

import connectors as c

TODAY = date(2026, 10, 18)
today = lambda: TODAY  # noqa: E731


# ---------------------------------------------------------------- weather
def test_weather_shape_and_trailing_nulls_dropped():
    def fake(url, params, headers, **kw):
        assert params["start_date"] == "2026-10-10" and params["end_date"] == "2026-10-14"
        return {"daily": {"time": ["2026-10-10", "2026-10-11", "2026-10-12", "2026-10-13", "2026-10-14"],
                          "temperature_2m_max": [30.1, 29.0, 28.5, None, None],
                          "temperature_2m_min": [20.1, 19.0, 18.5, None, None],
                          "temperature_2m_mean": [25.0, 24.0, 23.5, None, None],
                          "precipitation_sum": [0.0, 2.5, 0.0, None, None]}}
    r = c.OpenMeteoWeather(get=fake, today=today).fetch("Bengaluru", 12.97, 77.59, "2026-10-10", "2026-10-14")
    assert list(r.df.columns) == ["date", "city", "temperature_2m_max", "temperature_2m_min",
                                  "temperature_2m_mean", "precipitation_sum"]
    assert len(r.df) == 3 and r.df.city.eq("Bengaluru").all()
    assert any("dropped 2" in n for n in r.notes)
    assert r.suggested_type == "weather" and "Open-Meteo" in r.attribution


@pytest.mark.parametrize("args,msg", [
    (("X", 12, 77, "2026-10-14", "2026-10-10"), "start date must not be after"),
    (("X", 12, 77, "2026-10-19", "2026-10-25"), "in the future"),
    (("X", 99, 77, "2026-10-01", "2026-10-02"), "latitude"),
    (("X", 12, 77, "2010-01-01", "2026-10-01"), "too long"),
    (("X", 12, 77, "10/01/2026", "2026-10-02"), "invalid date"),
])
def test_weather_validation(args, msg):
    with pytest.raises(c.ConnectorError, match=msg):
        c.OpenMeteoWeather(get=lambda *a, **k: {}, today=today).fetch(*args)


def test_weather_end_clipped_to_today():
    seen = {}
    def fake(url, params, headers, **kw):
        seen.update(params)
        return {"daily": {"time": ["2026-10-17"], "temperature_2m_max": [30], "temperature_2m_min": [20],
                          "temperature_2m_mean": [25], "precipitation_sum": [0]}}
    c.OpenMeteoWeather(get=fake, today=today).fetch("X", 12, 77, "2026-10-17", "2026-12-31")
    assert seen["end_date"] == "2026-10-18"


def test_weather_empty_response():
    with pytest.raises(c.ConnectorError, match="no daily data"):
        c.OpenMeteoWeather(get=lambda *a, **k: {"error": True}, today=today).fetch("X", 12, 77, "2026-10-01", "2026-10-02")


# ---------------------------------------------------------------- Open-Meteo air quality
def _hours(day, vals):
    return [f"{day}T{h:02d}:00" for h in range(len(vals))], vals


def test_air_quality_daily_means_units_and_completeness():
    t1, pm1 = _hours("2026-10-15", [40.0] * 24)               # complete day
    t2, pm2 = _hours("2026-10-16", [50.0] * 10 + [None] * 14)  # only 10 valid hours -> blank -> row dropped
    t3, pm3 = _hours("2026-10-18", [99.0] * 24)               # "today" -> excluded
    times = t1 + t2 + t3
    n = len(times)
    def fake(url, params, headers, **kw):
        assert params["past_days"] == 5 and "pm2_5" in params["hourly"]
        return {"hourly": {"time": times, "pm2_5": pm1 + pm2 + pm3, "pm10": [80.0] * n,
                           "nitrogen_dioxide": [20.0] * n, "sulphur_dioxide": [5.0] * n,
                           "carbon_monoxide": [1200.0] * n, "ozone": [60.0] * n}}
    r = c.OpenMeteoAirQuality(get=fake, today=today).fetch("Bengaluru", 12.97, 77.59, past_days=5)
    df = r.df
    assert list(df.columns) == ["City", "Datetime", "PM2.5", "PM10", "NO2", "SO2", "CO", "O3"]
    d15 = df[df.Datetime == "2026-10-15"].iloc[0]
    assert d15["PM2.5"] == 40.0 and d15["CO"] == pytest.approx(1.2)          # ug/m3 -> mg/m3
    d16 = df[df.Datetime == "2026-10-16"].iloc[0]
    assert d16["PM2.5"] != d16["PM2.5"]                                      # NaN: <16 valid hours
    assert "2026-10-18" not in set(df.Datetime)
    assert any("MODELLED" in n for n in r.notes)


@pytest.mark.parametrize("bad", [0, 93, "5", None])
def test_air_quality_past_days_validation(bad):
    with pytest.raises(c.ConnectorError):
        c.OpenMeteoAirQuality(get=lambda *a, **k: {}, today=today).fetch("X", 12, 77, past_days=bad)


# ---------------------------------------------------------------- OpenAQ
def _openaq_fake(url, params, headers, **kw):
    assert headers["X-API-Key"] == "k"
    if url.endswith("/locations"):
        return {"results": [
            {"id": 1, "name": "Near, PM2.5 only", "distance": 500,
             "sensors": [{"id": 10, "parameter": {"name": "pm25", "units": "µg/m³"}}]},
            {"id": 2, "name": "Farther, many sensors", "distance": 4000,
             "sensors": [{"id": 21, "parameter": {"name": "pm25", "units": "µg/m³"}},
                         {"id": 22, "parameter": {"name": "pm10", "units": "µg/m³"}},
                         {"id": 23, "parameter": {"name": "co", "units": "ppm"}},
                         {"id": 24, "parameter": {"name": "no2", "units": "ppb"}},
                         {"id": 25, "parameter": {"name": "temperature", "units": "c"}}]}]}
    sid = int(url.split("/sensors/")[1].split("/")[0])
    val = {21: 60.0, 22: 120.0, 23: 2.0, 24: 10.0}[sid]
    unit = {21: "µg/m³", 22: "µg/m³", 23: "ppm", 24: "ppb"}[sid]
    return {"results": [{"value": val, "parameter": {"units": unit},
                         "period": {"datetimeFrom": {"local": "2026-10-10T00:00:00+05:30", "utc": "2026-10-09T18:30:00Z"}}}]}


def test_openaq_picks_best_station_and_converts_units():
    r = c.OpenAQ(api_key="k", get=_openaq_fake, today=today).fetch("Delhi", 28.6, 77.2, "2026-10-10", "2026-10-10")
    row = r.df.iloc[0]
    assert row["Datetime"] == "2026-10-10" and row["PM2.5"] == 60.0 and row["PM10"] == 120.0
    assert row["CO"] == pytest.approx(2.0 * 1.145)            # ppm -> mg/m3
    assert row["NO2"] == pytest.approx(10.0 * 1.88)           # ppb -> ug/m3
    assert any("Farther, many sensors" in n for n in r.notes)  # chose 3+ pollutants over nearest 1


def test_openaq_requires_key(monkeypatch):
    monkeypatch.delenv("OPENAQ_API_KEY", raising=False)
    with pytest.raises(c.ConnectorError, match="API key"):
        c.OpenAQ(get=_openaq_fake, today=today).fetch("Delhi", 28.6, 77.2, "2026-10-10", "2026-10-10")


def test_openaq_no_station():
    fake = lambda url, p, h, **k: {"results": []}  # noqa: E731
    with pytest.raises(c.ConnectorError, match="no station"):
        c.OpenAQ(api_key="k", get=fake, today=today).fetch("X", 1, 1, "2026-10-10", "2026-10-10")


# ---------------------------------------------------------------- Water Quality Portal
WQP_CSV = """MonitoringLocationIdentifier,ActivityStartDate,CharacteristicName,ResultMeasureValue,ResultMeasure/MeasureUnitCode,ResultDetectionConditionText
USGS-1,2026-01-05,pH,7.4,std units,
USGS-1,2026-01-05,Dissolved oxygen (DO),8.0,mg/l,
USGS-1,2026-01-05,Dissolved oxygen (DO),9.0,mg/l,
USGS-1,2026-01-05,Dissolved oxygen (DO),95,%,
USGS-1,2026-01-05,Turbidity,3.2,NTU,
USGS-1,2026-01-05,Turbidity,0.5,NTU,Not Detected
USGS-1,2026-01-05,Specific conductance,450,uS/cm @25C,
USGS-2,2026-01-06,pH,6.9,,
USGS-2,2026-01-06,Temperature,18,deg C,
"""


def test_wqp_pivot_filters_and_averages():
    def fake(url, params, headers, **kw):
        assert kw.get("as_text") is True
        assert params["startDateLo"] == "01-01-2026" and params["within"] == 10
        assert params["characteristicName"][0] == "pH"
        return WQP_CSV
    r = c.WaterQualityPortal(get=fake, today=today).fetch("2026-01-01", "2026-01-31", lat=37.0, lon=-120.0, within_miles=10)
    df = r.df.set_index(["location", "timestamp"])
    a = df.loc[("USGS-1", "2026-01-05")]
    assert a["ph"] == 7.4 and a["do"] == 8.5              # two DO results averaged, % row dropped
    assert a["turbidity"] == 3.2 and a["conductivity"] == 450  # 'Not Detected' row dropped
    assert df.loc[("USGS-2", "2026-01-06"), "ph"] == 6.9    # blank unit allowed for pH
    assert any("not-detected" in n for n in r.notes) and any("not comparable" in n for n in r.notes)
    assert r.suggested_type == "water_quality"


def test_wqp_requires_a_location_filter_and_small_radius():
    w = c.WaterQualityPortal(get=lambda *a, **k: WQP_CSV, today=today)
    with pytest.raises(c.ConnectorError, match="lat/lon/within_miles or a statecode"):
        w.fetch("2026-01-01", "2026-01-31")
    with pytest.raises(c.ConnectorError, match="between 0 and 25"):
        w.fetch("2026-01-01", "2026-01-31", lat=1, lon=1, within_miles=500)
    with pytest.raises(c.ConnectorError, match="unknown parameter"):
        w.fetch("2026-01-01", "2026-01-31", statecode="US:06", parameters=("nitrate",))


def test_wqp_unexpected_format_lists_columns():
    fake = lambda *a, **k: "Foo,Bar\n1,2\n"  # noqa: E731
    with pytest.raises(c.ConnectorError, match="unexpected response format"):
        c.WaterQualityPortal(get=fake, today=today).fetch("2026-01-01", "2026-01-31", statecode="US:06")


# ---------------------------------------------------------------- misc
def test_fetch_key_is_stable_and_order_independent():
    assert c.fetch_key("weather", {"a": 1, "b": 2}) == c.fetch_key("weather", {"b": 2, "a": 1})
    assert c.fetch_key("weather", {"a": 1}) != c.fetch_key("weather", {"a": 2})


class _Resp:
    def __init__(self, code, body=None):
        self.status_code, self._b, self.text = code, body or {}, "x"
    def json(self):
        return self._b


def test_default_get_retries_5xx_but_not_4xx(monkeypatch):
    import httpx
    monkeypatch.setattr(c.time, "sleep", lambda s: None)
    calls = {"n": 0}
    def flaky(*a, **k):
        calls["n"] += 1
        return _Resp(503) if calls["n"] < 3 else _Resp(200, {"ok": 1})
    monkeypatch.setattr(httpx, "get", flaky)
    assert c.default_get("https://x/y") == {"ok": 1} and calls["n"] == 3
    calls["n"] = 0
    monkeypatch.setattr(httpx, "get", lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1), _Resp(404))[1])
    with pytest.raises(c.ConnectorError, match="HTTP 404"):
        c.default_get("https://x/y")
    assert calls["n"] == 1  # 4xx fails fast, no retries
