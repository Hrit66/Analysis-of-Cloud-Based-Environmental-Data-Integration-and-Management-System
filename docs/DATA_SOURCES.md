# Data Sources

This platform combines two classes of environmental data: **live sources with real APIs**
and **file-based sources** that must be imported manually.

## API-based (live ingestion)

| Source | Data | Access |
| --- | --- | --- |
| Open-Meteo | Air quality (PM2.5, PM10, NO2, SO2, CO, O3), weather, temperature, rainfall | REST API, scheduled fetch |
| OpenAQ | Air quality measurements | REST API |

These are used for ongoing ingestion because they expose queryable, well-documented
interfaces and need no manual intervention.

## IMD (India Meteorological Department) — file import

IMD publishes rainfall and temperature data as **gridded binary products** distributed
through its website. There is **no real-time query API** — the data is only available as
bulk files that must be downloaded and converted. Because of this, IMD data is supported
through **file import** rather than live ingestion.

### Format

Individual daily CSV exports are two-column files named by parameter:

```
DateTime,12.97 77.59
2023-01-01,0.0000
2023-01-02,12.5000
```

- Column 1 is the date.
- Column 2 is the measured value; the header is the station's `latitude longitude`.
- The parameter is carried in the **filename** (`rain`, `tmax`, `tmin`).
- Rain, maximum temperature and minimum temperature arrive as **separate files**.

### Import behaviour

1. Rain / tmax / tmin files are uploaded together (or individually) and merged with an
   **outer join on date** — a missing day in one file does not drop it from the others.
2. Parameters are mapped to canonical columns: `rain → precipitation`,
   `tmax → temp_max`, `tmin → temp_min`.
3. A daily mean temperature is **derived** as `(temp_min + temp_max) / 2` where both are
   present. This is an **approximation, not the true daily mean**; the cleaning report
   labels it as derived so it is never mistaken for measured data.
   Note: the Bengaluru weather dataset combines a **30-year rain series (1995–2024,
   exported with `imdlib`)** with the temperature exports; temperature columns are
   `null` outside their coverage window, and the rainfall model's climatology
   (rain-chance card) uses the full 30 years.
4. The location is taken from the upload form if provided, otherwise from the coordinate
   header (e.g. `12.97 77.59`).
5. IMD sentinel values (e.g. `-999`) are cleared to `null`, and rainfall is range-checked —
   negative rainfall is impossible and set to `null`.
6. A file that cannot be identified (missing value column, or parameter not derivable from
   the filename) is rejected with an explicit error instead of importing bad data.

### Deliberately corrupted test fixtures

`back/tests/fixtures/` includes an IMD trio (`imd_rain_testcity.csv`,
`imd_tmax_testcity.csv`, `imd_tmin_testcity.csv`) plus corrupted copies: one with
sentinels and negative rainfall (`imd_rain_corrupt_bengaluru.csv`), one missing its value
column (`imd_broken_missing_column.csv`). The pytest suite in
`back/tests/test_imd_pipeline.py` verifies merging, derived temperature, sentinel
handling, range validation, location attachment and the upload endpoint end to end.

## Dataset types

Uploads map to four dashboard types: `air_quality` (AQI), `water_quality` (WQI),
`temperature`, `rainfall`. Standard uploads validate that the file actually contains the
required columns for the selected type and fail with a clear
`missing required columns:` message otherwise. Uploads are idempotent — re-uploading the
same file (or the same set of IMD files) returns the existing dataset instead of creating
duplicates.
