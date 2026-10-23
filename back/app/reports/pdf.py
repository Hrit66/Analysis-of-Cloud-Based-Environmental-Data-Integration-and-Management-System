"""PDF renderer for the report payload.

Layout is deliberately simple: cover, automatically written findings, one
section per dataset (cards, top/bottom stations, a monthly chart, outlooks),
the top 20 anomalies, methodology and a data-quality appendix. All values come
from ``build_report_data``; the only thing computed here is chart aggregation
(monthly means across stations), which is presentation, not statistics.
"""
import io
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import dates as mdates  # noqa: E402

from reportlab.lib import colors  # noqa: E402
from reportlab.lib.enums import TA_CENTER  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    CondPageBreak, Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate,
    Spacer, Table, TableStyle,
)

from app.services.report_units import PARAMETER_LABELS, TYPE_LABELS, TYPE_ORDER  # noqa: E402

NAVY = colors.HexColor("#1F4E79")
LIGHT = colors.HexColor("#EAF1F8")
GREY = colors.HexColor("#595959")

FONT_CANDIDATES = [
    ("/usr/share/fonts/truetype/dejavu", "DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans-Oblique.ttf"),
    ("/usr/share/fonts/dejavu-sans-fonts", "DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans-Oblique.ttf"),
    ("/usr/share/fonts/TTF", "DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans-Oblique.ttf"),
]


def _register_fonts() -> tuple:
    """Register DejaVu when available so µ, ³, ≥ and ± render correctly."""
    import os

    for directory, regular, bold, oblique in FONT_CANDIDATES:
        regular_path = os.path.join(directory, regular)
        if not os.path.exists(regular_path):
            continue
        pdfmetrics.registerFont(TTFont("DejaVu", regular_path))
        bold_path = os.path.join(directory, bold)
        if os.path.exists(bold_path):
            pdfmetrics.registerFont(TTFont("DejaVu-Bold", bold_path))
        oblique_path = os.path.join(directory, oblique)
        if os.path.exists(oblique_path):
            pdfmetrics.registerFont(TTFont("DejaVu-Oblique", oblique_path))
        return "DejaVu", "DejaVu-Bold", "DejaVu-Oblique"
    return "Helvetica", "Helvetica-Bold", "Helvetica-Oblique"


REGULAR, BOLD, OBLIQUE = _register_fonts()
HAS_UNICODE_FONT = REGULAR == "DejaVu"


def _tidy(value) -> str:
    if value is None:
        return "—"
    text = str(value)
    if HAS_UNICODE_FONT:
        return text
    return (text.replace("µ", "u").replace("³", "3").replace("≥", ">=")
            .replace("≤", "<=").replace("±", "+/-").replace("°", " deg"))


def _p(text, style) -> Paragraph:
    return Paragraph(_escape(text), style)


def _escape(value) -> str:
    return _tidy(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _styles() -> Dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    body = ParagraphStyle(
        "body", parent=base["BodyText"], fontName=REGULAR, fontSize=9, leading=13,
        textColor=colors.black, spaceAfter=3,
    )
    return {
        "title": ParagraphStyle(
            "title", parent=body, fontName=BOLD, fontSize=26, leading=32,
            textColor=NAVY, spaceAfter=6,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=body, fontName=REGULAR, fontSize=12, leading=17,
            textColor=GREY, spaceAfter=18,
        ),
        "h1": ParagraphStyle(
            "h1", parent=body, fontName=BOLD, fontSize=16, leading=20,
            textColor=NAVY, spaceBefore=12, spaceAfter=8,
        ),
        "h2": ParagraphStyle(
            "h2", parent=body, fontName=BOLD, fontSize=12, leading=16,
            textColor=NAVY, spaceBefore=10, spaceAfter=5,
        ),
        "body": body,
        "small": ParagraphStyle("small", parent=body, fontSize=7.5, leading=10, textColor=GREY),
        "cell": ParagraphStyle("cell", parent=body, fontSize=7.5, leading=9.5, spaceAfter=0),
        "cell_small": ParagraphStyle("cell_small", parent=body, fontSize=7, leading=9, spaceAfter=0),
        "right": ParagraphStyle("right", parent=body, fontName=REGULAR, fontSize=8.5, leading=11, alignment=2),
        "cover_caption": ParagraphStyle(
            "cover_caption", parent=body, fontSize=9, leading=13, textColor=GREY,
        ),
    }


def _pct(value) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "—"


def _fmt(value, digits: int = 2) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        return value.strftime("%d %b %Y")
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}"
    if isinstance(value, float):
        if value.is_integer():
            return f"{value:,.0f}"
        return f"{value:,.{digits}f}"
    return _tidy(value)


