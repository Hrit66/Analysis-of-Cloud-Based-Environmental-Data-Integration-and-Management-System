"""Ephemeral progress registry for upload/processing jobs.

Progress is intentionally kept in memory: it describes one API worker's live
work and is only needed while the Upload page polls. The dataset document
remains the durable source of truth.
"""
from __future__ import annotations

import copy
import re
import time
import uuid
from contextvars import ContextVar
from datetime import datetime
from typing import Any, Dict, Optional

MAX_JOBS = 500
JOB_TTL_SECONDS = 24 * 60 * 60

TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
ACTIVE_STATUSES = {"queued", "processing"}

STANDARD_STAGES = (
    "reading_file",
    "detecting_type",
    "removing_duplicate_headers",
    "converting_missing_values",
    "checking_ranges",
    "removing_duplicate_station_dates",
    "normalizing_timestamps",
    "calculating_index",
    "saving",
    "checking_forecast",
    "done",
)
IMD_STAGES = (
    "reading_file",
    "merging_files",
    "detecting_type",
    "removing_duplicate_headers",
    "converting_missing_values",
    "checking_ranges",
    "removing_duplicate_station_dates",
    "normalizing_timestamps",
    "calculating_index",
    "saving",
    "checking_forecast",
    "done",
)
STAGE_LABELS = {
    "reading_file": "Reading file",
    "merging_files": "Merging files",
    "detecting_type": "Detecting type",
    "removing_duplicate_headers": "Removing duplicate headers and empty columns",
    "converting_missing_values": "Converting missing-value markers",
    "checking_ranges": "Checking plausible ranges",
    "removing_duplicate_station_dates": "Removing duplicate station-dates",
    "normalizing_timestamps": "Normalizing timestamps",
    "calculating_index": "Calculating AQI/WQI",
    "saving": "Saving",
    "checking_forecast": "Checking forecast readiness",
    "done": "Done",
}
STAGE_PERCENTS = {
    "reading_file": 10,
    "merging_files": 16,
    "detecting_type": 20,
    "removing_duplicate_headers": 26,
    "converting_missing_values": 32,
    "checking_ranges": 38,
    "removing_duplicate_station_dates": 44,
    "normalizing_timestamps": 50,
    "calculating_index": 56,
    "saving": 60,
    "checking_forecast": 86,
    "done": 100,
}

_jobs: Dict[str, Dict[str, Any]] = {}
_job_context: ContextVar[Optional[str]] = ContextVar("progress_job_id", default=None)


class JobCancelled(Exception):
    """Raised at a safe checkpoint after the owner cancels a running job."""


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _prune_jobs() -> None:
    now = time.time()
    stale = [
        job_id for job_id, job in _jobs.items()
        if job.get("status") in TERMINAL_STATUSES
        and now - float(job.get("_created_ts") or now) > JOB_TTL_SECONDS
    ]
    for job_id in stale:
        _jobs.pop(job_id, None)
    while len(_jobs) > MAX_JOBS:
        oldest = min(_jobs, key=lambda key: _jobs[key].get("_created_ts", 0))
        _jobs.pop(oldest, None)


def _stage_sequence(mode: str) -> tuple[str, ...]:
    return IMD_STAGES if mode == "imd" else STANDARD_STAGES


def _public(job: Dict[str, Any]) -> Dict[str, Any]:
    payload = {
        key: copy.deepcopy(value)
        for key, value in job.items()
        if not key.startswith("_")
    }
    started = job.get("started_at")
    if started:
        try:
            started_dt = datetime.fromisoformat(str(started).rstrip("Z"))
            payload["elapsed_seconds"] = max(
                0, int((datetime.utcnow() - started_dt).total_seconds())
            )
        except (TypeError, ValueError):
            payload["elapsed_seconds"] = 0
    return payload


def create_job(
    dataset_id: str,
    dataset_type: Optional[str] = None,
    owner_id: Optional[str] = None,
    mode: str = "standard",
    file_count: int = 1,
    source_name: Optional[str] = None,
) -> Dict[str, Any]:
    _prune_jobs()
    job_id = uuid.uuid4().hex
    stages = _stage_sequence(mode)
    first_stage = stages[0]
    job = {
        "job_id": job_id,
        "dataset_id": dataset_id,
        "dataset_type": dataset_type,
        "owner_id": owner_id,
        "mode": mode,
        "source_name": source_name,
        "status": "processing",
        "stage_key": first_stage,
        "stage_label": STAGE_LABELS[first_stage],
        "percent": STAGE_PERCENTS[first_stage],
        "counts": {
            "rows_read": 0,
            "rows_kept": 0,
            "rows_dropped": 0,
            "files_total": int(file_count or 0),
            "files_done": 0,
        },
        "error_message": None,
        "result": None,
        "created_at": _now(),
        "started_at": _now(),
        "updated_at": _now(),
        "_created_ts": time.time(),
    }
    _jobs[job_id] = job
    return _public(job)


