"""CPCB surface-water import (waterKarna.csv shape).

Regression tests for the messy-header family: synonym columns that collapse
into duplicate names after normalization (``_do``/``d_o``/``d_o_``), low
coverage parameters, a pH outlier, repeated station+date samples, and
coordinates that must survive cleaning as numeric fields.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.services.pipeline_interface import clean_dataframe, dataframe_to_records

MESSY_HEADER = [
    "Station_Name", "Date", "ph_fld", "ph_gen", "ph", "_do", "do_sat_", "d_o", "d_o_",
    "bod", "bod3_27", "turb", "ec_fld", "ec_gen", "no3_n", "na", "na_", "no2_n",
    "no2__n", "Latitude", "Longitude", "empty_1",
]
MESSY_ROWS = [
    ["LAKE A", "2018-01-09 08:30:00", "", "7.2", "", "6.0", "95.0", "", "", "", "3.0", "4.2", "", "420.0", "3.1", "", "", "0.5", "", "13.01", "77.57", ""],
    ["LAKE B", "2018-07-26 08:30:00", "", "27.0", "", "1.2", "96.0", "", "", "", "8.0", "", "", "", "1.2", "", "", "0.4", "", "12.98", "77.61", ""],
    ["LAKE C", "2019-03-14 09:00:00", "", "7.5", "7.5", "", "", "", "", "", "2.0", "", "", "", "", "", "", "2.2", "", "12.90", "77.50", ""],
    ["LAKE C", "2019-03-14 09:00:00", "", "8.5", "8.5", "4.0", "", "", "", "", "", "2.0", "", "600.0", "", "", "", "", "", "12.90", "77.50", ""],
    ["LAKE D", "2021-12-28 08:30:00", "", "6.8", "", "", "", "", "6.0", "", "1.5", "", "", "", "", "", "", "", "", "13.05", "77.70", ""],
]
MESSY_CSV = "\n".join([",".join(MESSY_HEADER)] + [",".join(row) for row in MESSY_ROWS]) + "\n"


def _load():
    from io import StringIO

    return clean_dataframe(pd.read_csv(StringIO(MESSY_CSV)), "water_quality")


class TestSynonymMerge:
    def test_messy_headers_clean_without_duplicate_columns(self):
        cleaned, report = _load()

        assert not cleaned.columns.duplicated().any()
        assert list(cleaned.columns).count("do") == 1
        assert sorted(report["synonym_columns_merged"]["do"]) == ["_do", "d_o", "d_o_"]
        assert report["synonym_columns_merged"]["ph"] == ["ph_fld", "ph_gen", "ph"]
        assert report["synonym_columns_merged"]["bod"] == ["bod", "bod3_27"]
        assert report["synonym_columns_merged"]["conductivity"] == ["ec_fld", "ec_gen"]

    def test_first_non_null_value_wins_per_row(self):
        cleaned, _ = _load()
        rows = cleaned.set_index("location")

        assert rows.loc["LAKE A", "ph"] == pytest.approx(7.2)   # ph_fld empty -> ph_gen
        assert rows.loc["LAKE C", "ph"] == pytest.approx(8.0)   # both present -> first column order, then averaged over the day's two samples
        assert rows.loc["LAKE A", "do"] == pytest.approx(6.0)
        assert rows.loc["LAKE D", "do"] == pytest.approx(6.0)   # d_o_ carries the value
        assert rows.loc["LAKE A", "bod"] == pytest.approx(3.0)  # empty bod -> bod3_27
        assert rows.loc["LAKE A", "conductivity"] == pytest.approx(420.0)

    def test_do_saturation_is_not_merged_into_do(self):
        cleaned, report = _load()

        assert "do_sat_" in report["columns_dropped"]
        rows = cleaned.set_index("location")
        assert rows.loc["LAKE B", "do"] == pytest.approx(1.2)  # not 96 (saturation %)

    def test_unnamed_low_coverage_parameters_stay_nan(self):
        cleaned, report = _load()
        rows = cleaned.set_index("location")

        assert rows.loc["LAKE B", "turbidity"] != rows.loc["LAKE B", "turbidity"]  # NaN, not 0
        assert rows.loc["LAKE A", "turbidity"] == pytest.approx(4.2)
        assert "empty_1" in report["columns_dropped"]


class TestNitrateUnitNormalization:
    def test_no3_n_is_converted_to_nitrate_as_no3(self):
        cleaned, report = _load()
        rows = cleaned.set_index("location")

        # 3.1 mg/L as N -> 13.72 mg/L as NO3 (BIS limit is 45 as NO3)
        assert rows.loc["LAKE A", "nitrates"] == pytest.approx(3.1 * 4.4266, abs=0.01)
        assert "converted nitrate-N" in report["unit_conversions"]["nitrates"]
        assert "no3_n" in report["unit_conversions"]["nitrates"]

    def test_column_already_named_nitrates_is_not_converted(self):
        from io import StringIO

        csv = "Station_Name,Date,nitrates\nLAKE A,2018-01-09 08:30:00,45.0\n"
        cleaned, report = clean_dataframe(pd.read_csv(StringIO(csv)), "water_quality")

        assert cleaned.iloc[0]["nitrates"] == pytest.approx(45.0)
        assert "nitrates" not in report["unit_conversions"]


class TestRowLevelCleaning:
    def test_ph_outlier_is_blanked_and_reported(self):
        cleaned, report = _load()
        rows = cleaned.set_index("location")

        assert np.isnan(rows.loc["LAKE B", "ph"])
        assert report["out_of_range_values_set_to_nan"]["ph"] == 1

    def test_duplicate_station_and_date_rows_are_averaged(self):
        cleaned, report = _load()
        lake_c = cleaned[cleaned.location == "LAKE C"]

        assert len(lake_c) == 1  # two samples on 2019-03-14 collapsed to one
        assert lake_c.iloc[0]["ph"] == pytest.approx(8.0)  # (7.5 + 8.5) / 2
        assert lake_c.iloc[0]["do"] == pytest.approx(4.0)
        assert report["duplicates_removed"] == 1
        assert report["duplicates_averaged"] == 1

    def test_coordinates_and_timestamp_reach_records(self):
        cleaned, _ = _load()
        records = dataframe_to_records(cleaned, "ds", "water_quality")
        sample = next(r for r in records if r["location"] == "LAKE A")

        assert sample["latitude"] == pytest.approx(13.01)
        assert sample["longitude"] == pytest.approx(77.57)
        assert sample["bod"] == pytest.approx(3.0)
        assert sample["timestamp"].strftime("%Y-%m-%d") == "2018-01-09"


class TestColiformStorage:
    def test_tcol_mpn_becomes_numeric_total_coliform(self):
        csv = "Station_Name,Date,tcol_mpn\nLAKE A,2018-01-09 08:30:00,54000\n"
        from io import StringIO

        cleaned, _ = clean_dataframe(pd.read_csv(StringIO(csv)), "water_quality")
        records = dataframe_to_records(cleaned, "ds", "water_quality")

        assert records[0]["total_coliform"] == pytest.approx(54000)

    def test_river_style_coliform_header_maps_too(self):
        from io import StringIO

        csv = "timestamp,location,Total Coliform (MPN/100ml)\n2020-07-01,Ganga,1700\n"
        cleaned, _ = clean_dataframe(pd.read_csv(StringIO(csv)), "water_quality")
        records = dataframe_to_records(cleaned, "ds", "water_quality")

        assert records[0]["total_coliform"] == pytest.approx(1700)


class TestAmmoniaStorage:
    def test_nh3_n_becomes_numeric_ammonia(self):
        from io import StringIO

        csv = "Station_Name,Date,nh3_n\nLAKE A,2021-12-06 08:30:00,0.4\n"
        cleaned, _ = clean_dataframe(pd.read_csv(StringIO(csv)), "water_quality")
        records = dataframe_to_records(cleaned, "ds", "water_quality")

        assert records[0]["ammonia"] == pytest.approx(0.4)


REAL_FILE = Path("/home/vergil/Downloads/waterKarna.csv")


@pytest.mark.skipif(not REAL_FILE.exists(), reason="local CPCB file not present on this machine")
class TestRealKarnatakaFile:
    """Anchors cross-checked against the user's own parser output."""

    def test_anchor_values(self):
        cleaned, report = clean_dataframe(pd.read_csv(REAL_FILE), "water_quality")

        assert report["rows_read"] == 3434
        assert report["rows_kept"] == 3388
        assert report["duplicates_removed"] == 46
        assert cleaned["location"].nunique() == 102
        assert report["out_of_range_values_set_to_nan"]["ph"] == 1
        assert cleaned["timestamp"].min().startswith("2018-01-04")
        assert cleaned["timestamp"].max().startswith("2021-12-28")

        hebbal = cleaned[cleaned.location == "HEBBAL LAKE"]
        assert len(hebbal) == 89
        assert hebbal["ph"].mean() == pytest.approx(7.4, abs=0.05)
        assert hebbal["do"].mean() == pytest.approx(4.79, abs=0.05)
        assert hebbal["conductivity"].mean() == pytest.approx(1078, abs=5)
        assert (hebbal["do"] < 4).mean() == pytest.approx(0.21, abs=0.02)

        allasandra = cleaned[cleaned.location == "ALLASANDRA TANK"].sort_values("timestamp")
        assert len(allasandra) == 45
        assert allasandra.iloc[-1]["total_coliform"] == pytest.approx(54000)
        assert cleaned["total_coliform"].max() <= 100_000_000  # plausibility cap blanks implausible values

        basavanapura = cleaned[cleaned.location == "BASAVANAPURA LAKE"].sort_values("timestamp")
        assert len(basavanapura) == 16
        assert basavanapura.iloc[-1]["total_coliform"] == pytest.approx(160000)
        assert basavanapura.iloc[-1]["ammonia"] == pytest.approx(0.4)

        ibbalur = cleaned[
            (cleaned.location == "IBBALUR LAKE")
            & (cleaned["timestamp"].str.startswith("2020-12-30"))
        ]
        assert len(ibbalur) == 1
        assert ibbalur.iloc[0]["nitrates"] == pytest.approx(1.3 * 4.4266, abs=0.01)  # as NO3
        assert "converted nitrate-N" in report["unit_conversions"]["nitrates"]

    def test_missing_marker_ledger_and_fluoride_alias(self):
        cleaned, report = clean_dataframe(pd.read_csv(REAL_FILE), "water_quality")

        missing = report["missing_markers_found"]
        assert len(missing) == 12
        assert sum(missing.values()) == 20289
        assert missing["fluorides"] == 2522

        assert len(report["columns_dropped"]) == 77
        assert len(report["columns_renamed"]) == 11
        assert sum(len(v) for v in report["synonym_columns_merged"].values()) == 10

        assert cleaned["fluorides"].notna().sum() == 901
        assert cleaned["fluorides"].max() == pytest.approx(1.2)
        assert cleaned["fluorides"].isna().sum() == 3388 - 901