def _table(rows: List[List], widths: List[float], header: bool = True, font_size: float = 7.5) -> Table:
    if header and rows:
        header_style = ParagraphStyle(
            "table_header", fontName=BOLD, fontSize=font_size,
            leading=font_size + 1.5, textColor=colors.white,
        )
        rows = [rows[0]] + rows[1:]
        rows[0] = [
            cell if not isinstance(cell, str) else Paragraph(_escape(cell), header_style)
            for cell in rows[0]
        ]
    table = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    commands = [
        ("FONTNAME", (0, 0), (-1, -1), REGULAR),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#BFBFBF")),
    ]
    if header:
        commands += [
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), BOLD),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ]
    table.setStyle(TableStyle(commands))
    return table


def _card_rows(report: dict, overview: dict) -> List[List]:
    missing = overview.get("missing") or {}
    groups: Dict[float, List[str]] = {}
    for param, pct in missing.items():
        if pct and pct > 0:
            groups.setdefault(round(pct, 1), []).append(
                PARAMETER_LABELS.get(param, param)
            )
    missing_text = ", ".join(
        f"{', '.join(sorted(labels))} {pct:.1f}%"
        for pct, labels in sorted(groups.items(), key=lambda kv: -kv[0])[:3]
    ) or "none"
    not_in_source = overview.get("not_in_source") or []
    not_in_source_text = ", ".join(
        PARAMETER_LABELS.get(param, param) for param in not_in_source
    ) or "—"
    date_range = (
        f"{_fmt(overview.get('start_date'))} – {_fmt(overview.get('end_date'))}"
        if overview.get("start_date") or overview.get("end_date") else "—"
    )
    unit = overview.get("unit") or ""
    return [
        ["Stations", _fmt(overview.get("station_count")),
         "Rows in window", _fmt(overview.get("row_count"))],
        ["Date range", date_range, "Scored rows", (
            f"{_fmt(overview.get('scored_rows'))} "
            f"({_fmt(overview.get('coverage_pct'), 1)}% coverage)"
        )],
        ["Latest sample", f"{_fmt(overview.get('latest_value'))} {unit}".strip(),
         "Latest station", _fmt(overview.get("latest_station"))],
        ["Latest date", _fmt(overview.get("latest_date")),
         "Latest category", overview.get("latest_category") or "—"],
        [f"Mean {overview.get('headline_label', 'value')} (scored)",
         f"{_fmt(overview.get('mean_value'))} {unit}".strip(),
         "Mean category", overview.get("mean_category") or "—"],
        ["Min / max", f"{_fmt(overview.get('min_value'))} / {_fmt(overview.get('max_value'))} {unit}".strip(),
         "Max station", overview.get("max_station") or "—"],
        ["Most missing", missing_text, "Max date", _fmt(overview.get("max_date"))],
        ["Not in source", not_in_source_text, "Flagged anomalies",
         f"{_fmt(overview.get('anomaly_count'))} of {_fmt(overview.get('scanned_count'))} scanned"],
    ]


