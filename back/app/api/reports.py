"""Authenticated report exports: preview, direct download and job API."""
import asyncio
import tempfile
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Literal, Optional, Union
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field, field_validator

from app.api.auth import get_current_user_dep, get_database
from app.reports.build import (
    ReportScopeError,
    build_report_data,
    preview_report,
    resolve_datasets,
    user_id,
)
from app.reports.csv_zip import build_csv_zip, stream_csv_zip
from app.reports.excel import build_workbook
from app.reports.pdf import build_pdf
from app.services.auth import write_audit
from app.services.quotas import quota_for
from app.services.report_units import TYPE_ORDER

router = APIRouter(prefix="/api/reports", tags=["reports"])

FORMATS = {
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    "pdf": ("application/pdf", "pdf"),
    "csv": ("application/zip", "csv.zip"),
}
JOB_THRESHOLD = 50_000
JOB_TTL = timedelta(hours=2)
RATE_LIMIT = 10
RATE_WINDOW_SECONDS = 3600

JOBS: dict = {}
JOB_DIR = Path(tempfile.gettempdir()) / "envplatform_reports"
_RATE: dict = defaultdict(deque)


class ReportFilters(BaseModel):
    dataset_ids: Union[List[str], Literal["all"]] = "all"
    data_types: List[str] = Field(default_factory=list)
    date_from: Optional[datetime] = Field(default=None, alias="from")
    date_to: Optional[datetime] = Field(default=None, alias="to")

    model_config = {"populate_by_name": True}

    @field_validator("data_types")
    @classmethod
    def _known_types(cls, values):
        unknown = [value for value in values if value not in TYPE_ORDER]
        if unknown:
            raise ValueError(f"Unknown data type(s): {', '.join(unknown)}")
        return values


class ExportRequest(ReportFilters):
    format: Literal["xlsx", "pdf", "csv"] = "xlsx"


def _ids(filters: ReportFilters):
    if filters.dataset_ids == "all":
        return None
    return list(filters.dataset_ids)


def _filename(fmt: str) -> str:
    _, extension = FORMATS[fmt]
    stamp = datetime.utcnow().strftime("%Y-%m-%d_%H%M")
    return f"envplatform_report_{stamp}.{extension}"


def _headers(fmt: str) -> dict:
    return {
        "Content-Disposition": f'attachment; filename="{_filename(fmt)}"',
        "X-Report-Format": fmt,
    }


def _rate_limit(user: dict):
    now = time.monotonic()
    queue = _RATE[user_id(user)]
    while queue and now - queue[0] > RATE_WINDOW_SECONDS:
        queue.popleft()
    limit = quota_for(user).exports_per_hour if not isinstance(user, dict) else RATE_LIMIT
    if len(queue) >= limit:
        retry = int(RATE_WINDOW_SECONDS - (now - queue[0]))
        raise HTTPException(
            status_code=429,
            detail="Export limit reached. Try again later.",
            headers={"Retry-After": str(max(retry, 1))},
        )
    queue.append(now)


def _cleanup_jobs():
    now = datetime.utcnow()
    for job_id, job in list(JOBS.items()):
        if job.get("expires_at") and job["expires_at"] < now:
            path = job.get("path")
            if path:
                try:
                    Path(path).unlink(missing_ok=True)
                except OSError:
                    pass
            JOBS.pop(job_id, None)


def _job_public(job_id: str, job: dict) -> dict:
    def iso(value):
        return value.isoformat() if isinstance(value, datetime) else value

    return {
        "job_id": job_id,
        "status": job["status"],
        "format": job["format"],
        "filename": job.get("filename"),
        "created_at": iso(job.get("created_at")),
        "expires_at": iso(job.get("expires_at")),
        "error": job.get("error"),
        "download_url": f"/api/reports/jobs/{job_id}/download" if job["status"] == "completed" else None,
    }


async def _render(fmt: str, report: dict, database: AsyncIOMotorDatabase) -> bytes:
    if fmt == "xlsx":
        return await asyncio.to_thread(build_workbook, report)
    if fmt == "pdf":
        return await asyncio.to_thread(build_pdf, report)
    return await build_csv_zip(database, report)


