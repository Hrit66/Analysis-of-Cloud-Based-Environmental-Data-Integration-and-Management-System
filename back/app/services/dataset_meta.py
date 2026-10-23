from typing import Optional

SOURCE_TAGS = ("real", "synthetic", "modelled")


def source_tag_for(doc: dict) -> str:
    """Resolve the provenance label from explicit metadata or pipeline hints."""
    explicit = str(doc.get("source_tag") or "").strip().lower()
    if explicit in SOURCE_TAGS:
        return explicit
    hints = [
        doc.get("data_nature"),
        doc.get("label"),
        doc.get("display_name"),
        doc.get("filename"),
        (doc.get("cleaning_report") or {}).get("data_nature") if isinstance(doc.get("cleaning_report"), dict) else None,
    ]
    text = " ".join(str(value).lower() for value in hints if value)
    if "synthetic" in text:
        return "synthetic"
    if "modelled" in text or "modeled" in text:
        return "modelled"
    return "real"