def _dataset_chart(report: dict, dataset_id: str, data_type: str, start_date=None, end_date=None) -> Optional[Image]:
    rows = [
        row for row in report.get("monthly") or []
        if row.get("dataset_id") == dataset_id and row.get("data_type") == data_type
        and row.get("mean") is not None and row.get("month")
    ]
    if not rows:
        return None
    monthly: Dict[str, List[float]] = defaultdict(list)
    weights: Dict[str, float] = defaultdict(float)
    for row in rows:
        count = row.get("count") or 1
        monthly[row["month"]].append(row["mean"] * count)
        weights[row["month"]] += count
    labels = sorted(monthly)
    partial_labels: List[str] = []
    if labels and isinstance(start_date, datetime) and start_date.day > 1:
        first_label = labels[0]
        try:
            first_date = datetime.strptime(first_label, "%Y-%m")
        except ValueError:
            first_date = None
        if first_date and start_date.year == first_date.year and start_date.month == first_date.month:
            partial_labels.append(labels.pop(0))
    if labels and isinstance(end_date, datetime):
        last_label = labels[-1]
        try:
            last_date = datetime.strptime(last_label, "%Y-%m")
        except ValueError:
            last_date = None
        if last_date and end_date.year == last_date.year and end_date.month == last_date.month:
            import calendar
            last_day = calendar.monthrange(end_date.year, end_date.month)[1]
            if end_date.day < last_day:
                partial_labels.append(labels.pop())
    values = [sum(monthly[label]) / weights[label] for label in labels]
    if not values:
        return None
    try:
        dates = [datetime.strptime(label, "%Y-%m") for label in labels]
    except ValueError:
        dates = list(range(len(labels)))

    fig, ax = plt.subplots(figsize=(7.2, 2.4), dpi=140)
    ax.plot(dates, values, color="#1F4E79", linewidth=1.4)
    ax.fill_between(dates, values, 0, color="#1F4E79", alpha=0.08)
    ax.set_ylim(bottom=0)
    ax.set_ylabel(PARAMETER_LABELS.get(
        {"water_quality": "wqi", "air_quality": "aqi", "temperature": "temperature",
         "rainfall": "precipitation"}[data_type], "value"), fontsize=7)
    ax.tick_params(labelsize=6)
    ax.grid(alpha=0.25, linewidth=0.4)
    if dates and isinstance(dates[0], datetime):
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=9))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        fig.autofmt_xdate(rotation=35, ha="right")
    fig.tight_layout()
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", bbox_inches="tight")
    plt.close(fig)
    buffer.seek(0)
    image = Image(buffer, width=170 * mm, height=56 * mm)
    image._partial_labels = partial_labels
    return image


def _chart_label(data_type: str) -> str:
    return {
        "water_quality": "Mean WQI by month (all stations)",
        "air_quality": "Mean AQI by month (all stations)",
        "temperature": "Mean temperature by month (all stations)",
        "rainfall": "Mean daily precipitation by month (all stations)",
    }.get(data_type, "Mean by month")


