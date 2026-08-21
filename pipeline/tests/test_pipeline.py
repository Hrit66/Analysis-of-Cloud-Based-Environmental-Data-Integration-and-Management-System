"""Unit tests for pipeline readers, validators, cleaners, normalizers, and main pure pipeline functions."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np
import pandas as pd

from pipeline import clean_dataframe, parse_file, process_file
from pipeline.cleaners import (
    STANDARDIZED_AIR_QUALITY_COLUMNS,
    clean_data,
    normalize_air_quality,
)
from pipeline.imputation import impute_knn, impute_rf
from pipeline.ingestion import fetch_api_data
from pipeline.readers import read_csv, read_excel, read_json
from pipeline.validators import validate_file, validate_schema
from pipeline.workers import process_batch_task, process_file_task


class TestPipeline(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_csv_reader_and_parse_file(self):
        csv_file = self.temp_path / "sample.csv"
        csv_file.write_text(
            "timestamp,location,pm25,pm10,no2,so2,co,o3\n"
            "2026-08-21 10:00:00,Delhi Station 1,45.2,85.0,21.5,12.0,1.2,30.5\n"
            "2026-08-21 11:00:00,Delhi Station 1,48.0,90.2,24.1,13.2,1.4,32.0\n"
        )
        df_direct = read_csv(csv_file)
        self.assertEqual(len(df_direct), 2)

        df_parsed = parse_file(csv_file)
        self.assertEqual(len(df_parsed), 2)
        self.assertIn("pm25", df_parsed.columns)

    def test_json_reader_and_parse_file(self):
        json_file = self.temp_path / "sample.json"
        data = [
            {"time": "2026-08-21T08:00:00Z", "station": "Station A", "pm25": 30.1, "pm10": 60.0},
            {"time": "2026-08-21T09:00:00Z", "station": "Station A", "pm25": 32.5, "pm10": 62.1},
        ]
        json_file.write_text(json.dumps(data))
        df_parsed = parse_file(json_file)
        self.assertEqual(len(df_parsed), 2)
        self.assertIn("station", df_parsed.columns)

    def test_excel_reader_and_parse_file(self):
        excel_file = self.temp_path / "sample.xlsx"
        sample_df = pd.DataFrame({
            "timestamp": ["2026-08-21 12:00:00"],
            "location": ["Central Park"],
            "pm25": [18.5],
            "pm10": [35.0],
            "no2": [10.2],
            "so2": [5.1],
            "co": [0.6],
            "o3": [22.4],
        })
        sample_df.to_excel(excel_file, index=False)
        df_parsed = parse_file(excel_file)
        self.assertEqual(len(df_parsed), 1)

    def test_file_validator(self):
        valid_csv = self.temp_path / "valid.csv"
        valid_csv.write_text("a,b\n1,2")
        self.assertTrue(validate_file(valid_csv))

        # Missing file
        with self.assertRaises(FileNotFoundError):
            validate_file(self.temp_path / "non_existent.csv")

        # Unsupported extension
        invalid_txt = self.temp_path / "data.txt"
        invalid_txt.write_text("hello")
        with self.assertRaises(ValueError):
            validate_file(invalid_txt)

    def test_schema_validator(self):
        df = pd.DataFrame({"timestamp": ["2026-08-21"], "location": ["Site A"]})
        self.assertTrue(validate_schema(df, ["timestamp", "location"]))

        with self.assertRaises(ValueError):
            validate_schema(df, ["timestamp", "location", "pm25"])

    def test_clean_data(self):
        df = pd.DataFrame({
            " col1 ": [1, 2, 2, None],
            "col2": ["a", "b", "b", None],
        })
        cleaned = clean_data(df)
        self.assertListEqual(list(cleaned.columns), ["col1", "col2"])
        self.assertEqual(len(cleaned), 2)

    def test_clean_dataframe_air_quality_standardization(self):
        raw_df = pd.DataFrame({
            "Date Time": ["2026-08-21 19:30:00+05:30", "2026-08-21 20:30:00+05:30", "2026-08-21 20:30:00+05:30"],
            "Station_Name": [" Anand Vihar ", " Anand Vihar ", " Anand Vihar "],
            "PM2.5 (ug/m3)": ["120.5", "-5.0", "-5.0"],
            "PM10 (ug/m3)": [210.0, 195.0, 195.0],
            "NO2 (ug/m3)": [45.1, 40.2, 40.2],
            "SO2 (ug/m3)": [15.2, 14.8, 14.8],
            "CO (mg/m3)": [2.1, 1.9, 1.9],
            "O3 (ug/m3)": [35.0, 38.2, 38.2],
        })

        cleaned = clean_dataframe(raw_df, dataset_type="air_quality")

        self.assertListEqual(list(cleaned.columns), STANDARDIZED_AIR_QUALITY_COLUMNS)
        self.assertEqual(len(cleaned), 2)
        self.assertEqual(cleaned["timestamp"].iloc[0], "2026-08-21T14:00:00Z")
        self.assertEqual(cleaned["timestamp"].iloc[1], "2026-08-21T15:00:00Z")
        self.assertTrue(np.isnan(cleaned["pm25"].iloc[1]))
        self.assertEqual(cleaned["pm25"].iloc[0], 120.5)

        for col in ["pm25", "pm10", "no2", "so2", "co", "o3"]:
            self.assertEqual(cleaned[col].dtype, float)

        self.assertNotIn("dataset_id", cleaned.columns)
        self.assertNotIn("dataset_type", cleaned.columns)

    def test_process_file_end_to_end(self):
        csv_file = self.temp_path / "full_pipeline.csv"
        csv_file.write_text(
            "time,station,pm2.5,pm10,no2,so2,co,o3\n"
            "2026-08-21 12:00:00,Site Alpha,25.4,50.1,15.2,8.0,0.9,40.1\n"
        )
        res = process_file(csv_file, dataset_type="air_quality")
        self.assertListEqual(list(res.columns), STANDARDIZED_AIR_QUALITY_COLUMNS)
        self.assertEqual(res["location"].iloc[0], "Site Alpha")
        self.assertEqual(res["pm25"].iloc[0], 25.4)

    def test_worker_tasks(self):
        csv_file = self.temp_path / "task_test.csv"
        csv_file.write_text(
            "timestamp,location,pm25,pm10,no2,so2,co,o3\n"
            "2026-08-21 10:00:00,Delhi,30.0,60.0,20.0,10.0,1.0,25.0\n"
        )
        res = process_file_task(csv_file)
        self.assertEqual(len(res), 1)

        batch_res = process_batch_task([csv_file])
        self.assertIn(str(csv_file), batch_res)
        self.assertEqual(len(batch_res[str(csv_file)]), 1)

    def test_imputers(self):
        df_missing = pd.DataFrame({
            "a": [1.0, 2.0, np.nan, 4.0, 5.0],
            "b": [2.0, 4.0, 6.0, 8.0, 10.0],
        })
        knn_res = impute_knn(df_missing)
        self.assertEqual(knn_res["a"].isna().sum(), 0)

        rf_res = impute_rf(df_missing)
        self.assertEqual(rf_res["a"].isna().sum(), 0)

    @patch("urllib.request.urlopen")
    def test_fetch_api_data(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps([
            {"timestamp": "2026-08-21T00:00:00Z", "pm25": 12.0}
        ]).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        df = fetch_api_data("https://api.example.com/airquality")
        self.assertEqual(len(df), 1)
        self.assertIn("pm25", df.columns)


if __name__ == "__main__":
    unittest.main()