def get_job(job_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not job_id:
        return None
    job = _jobs.get(job_id)
    if not job:
        return None
    return _public(job)


def update_job(
    job_id: Optional[str],
    *,
    stage_key: Optional[str] = None,
    stage_label: Optional[str] = None,
    percent: Optional[int] = None,
    counts: Optional[Dict[str, Any]] = None,
    status: Optional[str] = None,
    error_message: Optional[str] = None,
    result: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    if not job_id:
        return None
    job = _jobs.get(job_id)
    if not job:
        return None

    if job["status"] in TERMINAL_STATUSES and status not in (None, job["status"]):
        return _public(job)

    if counts:
        merged = dict(job.get("counts") or {})
        for key, value in counts.items():
            if value is not None:
                merged[key] = value
        read = merged.get("rows_read")
        kept = merged.get("rows_kept")
        if read is not None and kept is not None:
            merged["rows_dropped"] = max(0, int(read) - int(kept))
        job["counts"] = merged

    if stage_key:
        job["stage_key"] = stage_key
        job["stage_label"] = stage_label or STAGE_LABELS.get(stage_key, stage_key)
    elif stage_label:
        job["stage_label"] = stage_label

    if percent is not None:
        target = max(0, min(100 if status == "completed" else 99, int(percent)))
        job["percent"] = max(int(job.get("percent") or 0), target)

    if status:
        job["status"] = status
        if status == "completed":
            job["percent"] = 100
            job["stage_key"] = "done"
            job["stage_label"] = STAGE_LABELS["done"]
            job["error_message"] = None
        elif status in ("failed", "cancelled"):
            job["error_message"] = error_message or job.get("error_message")
        elif status == "processing":
            job["error_message"] = error_message

    if result is not None:
        job["result"] = copy.deepcopy(result)

    job["updated_at"] = _now()
    return _public(job)


def report_stage(
    stage_key: str,
    *,
    percent: Optional[int] = None,
    label: Optional[str] = None,
    counts: Optional[Dict[str, Any]] = None,
) -> None:
    """Update the job bound to this execution context, if any."""
    job_id = _job_context.get()
    if not job_id:
        return
    job = _jobs.get(job_id)
    if not job:
        return
    if job.get("status") == "cancelled":
        raise JobCancelled("Processing cancelled")
    update_job(
        job_id,
        stage_key=stage_key,
        stage_label=label,
        percent=percent if percent is not None else STAGE_PERCENTS.get(stage_key),
        counts=counts,
    )


def report_counts(counts: Dict[str, Any]) -> None:
    job_id = _job_context.get()
    if not job_id:
        return
    update_job(job_id, counts=counts)


def complete_job(job_id: Optional[str], result: Dict[str, Any]) -> None:
    if not job_id:
        return
    job = _jobs.get(job_id)
    if job and job.get("status") == "cancelled":
        return
    update_job(job_id, status="completed", result=result)


def fail_job(job_id: Optional[str], error_message: str) -> None:
    if not job_id:
        return
    job = _jobs.get(job_id)
    if job and job.get("status") == "cancelled":
        return
    update_job(job_id, status="failed", error_message=str(error_message))


def cancel_job(job_id: str) -> Optional[Dict[str, Any]]:
    job = _jobs.get(job_id)
    if not job:
        return None
    if job.get("status") in TERMINAL_STATUSES:
        return _public(job)
    return update_job(job_id, status="cancelled", error_message="Processing cancelled")


def bind_job(job_id: Optional[str]):
    return _job_context.set(job_id)


def reset_job(token) -> None:
    try:
        _job_context.reset(token)
    except (ValueError, LookupError):
        _job_context.set(None)


def check_cancelled() -> None:
    job_id = _job_context.get()
    if job_id and (_jobs.get(job_id) or {}).get("status") == "cancelled":
        raise JobCancelled("Processing cancelled")


def clear_jobs() -> None:
    """Test helper."""
    _jobs.clear()


def forecast_readiness(dataset_type: Optional[str], meta: Optional[dict]) -> str:
    """Human-readable forecast outcome for the completion panel."""
    meta = meta or {}
    created = int(meta.get("forecasts_created") or 0)
    reasons = meta.get("skip_reasons") or []
    if dataset_type == "water_quality":
        ready_label = "Monthly water outlook ready"
        unavailable_label = "Water outlook not available"
    else:
        ready_label = "Daily forecast ready"
        unavailable_label = "Daily forecast not available"

    if not reasons:
        return ready_label if created else f"{unavailable_label}: not enough history yet"

    reason = str(reasons[0].get("reason") or "").strip()
    reason = re.sub(r"^Insufficient data for .*?: ", "", reason)
    only_match = re.search(
        r"only\s+(\d+)\s+([a-zA-Z ]+?)\s+\(minimum\s+(\d+)\)", reason
    )
    if only_match:
        observed, unit, needed = only_match.groups()
        return f"{unavailable_label}: {observed} observed {unit.strip()}, needs {needed}"
    aqi_match = re.search(
        r"(\d+)\s+daily points.*?at least\s+(\d+)\s+days", reason, re.IGNORECASE
    )
    if aqi_match:
        observed, needed = aqi_match.groups()
        return f"{unavailable_label}: {observed} observed days, needs {needed}"
    return f"{unavailable_label}: {reason or 'not enough history yet'}"