def _findings(report: dict) -> List[str]:
    findings: List[str] = []
    for overview in report.get("overview") or []:
        findings.append(
            f"{TYPE_LABELS.get(overview['data_type'], overview['data_type'])} "
            f"({overview['dataset_name']}): {_fmt(overview.get('station_count'))} stations, "
            f"{_fmt(overview.get('row_count'))} samples ({_fmt(overview.get('scored_rows'))} scored, "
            f"{_fmt(overview.get('coverage_pct'), 1)}% coverage); mean "
            f"{overview.get('headline_label')} over scored samples {_fmt(overview.get('mean_value'))} "
            f"(range {_fmt(overview.get('min_value'))}–{_fmt(overview.get('max_value'))})."
        )

    worst = [
        row for row in report.get("stations") or []
        if row.get("data_type") in {"water_quality", "air_quality"}
        and row.get("mean_value") is not None
        and (row.get("data_type") != "water_quality" or row.get("rank"))
    ]
    if worst:
        peak = max(worst, key=lambda row: row["mean_value"])
        findings.append(
            f"Worst ranked station by mean {peak.get('data_type_label', 'index')}: "
            f"{peak.get('location_label') or peak['location']} at {_fmt(peak['mean_value'])} "
            f"(latest {_fmt(peak.get('latest_value'))}, worst sample {_fmt(peak.get('max_value'))}; "
            f"rank {peak.get('rank') or 'unranked'})."
        )

    totals = report.get("anomaly_totals") or []
    flagged = sum(item.get("flagged", 0) for item in totals)
    scanned = sum(item.get("scanned", 0) for item in totals)
    if flagged:
        top = next(
            (row for row in report.get("anomalies") or []
             if row.get("effect") != "improvement"),
            None,
        )
        line = f"{flagged:,} flagged samples out of {scanned:,} scanned"
        if scanned:
            line += f" ({flagged / scanned * 100:.1f}%)"
        if top:
            line += (
                f"; the largest anomaly score is {top.get('location_label') or top['location']} "
                f"{top['parameter_label']} = {_fmt(top['value'])} on {_fmt(top['timestamp'])}"
                f" (expected {_fmt(top['expected_low'])}–{_fmt(top['expected_high'])} from the "
                f"station's full history, {top.get('severity') or 'unspecified'} severity)."
            )
        else:
            line += "."
        findings.append(line)

    for summary in report.get("do_summary") or []:
        samples = [
            row for row in report.get("low_do") or []
            if row.get("dataset_id") == summary.get("dataset_id")
        ]
        line = (
            f"Low dissolved oxygen ({summary.get('dataset_name')}): "
            f"{summary.get('critical', 0)} stations below 2 mg/L and "
            f"{summary.get('low', 0)} more between 2 and 4 mg/L on their worst sample"
        )
        if samples:
            worst = "; ".join(
                f"{row.get('location_label') or row.get('location')} {_fmt(row.get('value'))} "
                f"on {_fmt(row.get('timestamp'))}"
                for row in samples
            )
            line += f". Lowest readings: {worst}."
        else:
            line += "."
        findings.append(line)

    for overview in report.get("overview") or []:
        missing = overview.get("missing") or {}
        groups: Dict[float, List[str]] = {}
        for param, pct in missing.items():
            if pct and pct > 0:
                groups.setdefault(round(pct, 1), []).append(
                    PARAMETER_LABELS.get(param, param)
                )
        if groups:
            text = "; ".join(
                f"{', '.join(sorted(labels))} {pct:.1f}%"
                for pct, labels in sorted(groups.items(), key=lambda kv: -kv[0])[:3]
            )
            findings.append(f"Highest missing fields ({overview.get('dataset_name')}): {text}.")
        not_in_source = overview.get("not_in_source") or []
        if not_in_source:
            listed = ", ".join(
                PARAMETER_LABELS.get(param, param) for param in not_in_source
            )
            findings.append(
                f"No source readings for {listed} in {overview.get('dataset_name')}; "
                "these fields are excluded from missing-field percentages."
            )

    outlooks = report.get("outlooks") or []
    if outlooks:
        skills = [row["skill_pct"] for row in outlooks if row.get("skill_pct") is not None]
        stale = sum(1 for row in outlooks if row.get("stale"))
        weaker = sum(1 for row in outlooks if not row.get("beats_baseline"))
        line = f"{len(outlooks)} station-parameter outlooks are included"
        if skills:
            line += f"; mean skill vs persistence {sum(skills) / len(skills):.1f}%"
        line += f"; {weaker} are worse than persistence and {stale} are stale (both flagged)"
        findings.append(line + ".")
        gaps = sum(
            len(item.get("missing_stations") or [])
            for item in report.get("outlook_coverage") or []
        )
        if gaps:
            findings.append(
                f"{gaps} stations have no outlook; the reason (fewer than "
                f"{report['outlook_coverage'][0].get('min_months', 24)} monthly points or no stored "
                "forecast) is listed with the outlooks."
            )
    else:
        findings.append("No forecasts are available for this selection (sparse series or no forecast run).")

    low_coverage = []
    for overview in report.get("overview") or []:
        for param, pct in (overview.get("missing") or {}).items():
            if pct and pct >= 50:
                low_coverage.append(PARAMETER_LABELS.get(param, param))
    if low_coverage:
        unique = sorted(set(low_coverage))
        findings.append(
            "Parameters missing in at least half of the selected rows: " + ", ".join(unique) + "."
        )
    return findings


