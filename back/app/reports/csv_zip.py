"""CSV/ZIP renderer: one CSV per dataset plus a manifest.

Raw record rows are read from Mongo in a cursor and written through an
unseekable ZIP sink, so a large export can be streamed without holding the
whole archive in memory. Values keep their native form (ISO timestamps,
numbers, empty missing values) and headers carry units.
"""
import csv
import io
import json
import re
import zipfile
from datetime import date, datetime
from typing import AsyncIterator, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.reports.build import CSV_COLUMNS, CSV_LABELS
from app.services.dashboard_queries import collection_for, inclusive_end
from app.services.report_units import (
    PARAMETER_LABELS,
    PARAMETER_UNITS,
    TYPE_LABELS,
    header_with_unit,
)

BATCH = 500
INJECTION_PREFIX = ("=", "+", "-", "@")
SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


class _ZipSink:
    """Write-only sink without seek/tell so zipfile streams with descriptors."""

    def __init__(self):
        self.chunks: List[bytes] = []

    def write(self, data: bytes) -> int:
        self.chunks.append(bytes(data))
        return len(data)

    def flush(self):
        return None

    def tell(self):
        raise OSError("unseekable")

    def drain(self) -> bytes:
        data = b"".join(self.chunks)
        self.chunks.clear()
        return data


def _safe_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value != value:
        return ""
    if isinstance(value, (dict, list, tuple)):
        value = json.dumps(value, ensure_ascii=False, default=str)
    elif not isinstance(value, str):
        value = str(value)
    value = value.strip()
    if value.lower() in {"nan", "none", "nat", "<na>"}:
        return ""
    if value.startswith(INJECTION_PREFIX):
        value = "'" + value
    return value


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value != value:
            return ""
        if isinstance(value, float):
            return repr(round(value, 6))
        return str(value)
    return _safe_text(value)


def _slug(value: str, used: set) -> str:
    base = SLUG_RE.sub("_", (value or "dataset")).strip("._") or "dataset"
    if base.lower().endswith(".csv"):
        base = base[:-4]
    candidate = f"{base}.csv"
    counter = 2
    while candidate.lower() in used:
        candidate = f"{base}_{counter}.csv"
        counter += 1
    used.add(candidate.lower())
    return candidate


def _dataset_columns(dataset: dict, capabilities: List[str]) -> List[str]:
    outer = ["timestamp", "location"]
    seen = set(outer)
    columns = list(outer)
    for capability in capabilities:
        for column in CSV_COLUMNS.get(capability, []):
            if column not in seen:
                columns.append(column)
                seen.add(column)
    return columns


def _header(column: str) -> str:
    label = CSV_LABELS.get(column) or PARAMETER_LABELS.get(column) or column.replace("_", " ").title()
    unit = "" if column in {"timestamp", "location", "wqi_category", "aqi_category",
                            "dominant_pollutant", "extended_wqi_category",
                            "extended_param_count"} else PARAMETER_UNITS.get(column, "")
    if unit.lower() in {"index", "ph"}:
        unit = ""
    return header_with_unit(label, unit)


def _manifest_row(
    dataset: dict, capabilities: List[str], columns: List[str],
    exported_rows: int, first: Optional[datetime], last: Optional[datetime],
) -> List[str]:
    units = {_header(column): _cell(PARAMETER_UNITS.get(column, "")) for column in columns}
    return [
        dataset["id"],
        _cell(dataset.get("name")),
        ", ".join(TYPE_LABELS.get(cap, cap) for cap in capabilities),
        _cell(dataset.get("filename")),
        _cell(dataset.get("created_at")),
        str(exported_rows),
        str(dataset.get("row_count") or ""),
        _cell(first),
        _cell(last),
        ", ".join(dataset.get("tags") or []),
        json.dumps(units, ensure_ascii=False),
    ]


async def stream_csv_zip(database: AsyncIOMotorDatabase, report: dict) -> AsyncIterator[bytes]:
    """Yield the ZIP archive in chunks while the data cursors stream."""
    sink = _ZipSink()
    archive = zipfile.ZipFile(sink, "w", zipfile.ZIP_DEFLATED, allowZip64=True)
    used = set()
    manifest_rows: List[List[str]] = []
    manifest_header = [
        "dataset_id", "dataset", "data_types", "source_file", "uploaded",
        "rows_exported", "rows_stored", "first_exported", "last_exported",
        "tags", "units",
    ]

    # Metadata carries the public dataset dicts in the same order as the build.
    public_by_id = {item["id"]: item for item in report["meta"].get("datasets") or []}
    capabilities_by_id = {
        item["id"]: item.get("capabilities") or [] for item in report["meta"].get("datasets") or []
    }

    start = report["meta"].get("start_date")
    end = report["meta"].get("end_date")

    for dataset_id, capabilities in capabilities_by_id.items():
        dataset = public_by_id[dataset_id]
        columns = _dataset_columns(dataset, capabilities)
        capabilities = [cap for cap in capabilities if cap in CSV_COLUMNS]
        if not capabilities:
            continue
        collection = collection_for(database, capabilities[0])
        query: Dict = {"dataset_id": dataset_id}
        if start or end:
            query["timestamp"] = {}
            if start:
                query["timestamp"]["$gte"] = start
            if end:
                query["timestamp"]["$lte"] = inclusive_end(end)

        entry = _slug(dataset.get("name") or dataset.get("filename") or dataset_id, used)
        exported = 0
        first_seen = last_seen = None
        with archive.open(f"data/{entry}", "w") as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="", write_through=True)
            writer = csv.writer(text)
            writer.writerow([_header(column) for column in columns])
            cursor = collection.find(query).sort("timestamp", 1)
            async for doc in cursor:
                row = []
                for column in columns:
                    value = doc.get(column)
                    if column == "location" and not value:
                        value = doc.get("city")
                    row.append(_cell(value))
                writer.writerow(row)
                exported += 1
                timestamp = doc.get("timestamp")
                if isinstance(timestamp, datetime):
                    first_seen = first_seen or timestamp
                    last_seen = timestamp
                if exported % BATCH == 0:
                    text.flush()
                    chunk = sink.drain()
                    if chunk:
                        yield chunk
            text.flush()
            text.detach()
        chunk = sink.drain()
        if chunk:
            yield chunk

        manifest_rows.append(_manifest_row(
            dataset, capabilities, columns, exported, first_seen, last_seen,
        ))

    with archive.open("manifest.csv", "w") as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="", write_through=True)
        writer = csv.writer(text)
        writer.writerow(manifest_header)
        writer.writerows(manifest_rows)
        text.flush()
        text.detach()
    archive.close()
    final = sink.drain()
    if final:
        yield final


async def build_csv_zip(database: AsyncIOMotorDatabase, report: dict) -> bytes:
    chunks = []
    async for chunk in stream_csv_zip(database, report):
        chunks.append(chunk)
    return b"".join(chunks)
