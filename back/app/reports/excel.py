"""Excel renderer for the report payload.

Only formatting happens here: every value comes from ``build_report_data``.
The workbook is written with ``constant_memory`` so a large selection never
holds the full sheet in RAM, and every data sheet is capped well below the
Excel row limit (the full record window is available in the CSV/ZIP export).
"""
import io
import re
from datetime import date, datetime
from typing import Iterable, List, Optional

import xlsxwriter

from app.services.report_units import TYPE_LABELS

MAX_ROWS = 5000
INJECTION_PREFIX = ("=", "+", "-", "@")
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _text(value) -> str:
    """Sanitise a cell string: no formula injection, no 'nan', no controls."""
    if value is None:
        return ""
    if isinstance(value, float):
        return "" if value != value else str(value)
    if not isinstance(value, str):
        value = str(value)
    value = CONTROL_CHARS.sub("", value).strip()
    if value.lower() in {"nan", "none", "nat", "<na>"}:
        return ""
    if value.startswith(INJECTION_PREFIX):
        value = "'" + value
    return value


def _date(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    return None


def _filters_text(meta: dict) -> str:
    pieces = []
    if meta.get("start_date") or meta.get("end_date"):
        start = meta["start_date"].strftime("%d %b %Y") if meta.get("start_date") else "first record"
        end = meta["end_date"].strftime("%d %b %Y") if meta.get("end_date") else "last record"
        pieces.append(f"{start} – {end}")
    else:
        pieces.append("Full history")
    types = ", ".join(TYPE_LABELS.get(t, t) for t in meta.get("data_types") or [])
    if types:
        pieces.append(types)
    return " | ".join(pieces)


class _Sheet:
    def __init__(self, workbook, name: str, widths: List[int], headers: List[str]):
        self.worksheet = workbook.add_worksheet(name[:31])
        self.headers = headers
        for index, width in enumerate(widths):
            self.worksheet.set_column(index, index, width)
        self.row = 0

    def header(self):
        formats = self.workbook_formats
        for col, label in enumerate(self.headers):
            self.worksheet.write(self.row, col, label, formats["header"])
        self.worksheet.freeze_panes(self.row + 1, 0)
        self.header_row = self.row
        self.row += 1

    def write(self, values: Iterable):
        formats = self.workbook_formats
        for col, value in enumerate(values):
            if value is None or value == "":
                self.worksheet.write_blank(self.row, col, None)
            elif isinstance(value, bool):
                self.worksheet.write_string(self.row, col, "yes" if value else "no")
            elif isinstance(value, (int, float)):
                fmt = formats["float"] if isinstance(value, float) else formats["int"]
                self.worksheet.write_number(self.row, col, value, fmt)
            elif isinstance(value, datetime):
                self.worksheet.write_datetime(self.row, col, value, formats["date"])
            else:
                self.worksheet.write_string(self.row, col, _text(value))
        self.row += 1

    def note(self, text: str):
        self.worksheet.write_string(self.row, 0, _text(text), self.workbook_formats["note"])
        self.row += 1

    def finish(self, last_data_row: Optional[int] = None):
        last = self.row - 1 if last_data_row is None else last_data_row
        if last >= self.header_row:
            self.worksheet.autofilter(self.header_row, 0, last, len(self.headers) - 1)


def _cap(rows: List[dict]) -> List[dict]:
    return rows[:MAX_ROWS]


def _about_sheet(workbook, formats, report: dict):
    meta = report["meta"]
    ws = workbook.add_worksheet("About")
    ws.set_column(0, 0, 26)
    ws.set_column(1, 1, 100)
    ws.write(0, 0, "Environment Data Report", formats["title"])
    ws.write(1, 0, "Generated (UTC)", formats["label"])
    ws.write(1, 1, meta["generated_at"], formats["datetime"])
    ws.write(2, 0, "Prepared for", formats["label"])
    ws.write(2, 1, _text(meta.get("user_email")), formats["text"])
    ws.write(3, 0, "Filters", formats["label"])
    ws.write(3, 1, _filters_text(meta), formats["text"])
    selection = meta.get("selection") or {}
    dataset_count = selection.get("dataset_count", 0)
    ws.write(4, 0, "Selection", formats["label"])
    ws.write(
        4, 1,
        f"{dataset_count} dataset{'s' if dataset_count != 1 else ''} · "
        f"{selection.get('station_count', 0)} stations · "
        f"{selection.get('row_count', 0):,} rows · "
        f"{selection.get('anomaly_count', 0):,} flagged samples · "
        f"{selection.get('outlook_count', 0)} outlooks",
        formats["text"],
    )

    row = 6
    ws.write(row, 0, "Datasets", formats["section"])
    row += 1
    headers = ["Dataset", "Type", "Tags", "Rows", "Uploaded", "Source file"]
    for col, label in enumerate(headers):
        ws.write(row, col, label, formats["header"])
    row += 1
    for dataset in meta.get("datasets") or []:
        caps = ", ".join(TYPE_LABELS.get(cap, cap) for cap in dataset.get("capabilities") or [])
        ws.write_string(row, 0, _text(dataset.get("name")))
        ws.write_string(row, 1, _text(caps))
        ws.write_string(row, 2, _text(", ".join(dataset.get("tags") or [])))
        ws.write_number(row, 3, dataset.get("row_count") or 0, formats["int"])
        if dataset.get("updated_at") or dataset.get("created_at"):
            ws.write_datetime(row, 4, dataset.get("updated_at") or dataset.get("created_at"), formats["date"])
        else:
            ws.write_blank(row, 4, None)
        ws.write_string(row, 5, _text(dataset.get("filename")))
        row += 1

    row += 1
    ws.write(row, 0, "How the numbers are produced", formats["section"])
    row += 1
    for note in meta.get("notes") or []:
        ws.write(row, 0, _text(note), formats["wrap"])
        ws.set_row(row, 30)
        row += 1

    row += 1
    ws.write(row, 0, "Coverage notes", formats["section"])
    row += 1
    for note in report.get("notes") or []:
        ws.write(row, 0, _text(note), formats["wrap"])
        ws.set_row(row, 30)
        row += 1

    row += 1
    ws.write(row, 0, "Limitations", formats["section"])
    row += 1
    limitations = [
        "Raw records are not embedded in this workbook (Excel caps a sheet at 1,048,576 rows). Use the CSV/ZIP export for every record.",
        "Missing values are blank, never zero or the string 'nan'.",
        "Expected ranges on anomalies are descriptive, not regulatory limits.",
        "Outlooks use harmonic regression when the series is long enough and exponential smoothing otherwise; a model that loses to persistence is replaced by the persistence baseline and claims no skill. Intervals are 80% prediction intervals from a rolling-origin evaluation, and sparse series get no outlook.",
        "Outlooks flagged as worse than persistence or stale should not be read as forecasts.",
        "Partial months at either edge of the window are excluded from the PDF chart; their monthly sheet rows remain and are marked in the Partial month column. Mean uses scored samples only.",
        "The bacteriological flag compares the latest coliform sample with 5,000 MPN/100 mL (Class C); it is not a window average.",
    ]
    selected_types = set(report.get("meta", {}).get("data_types") or [])
    if "rainfall" in selected_types:
        limitations.append("Rain chance is climatological (roughly ±12 percentage points); Brier skill is leave-one-year-out against the constant base rate, with a 95% Wilson interval.")
    for note in limitations:
        ws.write(row, 0, _text(note), formats["wrap"])
        ws.set_row(row, 30)
        row += 1


def _overview_sheet(workbook, formats, report: dict):
    headers = [
        "Dataset", "Data type", "Headline", "Unit", "Stations", "Rows",
        "Scored", "Coverage %", "First date", "Last date", "Latest", "Latest date",
        "Latest station", "Latest category", "Mean (scored)", "Mean category",
        "Min", "Max", "Max date", "Max station",
    ]
    widths = [28, 16, 14, 10, 10, 10, 10, 11, 12, 12, 10, 12, 26, 18, 14, 18, 10, 10, 12, 26]
    sheet = _Sheet(workbook, "Overview", widths, headers)
    sheet.workbook_formats = formats
    sheet.header()
    rows = _cap(report.get("overview") or [])
    for row in rows:
        sheet.write([
            row.get("dataset_name"), row.get("data_type_label"),
            row.get("headline_label"), row.get("unit"),
            row.get("station_count"), row.get("row_count"), row.get("scored_rows"),
            row.get("coverage_pct"), row.get("start_date"), row.get("end_date"),
            row.get("latest_value"), row.get("latest_date"), row.get("latest_station"),
            row.get("latest_category"), row.get("mean_value"), row.get("mean_category"),
            row.get("min_value"), row.get("max_value"), row.get("max_date"),
            row.get("max_station"),
        ])
    data_end = sheet.row - 1
    if len(report.get("overview") or []) > MAX_ROWS:
        sheet.note(f"Showing the first {MAX_ROWS} rows; the CSV/ZIP export carries the full window.")
    sheet.finish(data_end)


def _station_sheet(workbook, formats, report: dict):
    headers = [
        "Dataset", "Data type", "Station", "Scored samples", "First date", "Last date",
        "Latest", "Latest category", "Mean", "Mean category", "Min", "Max",
        "Max date", "Unit", "Rank", "Rank of", "Rank samples", "Best-use class",
        "Bacteriological flag", "Min DO", "DO flag",
    ]
    widths = [28, 16, 30, 10, 12, 12, 10, 18, 10, 18, 10, 10, 12, 10, 8, 9, 12, 16, 40, 10, 24]
    sheet = _Sheet(workbook, "Station summary", widths, headers)
    sheet.workbook_formats = formats
    sheet.header()
    rows = _cap(report.get("stations") or [])
    for row in rows:
        sheet.write([
            row.get("dataset_name"), row.get("data_type_label"), row.get("location_label") or row.get("location"),
            row.get("scored_count"), row.get("first_date"), row.get("last_date"),
            row.get("latest_value"), row.get("latest_category"), row.get("mean_value"),
            row.get("mean_category"), row.get("min_value"), row.get("max_value"),
            row.get("max_date"), row.get("unit"), row.get("rank_position"),
            row.get("rank_of"), row.get("rank_samples"), row.get("best_use_class"),
            row.get("bacteriological_flag"), row.get("min_do"), row.get("do_flag"),
        ])
    data_end = sheet.row - 1
    if len(report.get("stations") or []) > MAX_ROWS:
        sheet.note(f"Showing the first {MAX_ROWS} stations; refine the filters for the rest.")
    sheet.finish(data_end)


def _monthly_sheet(workbook, formats, report: dict):
    headers = [
        "Dataset", "Data type", "Station", "Month", "Parameter", "Unit",
        "Mean (scored)", "Min", "Max", "Samples", "Scored", "Partial month",
    ]
    widths = [28, 16, 30, 10, 16, 10, 12, 10, 10, 9, 9, 13]
    sheet = _Sheet(workbook, "Monthly", widths, headers)
    sheet.workbook_formats = formats
    sheet.header()
    rows = _cap(report.get("monthly") or [])
    for row in rows:
        sheet.write([
            row.get("dataset_name"), row.get("data_type_label"), row.get("location_label") or row.get("location"),
            row.get("month_date"), row.get("parameter_label"), row.get("unit"),
            row.get("mean"), row.get("min"), row.get("max"), row.get("count"),
            row.get("scored_count"), row.get("partial"),
        ])
    data_end = sheet.row - 1
    if len(report.get("monthly") or []) > MAX_ROWS:
        sheet.note(f"Showing the first {MAX_ROWS} station-months.")
    sheet.finish(data_end)


def _anomaly_sheet(workbook, formats, report: dict):
    headers = [
        "Dataset", "Data type", "Station", "Timestamp", "Parameter", "Unit",
        "Value", "Expected low", "Expected high", "Severity", "Direction",
        "Effect", "Method",
    ]
    widths = [28, 16, 28, 18, 16, 10, 10, 12, 12, 10, 14, 16, 22]
    sheet = _Sheet(workbook, "Anomalies", widths, headers)
    sheet.workbook_formats = formats
    sheet.header()
    rows = _cap(report.get("anomalies") or [])
    for row in rows:
        sheet.write([
            row.get("dataset_name"), row.get("data_type_label"), row.get("location_label") or row.get("location"),
            row.get("timestamp"), row.get("parameter_label"), row.get("unit"),
            row.get("value"), row.get("expected_low"), row.get("expected_high"),
            row.get("severity"), row.get("direction_label"), row.get("effect"),
            row.get("detector"),
        ])
    data_end = sheet.row - 1
    totals = report.get("anomaly_totals") or []
    flagged = sum(item.get("flagged", 0) for item in totals)
    shown = len(rows)
    if flagged > shown:
        sheet.note(
            f"Showing the {shown} most severe of {flagged:,} flagged samples. "
            "The CSV/ZIP export carries the raw record window."
        )
    sheet.finish(data_end)


def _outlook_sheet(workbook, formats, report: dict):
    headers = [
        "Dataset", "Data type", "Station", "Parameter", "Unit", "Target date",
        "Forecast", "Lower 80%", "Upper 80%", "MAE", "Baseline MAE",
        "Skill %", "Beats baseline", "Stale", "Method", "Note",
    ]
    widths = [28, 16, 28, 16, 10, 12, 10, 10, 10, 9, 12, 9, 14, 8, 26, 60]
    sheet = _Sheet(workbook, "Outlooks", widths, headers)
    sheet.workbook_formats = formats
    sheet.header()
    rows = _cap(report.get("outlooks") or [])
    for row in rows:
        sheet.write([
            row.get("dataset_name"), row.get("data_type_label"), row.get("location_label") or row.get("location"),
            row.get("parameter_label"), row.get("unit"), row.get("target_date"),
            row.get("forecast_value"), row.get("lower_bound"), row.get("upper_bound"),
            row.get("mae"), row.get("baseline_mae"), row.get("skill_pct"),
            row.get("beats_baseline"), row.get("stale"),
            row.get("method"), row.get("note"),
        ])
    for offset, row in enumerate(rows):
        skill = row.get("skill_pct")
        if isinstance(skill, (int, float)) and not isinstance(skill, bool):
            sheet.worksheet.write_number(
                sheet.header_row + 1 + offset, 11, float(skill), formats["one_decimal"]
            )
    data_end = sheet.row - 1
    if not rows:
        sheet.note("No forecasts are available for this selection.")
    elif len(report.get("outlooks") or []) > MAX_ROWS:
        sheet.note(f"Showing the first {MAX_ROWS} outlooks.")
    for coverage in report.get("outlook_coverage") or []:
        sheet.note(
            f"{coverage.get('dataset_name')}: {coverage.get('stations_with_outlook')} of "
            f"{coverage.get('station_count')} stations have at least one outlook; "
            f"{len(coverage.get('missing_stations') or [])} have none. "
            f"{coverage.get('sparse_slots')} station-parameter series have fewer than "
            f"{coverage.get('min_months')} monthly points; "
            f"{coverage.get('unexplained_slots')} have enough points but no stored forecast."
        )
    sheet.finish(data_end)


def _quality_sheet(workbook, formats, report: dict):
    headers = [
        "Dataset", "Data type", "Rows read", "Rows stored", "Duplicates removed",
        "Columns dropped", "Columns renamed", "Synonyms merged", "Source format", "Notes",
    ]
    widths = [30, 16, 11, 11, 16, 13, 13, 13, 14, 90]
    sheet = _Sheet(workbook, "Data quality", widths, headers)
    sheet.workbook_formats = formats
    sheet.header()
    for row in report.get("data_quality") or []:
        sheet.write([
            row.get("dataset_name"), TYPE_LABELS.get(row.get("data_type"), row.get("data_type")),
            row.get("rows_read"), row.get("rows_stored"), row.get("duplicates_removed"),
            row.get("columns_dropped"), row.get("columns_renamed"),
            row.get("synonym_columns_merged"), row.get("source_format"),
            " ".join(row.get("notes") or []),
        ])
    sheet.finish()


def build_workbook(report: dict) -> bytes:
    buffer = io.BytesIO()
    workbook = xlsxwriter.Workbook(buffer, {
        "in_memory": False,
        "constant_memory": True,
        "default_date_format": "dd mmm yyyy",
    })
    formats = {
        "title": workbook.add_format({"bold": True, "font_size": 18, "font_color": "#1F4E79"}),
        "section": workbook.add_format({"bold": True, "font_size": 12, "font_color": "#1F4E79", "bottom": 1}),
        "label": workbook.add_format({"bold": True}),
        "text": workbook.add_format({"text_wrap": False}),
        "wrap": workbook.add_format({"text_wrap": True, "valign": "top"}),
        "note": workbook.add_format({"italic": True, "font_color": "#595959"}),
        "header": workbook.add_format({
            "bold": True, "font_color": "#FFFFFF", "bg_color": "#1F4E79",
            "border": 1, "text_wrap": True, "valign": "vcenter",
        }),
        "date": workbook.add_format({"num_format": "dd mmm yyyy"}),
        "datetime": workbook.add_format({"num_format": "dd mmm yyyy hh:mm"}),
        "int": workbook.add_format({"num_format": "#,##0"}),
        "float": workbook.add_format({"num_format": "0.00"}),
        "one_decimal": workbook.add_format({"num_format": "0.0"}),
    }

    _about_sheet(workbook, formats, report)
    _overview_sheet(workbook, formats, report)
    _station_sheet(workbook, formats, report)
    _monthly_sheet(workbook, formats, report)
    _anomaly_sheet(workbook, formats, report)
    _outlook_sheet(workbook, formats, report)
    _quality_sheet(workbook, formats, report)

    workbook.close()
    return buffer.getvalue()