def _cover(story: List, report: dict, styles: Dict[str, ParagraphStyle]):
    meta = report["meta"]
    story.append(Spacer(1, 40 * mm))
    story.append(Paragraph("Environment Data Report", styles["title"]))
    story.append(Paragraph(
        "Air, water and weather data from the EnvPlatform dashboards, generated from the same "
        "queries the dashboards use.", styles["subtitle"],
    ))
    selection = meta.get("selection") or {}
    dataset_count = selection.get("dataset_count", 0)
    lines = [
        ["Generated", meta["generated_at"].strftime("%d %b %Y %H:%M UTC")],
        ["Prepared for", meta.get("user_email") or "—"],
        ["Date range", (
            f"{_fmt(meta.get('start_date'))} – {_fmt(meta.get('end_date'))}"
            if meta.get("start_date") or meta.get("end_date") else "Full history"
        )],
        ["Data types", ", ".join(TYPE_LABELS.get(t, t) for t in meta.get("data_types") or [])],
        ["Selection", (
            f"{dataset_count} dataset{'s' if dataset_count != 1 else ''} · "
            f"{selection.get('station_count', 0)} stations · "
            f"{selection.get('row_count', 0):,} rows · "
            f"{selection.get('anomaly_count', 0):,} flagged samples · "
            f"{selection.get('outlook_count', 0)} outlooks"
        )],
    ]
    table = _table([[label, value] for label, value in lines], [34 * mm, 126 * mm], header=False, font_size=9)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), BOLD),
        ("GRID", (0, 0), (-1, -1), 0, colors.white),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#D9D9D9")),
    ]))
    story.append(table)
    story.append(Spacer(1, 10 * mm))

    story.append(Paragraph("Datasets in this report", styles["h2"]))
    datasets = meta.get("datasets") or []
    rows = [["Dataset", "Type", "Tags", "Rows"]]
    for dataset in datasets:
        caps = ", ".join(TYPE_LABELS.get(cap, cap) for cap in dataset.get("capabilities") or [])
        rows.append([
            _p(dataset.get("name"), styles["cell"]),
            _p(caps, styles["cell"]),
            _p(", ".join(dataset.get("tags") or []) or "—", styles["cell"]),
            _p(_fmt(dataset.get("row_count")), styles["cell"]),
        ])
    if len(rows) == 1:
        rows.append([_p("No datasets matched these filters.", styles["cell"]), "", "", ""])
    story.append(_table(rows, [70 * mm, 38 * mm, 40 * mm, 18 * mm]))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(
        "Tags: synthetic = generated data; modelled = derived, imputed, or source-appears-modelled values; merged = multi-file source.",
        styles["cover_caption"],
    ))
    story.append(PageBreak())


