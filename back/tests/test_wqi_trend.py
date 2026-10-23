"""Sen slope and Mann-Kendall diagnostics for WQI series."""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from app.api.analytics import get_database
from app.main import app
from app.services.trend_analysis import analyze_trend

DATASET_ID = "6ad3cbfee69574480fc16e50"
STEP_DAYS = 365.25 / 12


def _series(values, start=datetime(2020, 1, 1)):
    return [start + timedelta(days=STEP_DAYS * index) for index in range(len(values))]


class TestAnalyzeTrend:
    def test_increasing_series_has_positive_slope_and_significant_mk(self):
        values = [10.0 + index for index in range(24)]

        result = analyze_trend(_series(values), values)

        assert result["available"] is True
        assert result["n"] == 24
        assert result["sen_slope_per_year"] == 12.0
        assert result["direction"] == "increasing"
        assert result["significant"] is True
        assert result["mann_kendall"]["s"] > 0
        assert result["mann_kendall"]["p_value"] < 0.05
        assert "worsening" in result["interpretation"]

    def test_decreasing_series_is_an_improvement(self):
        values = [40.0 - index for index in range(24)]

        result = analyze_trend(_series(values), values)

        assert result["sen_slope_per_year"] == -12.0
        assert result["direction"] == "decreasing"
        assert result["significant"] is True
        assert "improving" in result["interpretation"]

    def test_flat_series_has_no_trend_and_handles_ties(self):
        values = [20.0] * 12

        result = analyze_trend(_series(values), values)

        assert result["available"] is True
        assert result["sen_slope_per_year"] == 0.0
        assert result["direction"] == "no trend"
        assert result["significant"] is False
        assert result["mann_kendall"]["p_value"] == 1.0
        assert "No statistically significant" in result["interpretation"]

    def test_alternating_series_is_not_significant(self):
        values = [10.0, 20.0] * 6

        result = analyze_trend(_series(values), values)

        assert result["available"] is True
        assert result["significant"] is False
        assert result["direction"] in ("increasing", "decreasing")

    def test_too_few_samples_is_unavailable(self):
        values = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0]

        result = analyze_trend(_series(values), values)

        assert result["available"] is False
        assert result["n"] == 7
        assert result["reason"] == "needs at least 8 scored samples in the window (has 7)"

    def test_missing_values_are_ignored(self):
        values = [10.0, None, 12.0, 13.0, None, 15.0, 16.0, 17.0, 18.0, 19.0]

        result = analyze_trend(_series(values), values)

        assert result["available"] is True
        assert result["n"] == 8
        assert result["reason"] is None


class TestWQITrendEndpoint:
    def _client(self, rows):
        fake = AsyncMock()
        fake.datasets.find_one = AsyncMock(return_value={
            "_id": DATASET_ID,
            "dataset_type": "water_quality",
            "capabilities": ["water_quality"],
        })
        cursor = MagicMock()
        cursor.sort = MagicMock(return_value=cursor)
        cursor.to_list = AsyncMock(return_value=rows)
        fake.water_quality.find = MagicMock(return_value=cursor)
        app.dependency_overrides[get_database] = lambda: fake
        return TestClient(app)

    def test_endpoint_returns_sen_slope_and_mk_significance(self):
        values = [10.0 + index for index in range(24)]
        rows = [
            {"timestamp": timestamp, "wqi": value}
            for timestamp, value in zip(_series(values), values)
        ]
        client = self._client(rows)
        try:
            response = client.get(
                f"/api/analytics/wqi/{DATASET_ID}/trend",
                params={"location": "Lake A"},
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        payload = response.json()
        assert payload["dataset_id"] == DATASET_ID
        assert payload["location"] == "Lake A"
        assert payload["parameter"] == "wqi"
        assert payload["available"] is True
        assert payload["sen_slope_per_year"] == 12.0
        assert payload["significant"] is True
        assert payload["mann_kendall"]["p_value"] < 0.05
