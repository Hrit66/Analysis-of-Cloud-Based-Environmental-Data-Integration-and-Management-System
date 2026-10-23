"""Station rank in /wqi/{ds}/summary: pool rules and the rank-with-count contract."""
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from app.api.analytics import get_database
from app.main import app

DATASET_ID = "6ad3cbfee69574480fc16e50"
WATER_DS = {"_id": DATASET_ID, "dataset_type": "water_quality", "capabilities": ["water_quality"]}


def _client(rows):
    fake = AsyncMock()
    fake.datasets.find_one = AsyncMock(return_value=WATER_DS)
    cursor = MagicMock()
    cursor.to_list = AsyncMock(return_value=rows)
    fake.water_quality.aggregate = MagicMock(return_value=cursor)
    app.dependency_overrides[get_database] = lambda: fake
    return TestClient(app), fake


def _row(location, avg, scored_count, count=None):
    return {
        "_id": location,
        "avg_wqi": avg,
        "min_wqi": avg,
        "max_wqi": avg,
        "count": count if count is not None else scored_count,
        "scored_count": scored_count,
    }


def _get(rows, params=""):
    client, fake = _client(rows)
    try:
        response = client.get(f"/api/analytics/wqi/{DATASET_ID}/summary{params}")
    finally:
        app.dependency_overrides.clear()
    return response, fake


class TestStationRank:
    def test_rank_is_worse_than_share_of_ranked_stations(self):
        response, _ = _get([
            _row("A", 80.0, 5),
            _row("B", 100.0, 4),
            _row("C", 120.0, 7),
        ])

        by_loc = {r["location"]: r for r in response.json()}
        assert by_loc["B"]["rank_pct"] == 50
        assert by_loc["B"]["rank_of"] == 3
        assert by_loc["B"]["rank_samples"] == 4
        assert by_loc["A"]["rank_pct"] == 0
        assert by_loc["C"]["rank_pct"] == 100

    def test_rank_is_never_returned_without_the_sample_count(self):
        response, _ = _get([
            _row("A", 80.0, 5),
            _row("B", 100.0, 6),
        ])

        for entry in response.json():
            assert entry["rank_pct"] is not None
            assert entry["rank_of"] == 2
            assert entry["rank_samples"] == entry["scored_count"]
            assert entry["rank_samples"] >= 3

    def test_station_with_fewer_than_three_samples_is_not_ranked(self):
        response, _ = _get([
            _row("A", 80.0, 5),
            _row("B", 100.0, 4),
            _row("C", 1.0, 2),
        ])

        by_loc = {r["location"]: r for r in response.json()}
        # C has the best mean but only 2 samples: excluded from the pool and unranked.
        assert by_loc["C"]["rank_pct"] is None
        assert by_loc["C"]["rank_of"] is None
        assert by_loc["C"]["rank_samples"] is None
        # The pool itself only counts A and B: B is worse than its only peer.
        assert by_loc["A"]["rank_of"] == 2
        assert by_loc["B"]["rank_pct"] == 100

    def test_unscored_samples_do_not_count_towards_the_rank(self):
        response, _ = _get([
            _row("A", 80.0, 3, count=10),
            _row("B", 100.0, 3, count=4),
        ])

        by_loc = {r["location"]: r for r in response.json()}
        assert by_loc["A"]["rank_samples"] == 3
        assert by_loc["B"]["rank_pct"] == 100

    def test_single_station_pool_has_no_rank(self):
        response, _ = _get([_row("A", 80.0, 9)])

        entry = response.json()[0]
        assert entry["rank_pct"] is None
        assert entry["rank_of"] is None
        assert entry["rank_samples"] is None

    def test_ties_are_not_counted_as_better(self):
        response, _ = _get([
            _row("A", 100.0, 5),
            _row("B", 100.0, 5),
        ])

        for entry in response.json():
            assert entry["rank_pct"] == 0


class TestSummaryWindow:
    def test_window_params_reach_the_match_stage(self):
        _response, fake = _get(
            [_row("A", 80.0, 5)],
            params="?start_date=2020-12-28&end_date=2021-12-28",
        )

        pipeline = fake.water_quality.aggregate.call_args.args[0]
        match = pipeline[0]["$match"]
        assert match["dataset_id"] == DATASET_ID
        assert match["timestamp"]["$gte"].year == 2020
        assert match["timestamp"]["$lte"].year == 2021