def _dataset_sections(report: dict, styles: Dict[str, ParagraphStyle]):
    story: List = []
    overviews = report.get("overview") or []
    stations = report.get("stations") or []
    outlooks = report.get("outlooks") or []

    for data_type in TYPE_ORDER:
        type_overviews = [row for row in overviews if row["data_type"] == data_type]
        if not type_overviews:
            continue
        story.append(CondPageBreak(100 * mm))
        story.append(Paragraph(TYPE_LABELS.get(data_type, data_type), styles["h1"]))
        for overview in type_overviews:
            dataset_id = overview["dataset_id"]
            header_block: List = []
            header_block.append(Paragraph(_tidy(overview["dataset_name"]), styles["h2"]))
            cards = [
                [_p(cell, styles["cell"]) for cell in row]
                for row in _card_rows(report, overview)
            ]
            header_block.append(_table(cards, [28 * mm, 54 * mm, 26 * mm, 52 * mm], header=False, font_size=8))
            story.append(KeepTogether(header_block))

            local = [
                row for row in stations
                if row["dataset_id"] == dataset_id and row["data_type"] == data_type
                and row.get("mean_value") is not None
                and (data_type != "water_quality" or row.get("rank"))
            ]
            local.sort(key=lambda row: row["mean_value"])
            if local:
                bottom = local[:5]
                top = list(reversed(local[-5:]))
                rows = [["Station", "Mean", "Mean category", "Scored", "Latest", "Worst", "Rank"]]
                spans = []
                for title, group in (("Best 5 by mean (lowest WQI)", bottom),
                                     ("Worst 5 by mean (highest WQI)", top)):
                    spans.append(len(rows))
                    rows.append([title, "", "", "", "", "", ""])
                    for row in group:
                        rows.append([
                            _p(row.get("location_label") or row.get("location"), styles["cell"]),
                            _p(_fmt(row.get("mean_value")), styles["cell"]),
                            _p(row.get("mean_category") or "—", styles["cell"]),
                            _p(_fmt(row.get("scored_count")), styles["cell"]),
                            _p(f"{_fmt(row.get('latest_value'))} [{_fmt(row.get('last_date'))}]", styles["cell"]),
                            _p(f"{_fmt(row.get('max_value'))} [{_fmt(row.get('max_date'))}]", styles["cell"]),
                            _p(row.get("rank") or "—", styles["cell"]),
                        ])
                table = _table(rows, [39 * mm, 14 * mm, 26 * mm, 16 * mm, 29 * mm, 29 * mm, 17 * mm])
                style = [
                    ("SPAN", (0, index), (-1, index)) for index in spans
                ]
                style += [
                    ("BACKGROUND", (0, index), (-1, index), LIGHT)
                    for index in spans
                ]
                style += [
                    ("FONTNAME", (0, index), (-1, index), BOLD)
                    for index in spans
                ]
                table.setStyle(TableStyle(style))
                do_rows = [
                    row for row in stations
                    if row["dataset_id"] == dataset_id and row["data_type"] == data_type
                    and row.get("do_flag")
                ]
                do_critical = sum(
                    1 for row in do_rows if (row.get("do_flag") or "").startswith("critical")
                )
                do_low = sum(
                    1 for row in do_rows if (row.get("do_flag") or "").startswith("low DO")
                )
                do_note = (
                    f" Low-DO flag (absolute): {do_critical} stations below 2 mg/L and "
                    f"{do_low} more between 2 and 4 mg/L on their worst sample in the window."
                    if do_rows else ""
                )
                story.append(CondPageBreak(100 * mm))
                story.append(KeepTogether([
                    Spacer(1, 3 * mm),
                    table,
                    Paragraph(
                        "Mean category is computed from the station mean, not the latest sample. "
                        "Only ranked stations (at least three scored samples) enter these lists; "
                        "unranked stations are excluded rather than labelled the worst."
                        + do_note,
                        styles["small"],
                    ),
                ]))

            if data_type == "water_quality":
                do_readings = [
                    row for row in report.get("low_do") or []
                    if row.get("dataset_id") == dataset_id
                ]
                if do_readings:
                    do_table_rows = [["Station", "DO (mg/L)", "Date"]]
                    for row in do_readings:
                        do_table_rows.append([
                            _p(row.get("location_label") or row.get("location"), styles["cell"]),
                            _p(_fmt(row.get("value")), styles["cell"]),
                            _p(_fmt(row.get("timestamp")), styles["cell"]),
                        ])
                    story.append(CondPageBreak(60 * mm))
                    story.append(KeepTogether([
                        Spacer(1, 3 * mm),
                        Paragraph(
                            "Lowest dissolved-oxygen samples in the window", styles["h2"]
                        ),
                        _table(do_table_rows, [95 * mm, 30 * mm, 45 * mm]),
                    ]))

            chart = _dataset_chart(
                report, dataset_id, data_type,
                overview.get("start_date"), overview.get("end_date"),
            )
            if chart:
                story.append(Spacer(1, 3 * mm))
                story.append(Paragraph(_tidy(_chart_label(data_type)), styles["body"]))
                story.append(chart)
                partials = getattr(chart, "_partial_labels", [])
                if partials:
                    noun = "month is" if len(partials) == 1 else "months are"
                    story.append(Paragraph(
                        f"Note: {' and '.join(partials)} {noun} partial and "
                        f"{'is' if len(partials) == 1 else 'are'} excluded from the chart.",
                        styles["small"],
                    ))

            section_outlooks = [
                row for row in outlooks
                if row["dataset_id"] == dataset_id and row["data_type"] == data_type
            ]
            stale = sum(1 for row in section_outlooks if row.get("stale"))
            weaker = sum(1 for row in section_outlooks if not row.get("beats_baseline"))
            usable = [
                row for row in section_outlooks
                if not row.get("stale") and row.get("beats_baseline")
            ]
            coverage = next(
                (item for item in report.get("outlook_coverage") or []
                 if item["dataset_id"] == dataset_id), None,
            )
            story.append(CondPageBreak(85 * mm))
            story.append(Spacer(1, 2 * mm))
            if usable:
                rows = [["Station", "Parameter", "Target", "Forecast", "80% interval", "MAE", "Baseline", "Skill"]]
                for row in usable[:12]:
                    rows.append([
                        _p(row.get("location_label") or row.get("location"), styles["cell"]),
                        _p(row.get("parameter_label"), styles["cell"]),
                        _p(_fmt(row.get("target_date")), styles["cell"]),
                        _p(f"{_fmt(row.get('forecast_value'))} {row.get('unit') or ''}".strip(), styles["cell"]),
                        _p(f"{_fmt(row.get('lower_bound'))}–{_fmt(row.get('upper_bound'))}", styles["cell"]),
                        _p(_fmt(row.get("mae")), styles["cell"]),
                        _p(_fmt(row.get("baseline_mae")), styles["cell"]),
                        _p(_pct(row.get("skill_pct")), styles["cell"]),
                    ])
                story.append(Paragraph("Outlooks that beat persistence (latest data)", styles["h2"]))
                story.append(_table(rows, [32 * mm, 28 * mm, 18 * mm, 22 * mm, 27 * mm, 13 * mm, 15 * mm, 15 * mm]))
                note = next((row.get("note") for row in usable if row.get("note")), None)
                shown = min(12, len(usable))
                shown_note = (
                    f"Showing the first {shown} of {len(usable)} usable outlooks. "
                    if len(usable) > shown else ""
                )
                extra = (
                    f"{shown_note}"
                    f"{len(section_outlooks)} stored outlooks; {weaker} are worse than persistence, "
                    f"{stale} are stale and both are excluded from this table (kept in Excel)."
                )
                story.append(Paragraph(
                    _tidy((note + " " if note else "") + extra +
                          " Intervals are 80% prediction intervals."),
                    styles["small"],
                ))
            else:
                story.append(Paragraph(
                    f"{len(section_outlooks)} stored outlooks, but none both beat persistence and "
                    "target a future month; see the Excel report for the flagged rows.",
                    styles["small"],
                ))
            if coverage and coverage.get("missing_stations"):
                names = ", ".join((coverage.get("missing_station_labels") or coverage["missing_stations"])[:8])
                more = "" if len(coverage["missing_stations"]) <= 8 else ", …"
                story.append(Paragraph(
                    _tidy(
                        f"{len(coverage['missing_stations'])} of {coverage['station_count']} stations "
                        f"have no outlook ({coverage['sparse_slots']} station-parameter series have fewer "
                        f"than {coverage['min_months']} monthly points; "
                        f"{coverage['unexplained_slots']} have enough points but no stored forecast). "
                        f"Examples: {names}{more}."
                    ),
                    styles["small"],
                ))
    return story