async def _run_job(job_id: str, filters: dict, database: AsyncIOMotorDatabase):
    job = JOBS.get(job_id)
    if not job:
        return
    job["status"] = "running"
    try:
        JOB_DIR.mkdir(parents=True, exist_ok=True)
        report = await build_report_data(
            database,
            job["user"],
            dataset_ids=filters["dataset_ids"],
            data_types=filters["data_types"],
            start_date=filters["start_date"],
            end_date=filters["end_date"],
        )
        job["filename"] = _filename(job["format"])
        path = JOB_DIR / f"{job_id}_{job['filename']}"
        fmt = job["format"]
        if fmt == "csv":
            with open(path, "wb") as handle:
                async for chunk in stream_csv_zip(database, report):
                    handle.write(chunk)
        else:
            content = await _render(fmt, report, database)
            path.write_bytes(content)
        job["path"] = str(path)
        job["status"] = "completed"
        job["size_bytes"] = path.stat().st_size
    except ReportScopeError as exc:
        job["status"] = "failed"
        job["error"] = str(exc)
    except Exception as exc:  # noqa: BLE001 - surfaced through the job status
        job["status"] = "failed"
        job["error"] = f"Report generation failed: {exc}"


@router.post("/preview")
async def preview_reports(
    filters: ReportFilters,
    database: AsyncIOMotorDatabase = Depends(get_database),
    user=Depends(get_current_user_dep),
):
    try:
        return await preview_report(
            database,
            user,
            dataset_ids=_ids(filters),
            data_types=filters.data_types or None,
            start_date=filters.date_from,
            end_date=filters.date_to,
        )
    except ReportScopeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/export")
async def export_report(
    request: ExportRequest,
    background_tasks: BackgroundTasks,
    database: AsyncIOMotorDatabase = Depends(get_database),
    user=Depends(get_current_user_dep),
):
    _cleanup_jobs()
    _rate_limit(user)
    ids = _ids(request)
    if ids == []:
        raise HTTPException(status_code=400, detail="Select at least one dataset.")
    try:
        selected = await resolve_datasets(
            database, user_id(user), ids, request.data_types or None, user=user,
        )
    except ReportScopeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not selected:
        raise HTTPException(status_code=400, detail="No datasets match this selection.")

    estimate = sum(int(doc.get("row_count") or 0) for doc, _ in selected)
    if estimate > JOB_THRESHOLD:
        job_id = uuid4().hex
        JOBS[job_id] = {
            "status": "queued",
            "format": request.format,
            "user": user,
            "user_id": user_id(user),
            "created_at": datetime.utcnow(),
            "expires_at": datetime.utcnow() + JOB_TTL,
        }
        background_tasks.add_task(
            _run_job,
            job_id,
            {
                "dataset_ids": ids,
                "data_types": request.data_types or None,
                "start_date": request.date_from,
                "end_date": request.date_to,
            },
            database,
        )
        return JSONResponse(_job_public(job_id, JOBS[job_id]), status_code=202)

    report = await build_report_data(
        database,
        user,
        dataset_ids=ids,
        data_types=request.data_types or None,
        start_date=request.date_from,
        end_date=request.date_to,
    )
    media_type, _ = FORMATS[request.format]
    headers = _headers(request.format)
    if request.format == "csv":
        return StreamingResponse(
            stream_csv_zip(database, report), media_type=media_type, headers=headers,
        )
    content = await _render(request.format, report, database)
    await write_audit(
        database, "report.exported", actor=user,
        metadata={"format": request.format, "dataset_ids": report["meta"]["dataset_ids"]},
    )
    return Response(content=content, media_type=media_type, headers=headers)


@router.get("/jobs/{job_id}")
async def report_job_status(job_id: str, user=Depends(get_current_user_dep)):
    _cleanup_jobs()
    job = JOBS.get(job_id)
    if not job or job.get("user_id") != user_id(user):
        raise HTTPException(status_code=404, detail="Report job not found.")
    return _job_public(job_id, job)


@router.get("/jobs/{job_id}/download")
async def download_report_job(job_id: str, user=Depends(get_current_user_dep)):
    _cleanup_jobs()
    job = JOBS.get(job_id)
    if not job or job.get("user_id") != user_id(user):
        raise HTTPException(status_code=404, detail="Report job not found.")
    if job["status"] != "completed" or not job.get("path"):
        raise HTTPException(status_code=409, detail="Report is not ready yet.")
    path = Path(job["path"])
    if not path.exists():
        JOBS.pop(job_id, None)
        raise HTTPException(status_code=410, detail="Report file expired; export it again.")
    media_type, _ = FORMATS[job["format"]]
    return FileResponse(path, media_type=media_type, filename=job["filename"])
