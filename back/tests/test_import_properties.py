"""Property-based import contracts.

These tests exercise invariants instead of golden values: conservation of row
counts, column accounting, no silent zeros, idempotent unit conversion,
invariance to row/column order and delimiter/encoding, plausibility bounds,
and graceful failure on arbitrary input.
"""
import asyncio
from types import SimpleNamespace
from bson import ObjectId

import numpy as np
import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from app.api import datasets as datasets_api
from app.services import dataset_config
from app.services.pipeline_interface import (
    clean_dataframe,
    parse_file,
)

HYPOTHESIS = settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


def _water_frame(values, timestamps=None):
    count = len(values)
    stamps = timestamps or pd.date_range("2021-01-01", periods=count, freq="D").strftime("%Y-%m-%d")
    return pd.DataFrame({
        "timestamp": list(stamps),
        "station": ["Property Lake"] * count,
        "ph": [7.2] * count,
        "Dissolved Oxygen (mg/L)": values,
        "BOD": [4.0] * count,
    })


def _comparable(df):
    return df.sort_values(["timestamp", "location"]).reset_index(drop=True)


class TestConservation:
    @HYPOTHESIS
    @given(
        values=st.lists(
            st.floats(min_value=-5, max_value=30, allow_nan=False),
            min_size=1,
            max_size=10,
        ),
        choices=st.lists(
            st.sampled_from(["2021-01-01", "2021-01-02", "2021-01-03", "not-a-date", ""]),
            min_size=1,
            max_size=10,
        ),
    )
    def test_rows_read_equals_kept_plus_rejected(self, values, choices):
        count = min(len(values), len(choices))
        timestamps = ["2021-01-01"] + list(choices[1:count])
        df = _water_frame(values[:count], timestamps)
        df.loc[0, "timestamp"] = "2021-01-01"

        cleaned, report = clean_dataframe(df, "water_quality")

        rejected = sum(report["rows_dropped"].values())
        assert report["rows_read"] == len(df)
        assert report["rows_read"] == (
            report["rows_kept"] + rejected + report["duplicates_removed"]
        )
        assert report["rows_kept"] == len(cleaned)

    @HYPOTHESIS
    @given(extra=st.lists(st.integers(min_value=0, max_value=8), min_size=1, max_size=6))
    def test_every_original_column_is_accounted_for(self, extra):
        df = _water_frame([6.0])
        for index in extra:
            df[f"zz_extra_{index}"] = ["ignored"]

        _, report = clean_dataframe(df, "water_quality")

        merged_sources = {
            source
            for sources in report["synonym_columns_merged"].values()
            for source in sources
        }
        accounted = (
            set(report["columns_renamed"])
            | merged_sources
            | set(report["columns_dropped"])
            | {
                column for column in df.columns
                if column in report.get("plausibility_ranges", {})
                or column in ("timestamp", "location")
            }
        )
        assert set(df.columns) <= accounted


class TestNoSilentZeros:
    @HYPOTHESIS
    @given(marker=st.sampled_from(["", "NA", "null", "-", "missing", "n/a", "ND", "BDL"]))
    def test_missing_markers_never_become_zero(self, marker):
        df = pd.DataFrame({
            "timestamp": ["2021-01-01"],
            "station": ["Marker Lake"],
            "do": [marker],
            "BOD": [4.0],
        })
        cleaned, report = clean_dataframe(df, "water_quality")

        assert pd.isna(cleaned.loc[0, "do"])
        assert cleaned.loc[0, "do"] != 0
        assert report["missing_values_count"]["do"] == 1

    def test_source_nan_never_becomes_zero(self):
        df = pd.DataFrame({
            "timestamp": ["2021-01-01"],
            "station": ["NaN Lake"],
            "do": [np.nan],
            "BOD": [4.0],
        })
        cleaned, report = clean_dataframe(df, "water_quality")

        assert pd.isna(cleaned.loc[0, "do"])
        assert report["missing_values_count"]["do"] == 1


class TestIdempotence:
    @HYPOTHESIS
    @given(value=st.floats(min_value=0.0, max_value=40.0, allow_nan=False))
    def test_nitrate_as_n_is_converted_exactly_once(self, value):
        df = pd.DataFrame({
            "timestamp": ["2021-01-01"],
            "station": ["Nitrate Lake"],
            "Nitrate as N": [value],
            "do": [6.0],
            "BOD": [4.0],
        })
        first, first_report = clean_dataframe(df, "water_quality")
        second, second_report = clean_dataframe(first, "water_quality")

        assert first_report["unit_conversions"]["nitrates"]
        assert "nitrates" not in second_report["unit_conversions"]
        if not pd.isna(first.loc[0, "nitrates"]):
            assert second.loc[0, "nitrates"] == pytest.approx(first.loc[0, "nitrates"])
        assert first.loc[0, "nitrates"] == pytest.approx(value * 62.004 / 14.007)