def _anomaly_section(report: dict, styles: Dict[str, ParagraphStyle]):
    story: List = []
    rows_data = report.get("anomalies") or []
    story.append(Paragraph("Anomalies", styles["h1"]))
    totals = report.get("anomaly_totals") or []
    flagged = sum(item.get("flagged", 0) for item in totals)
    if not rows_data:
        story.append(Paragraph("No anomalies were flagged in this selection.", styles["body"]))
        return story

    deteriorations = [row for row in rows_data if row.get("effect") == "deterioration"]
    improvements = [row for row in rows_data if row.get("effect") == "improvement"]
    unusual = [
        row for row in rows_data
        if row.get("effect") not in {"deterioration", "improvement"}
    ]
    story.append(Paragraph(
        f"{flagged:,} flagged samples in this window. Deteriorations are ranked first; "
        "improvements (for example unusually low WQI, which means better water) are "
        "listed separately and are not hazards. Expected ranges are descriptive, not "
        "regulatory limits.",
        styles["body"],
    ))

    def table(group, title):
        if not group:
            return
        story.append(Paragraph(title, styles["h2"]))
        rows = [["Dataset", "Station", "Date", "Parameter", "Value", "Expected",
                 "Direction", "Severity", "Method"]]
        for row in group[:15]:
            rows.append([
                _p(row.get("dataset_name"), styles["cell_small"]),
                _p(row.get("location_label") or row.get("location"), styles["cell_small"]),
                _p(_fmt(row.get("timestamp")), styles["cell_small"]),
                _p(row.get("parameter_label"), styles["cell_small"]),
                _p(f"{_fmt(row.get('value'))} {row.get('unit') or ''}".strip(), styles["cell_small"]),
                _p(f"{_fmt(row.get('expected_low'))}–{_fmt(row.get('expected_high'))}", styles["cell_small"]),
                _p(row.get("direction_label") or "—", styles["cell_small"]),
                _p(row.get("severity") or "—", styles["cell_small"]),
                _p((row.get("detector") or "—").replace("_", " "), styles["cell_small"]),
            ])
        story.append(_table(
            rows,
            [22 * mm, 33 * mm, 17 * mm, 17 * mm, 16 * mm, 23 * mm, 15 * mm, 15 * mm, 16 * mm],
            font_size=7,
        ))

    table(deteriorations, "Deteriorations")
    table(unusual, "Unusual values (direction not classified)")
    table(improvements, "Improvements / unusually good water")
    shown = sum(min(15, len(group)) for group in (deteriorations, unusual, improvements))
    if shown < len(rows_data):
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(
            f"Tables show at most 15 rows per group ({shown} of {len(rows_data):,} flagged "
            "samples included here); the Excel report lists every flagged sample.",
            styles["small"],
        ))
    return story


