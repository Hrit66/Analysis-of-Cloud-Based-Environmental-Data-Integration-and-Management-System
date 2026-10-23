"""Processing job registry and API contracts."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import job_progress
from app.services.job_progress import (
    JobCancelled,
    bind_job,
    cancel_job,
    check_cancelled,
    clear_jobs,
    complete_job,
    create_job,
    forecast_readiness,
    get_job,
    report_stage,
    reset_job,
    update_job,
)


@pytest.fixture(autouse=True)
def clean_job_registry():
    clear_jobs()
    yield
    clear_jobs()


def test_percent_is_monotonic_and_completion_reaches_one_hundred():
    job = create_job("dataset-1", dataset_type="air_quality")
    job_id = job["job_id"]

    update_job(job_id, stage_key="saving", percent=75)
    update_job(job_id, stage_key="saving", percent=40)
    assert get_job(job_id)["percent"] == 75

    complete_job(job_id, {"dataset_id": "dataset-1", "rows_kept": 10})
    finished = get_job(job_id)
    assert finished["status"] == "completed"
    assert finished["stage_key"] == "done"
    assert finished["percent"] == 100
    assert finished["result"]["rows_kept"] == 10


def test_cancelled_job_cannot_be_completed_and_checkpoints_raise():
    job = create_job("dataset-2", dataset_type="water_quality")
    job_id = job["job_id"]
    token = bind_job(job_id)
    try:
        cancel_job(job_id)
        with pytest.raises(JobCancelled):
            check_cancelled()
        with pytest.raises(JobCancelled):
            report_stage("saving")
        complete_job(job_id, {"dataset_id": "dataset-2"})
    finally:
        reset_job(token)

    cancelled = get_job(job_id)
    assert cancelled["status"] == "cancelled"
    assert cancelled["percent"] < 100


def test_forecast_readiness_summarizes_skip_reasons():
    meta = {
        "forecasts_created": 0,
        "skip_reasons": [{
            "reason": "Insufficient data for Bengaluru: only 12 daily points (minimum 30)",
        }],
    }
    assert forecast_readiness("air_quality", meta) == (
        "Daily forecast not available: 12 observed daily points, needs 30"
    )


def test_job_status_and_cancel_endpoints():
    job = create_job("dataset-3", dataset_type="air_quality")
    job_id = job["job_id"]
    client = TestClient(app)

    response = client.get(f"/api/datasets/jobs/{job_id}")
    assert response.status_code == 200
    assert response.json()["dataset_id"] == "dataset-3"

    response = client.post(f"/api/datasets/jobs/{job_id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"

    assert client.get("/api/datasets/jobs/unknown").status_code == 404