class TestInvariance:
    def _base(self):
        return _water_frame([6.5, 5.8, 6.1, 7.0], [
            "2021-01-01", "2021-02-01", "2021-03-01", "2021-04-01",
        ])

    def test_row_order_does_not_change_cleaned_values(self):
        df = self._base()
        first, _ = clean_dataframe(df, "water_quality")
        shuffled, _ = clean_dataframe(df.sample(frac=1, random_state=7), "water_quality")

        pd.testing.assert_frame_equal(_comparable(first), _comparable(shuffled))

    def test_column_order_does_not_change_cleaned_values(self):
        df = self._base()
        first, _ = clean_dataframe(df, "water_quality")
        reordered, _ = clean_dataframe(df[list(reversed(df.columns))], "water_quality")

        pd.testing.assert_frame_equal(_comparable(first), _comparable(reordered))

    @pytest.mark.parametrize("delimiter", [",", ";", "\t", "|"])
    def test_delimiter_does_not_change_cleaned_values(self, tmp_path, delimiter):
        df = self._base()
        path = tmp_path / f"delimiter_{ord(delimiter)}.csv"
        df.to_csv(path, index=False, sep=delimiter)

        cleaned, _ = clean_dataframe(parse_file(str(path), "water_quality"), "water_quality")
        expected, _ = clean_dataframe(df, "water_quality")

        pd.testing.assert_frame_equal(_comparable(cleaned), _comparable(expected))

    def test_latin1_encoding_and_non_ascii_station_name(self, tmp_path):
        df = self._base()
        df["station"] = ["München Lake"] * len(df)
        path = tmp_path / "latin1.csv"
        df.to_csv(path, index=False, encoding="latin-1")

        cleaned, _ = clean_dataframe(parse_file(str(path), "water_quality"), "water_quality")
        assert set(cleaned["location"]) == {"München Lake"}


class TestBounds:
    @HYPOTHESIS
    @given(values=st.lists(
        st.floats(min_value=-500, max_value=500, allow_nan=False),
        min_size=1,
        max_size=10,
    ))
    def test_out_of_range_values_are_blanked_and_counted(self, values):
        df = _water_frame(values)
        cleaned, report = clean_dataframe(df, "water_quality")

        low, high = dataset_config.RANGES["water_quality"]["do"]
        expected_out = sum(value < low or value > high for value in values)
        assert report["out_of_range_values_set_to_nan"].get("do", 0) == expected_out
        assert cleaned["do"].dropna().between(low, high).all()


class TestNeverCrash:
    @HYPOTHESIS
    @given(rows=st.lists(
        st.tuples(st.text(max_size=20), st.text(max_size=20)),
        min_size=1,
        max_size=5,
    ))
    def test_random_tables_raise_value_error_not_internal_errors(self, rows):
        df = pd.DataFrame(rows, columns=["alpha", "beta"])
        try:
            cleaned, report = clean_dataframe(df, "water_quality")
        except ValueError:
            return
        assert isinstance(cleaned, pd.DataFrame)
        assert report["rows_read"] == len(df)

    @HYPOTHESIS
    @given(payload=st.binary(max_size=200))
    def test_random_bytes_fail_with_value_error(self, payload, tmp_path):
        path = tmp_path / "random.csv"
        path.write_bytes(payload)
        try:
            parsed = parse_file(str(path), "air_quality")
        except ValueError:
            return
        assert isinstance(parsed, pd.DataFrame)


class TestOwnership:
    def test_every_stored_record_carries_the_dataset_owner(self, tmp_path, monkeypatch):
        source = tmp_path / "owned.csv"
        pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=5, freq="D").strftime("%Y-%m-%d"),
            "station": ["Owned"] * 5,
            "PM2.5": [20.0, 21.0, 19.0, 22.0, 20.5],
        }).to_csv(source, index=False)

        class FakeCollection:
            def __init__(self):
                self.records = []

            async def insert_many(self, batch):
                self.records.extend(batch)

            async def insert_one(self, doc):
                doc = dict(doc)
                doc.setdefault("_id", ObjectId())
                self.records.append(doc)
                return SimpleNamespace(inserted_id=doc["_id"])

            async def update_many(self, *args, **kwargs):
                return SimpleNamespace(modified_count=0)

            async def update_one(self, *args, **kwargs):
                return SimpleNamespace(matched_count=1)

            async def delete_many(self, *args, **kwargs):
                return SimpleNamespace(deleted_count=0)

        class FakeDatabase:
            def __init__(self):
                self.datasets = FakeCollection()
                self.air_quality = FakeCollection()
                self.water_quality = FakeCollection()
                self.anomalies = FakeCollection()
                self.forecasts = FakeCollection()
                self.notifications = FakeCollection()

            async def find_one(self, *args, **kwargs):
                return {"user_id": "owner-1"}

        database = FakeDatabase()
        database.datasets.find_one = None  # process_dataset uses the module helper

        async def owner_lookup(_database, _dataset_id):
            return "owner-1"

        monkeypatch.setattr(datasets_api, "_dataset_owner", owner_lookup)
        monkeypatch.setattr(datasets_api.db, "db", database)

        asyncio.run(datasets_api.process_dataset(
            "6ad3cbfee69574480fc16e50", str(source), "air_quality"
        ))

        records = database.air_quality.records
        assert records
        assert all(record["owner_id"] == "owner-1" for record in records)