def _method_section(report: dict, styles: Dict[str, ParagraphStyle]):
    story = [Paragraph("Methodology and limitations", styles["h1"])]
    for note in report["meta"].get("notes") or []:
        story.append(Paragraph("• " + _tidy(note), styles["body"]))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(
        "Raw records are not embedded in the PDF; use the CSV/ZIP export for every row. "
        "Missing values are blank (never zero or the string 'nan'). Values are rounded for "
        "presentation; the Excel workbook carries the same rounded values.",
        styles["small"],
    ))
    return story


def _quality_section(report: dict, styles: Dict[str, ParagraphStyle]):
    story = [Paragraph("Data quality appendix", styles["h1"])]
    rows = [["Dataset", "Rows read", "Rows stored", "Dupes fixed", "Columns dropped", "Notes"]]
    for row in report.get("data_quality") or []:
        rows.append([
            _p(row.get("dataset_name"), styles["cell"]),
            _p(_fmt(row.get("rows_read")), styles["cell"]),
            _p(_fmt(row.get("rows_stored")), styles["cell"]),
            _p(_fmt(row.get("duplicates_removed")), styles["cell"]),
            _p(_fmt(row.get("columns_dropped")), styles["cell"]),
            _p(" ".join(row.get("notes") or []) or "—", styles["cell"]),
        ])
    story.append(_table(rows, [42 * mm, 17 * mm, 18 * mm, 16 * mm, 20 * mm, 57 * mm]))
    return story


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont(REGULAR, 7)
    canvas.setFillColor(GREY)
    canvas.drawString(18 * mm, 10 * mm, "Environment Data Report · built from the same queries as the dashboards")
    canvas.drawRightString(192 * mm, 10 * mm, f"Page {doc.page}")
    canvas.restoreState()


def build_pdf(report: dict) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title="Environment Data Report", author="EnvPlatform",
    )
    styles = _styles()
    story: List = []
    _cover(story, report, styles)

    story.append(Paragraph("Key findings", styles["h1"]))
    for finding in _findings(report):
        story.append(Paragraph("• " + _tidy(finding), styles["body"]))
    story.append(PageBreak())

    story.extend(_dataset_sections(report, styles))
    story.append(CondPageBreak(100 * mm))
    story.extend(_anomaly_section(report, styles))
    story.append(Spacer(1, 4 * mm))
    story.extend(_method_section(report, styles))
    story.append(Spacer(1, 6 * mm))
    story.extend(_quality_section(report, styles))

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()
