"""CPCB designated-best-use water quality classification (IS 2296:1992 / CPCB criteria).

Documented limits table (only the parameters this platform's water datasets
carry are enforced; the full IS 2296 table has more parameters):

    Class A  Drinking water source without conventional treatment but after
             disinfection: pH 6.5-8.5, DO >= 6 mg/L, BOD (5d, 20C) <= 2 mg/L,
             total coliform <= 50 MPN/100 mL
    Class B  Outdoor bathing (organised): pH 6.5-8.5, DO >= 5 mg/L,
             BOD <= 3 mg/L, total coliform <= 500 MPN/100 mL
    Class C  Drinking water source after conventional treatment and
             disinfection: pH 6.0-9.0, DO >= 4 mg/L, BOD <= 3 mg/L,
             total coliform <= 5000 MPN/100 mL
    Class D  Propagation of wildlife and fisheries: pH 6.5-8.5, DO >= 4 mg/L,
             free ammonia (as N) <= 1.2 mg/L
    Class E  Irrigation, industrial cooling, controlled waste disposal:
             pH 6.0-8.5, conductivity <= 2250 micromhos/cm, sodium adsorption
             ratio <= 26, boron <= 2 mg/L
    Below E  meets none of the checkable A-E criteria

Honesty rules:
- A sample's class is the BEST class whose checkable criteria are all met.
  Criteria whose parameter is missing are NOT assumed to pass: if the winning
  class has unchecked criteria the result is flagged ``partial`` with the
  missing parameter names - no guessing.
- The datasets store total ammonia (NH3-N), not free ammonia. Free ammonia is
  a fraction of total, so ``total <= 1.2`` proves the class-D ammonia
  criterion; when total exceeds 1.2 the criterion is unverifiable. Class D is
  therefore always flagged ``approximate`` on this data and its note says why.
- Sodium adsorption ratio and boron are not stored, so class E is partial on
  this data (pH and conductivity are still checked).
- This classification is reported separately from the WQI and is not mixed
  into the index.
"""
import math
from typing import Any, Dict, List, Optional

CPCB_USE_CLASSES: List[Dict[str, Any]] = [
    {
        "class": "A",
        "label": "Drinking water source without conventional treatment but after disinfection",
        "criteria": [
            ("ph", "range", 6.5, 8.5),
            ("do", "min", 6.0),
            ("bod", "max", 2.0),
            ("total_coliform", "max", 50.0),
        ],
    },
    {
        "class": "B",
        "label": "Outdoor bathing (organised)",
        "criteria": [
            ("ph", "range", 6.5, 8.5),
            ("do", "min", 5.0),
            ("bod", "max", 3.0),
            ("total_coliform", "max", 500.0),
        ],
    },
    {
        "class": "C",
        "label": "Drinking water source after conventional treatment and disinfection",
        "criteria": [
            ("ph", "range", 6.0, 9.0),
            ("do", "min", 4.0),
            ("bod", "max", 3.0),
            ("total_coliform", "max", 5000.0),
        ],
    },
    {
        "class": "D",
        "label": "Propagation of wildlife and fisheries",
        "criteria": [
            ("ph", "range", 6.5, 8.5),
            ("do", "min", 4.0),
            ("ammonia_free", "max", 1.2),
        ],
    },
    {
        "class": "E",
        "label": "Irrigation, industrial cooling, controlled waste disposal",
        "criteria": [
            ("ph", "range", 6.0, 8.5),
            ("conductivity", "max", 2250.0),
            ("sar", "max", 26.0),
            ("boron", "max", 2.0),
        ],
    },
]

_PARAM_LABELS = {
    "ph": "pH",
    "do": "dissolved oxygen",
    "bod": "BOD",
    "total_coliform": "total coliform",
    "conductivity": "conductivity",
    "sar": "sodium adsorption ratio (not stored)",
    "boron": "boron (not stored)",
    "ammonia_free": "free ammonia (only total NH3-N is stored)",
}

_CLASS_D_NOTE = (
    "Class D is approximate on this data: the file stores total NH3-N, not free "
    "ammonia (free ammonia is a fraction of the total, so total <= 1.2 proves the "
    "criterion)."
)


def _check(record: Dict[str, Any], param: str, op: str, *limits: float) -> Optional[bool]:
    """True/False when checkable, None when the parameter is missing or unprovable."""
    if param == "ammonia_free":
        value = record.get("ammonia")
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        return True if float(value) <= limits[0] else None

    value = record.get(param)
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None

    value = float(value)
    if op == "range":
        return limits[0] <= value <= limits[1]
    if op == "min":
        return value >= limits[0]
    if op == "max":
        return value <= limits[0]
    raise ValueError(f"unknown criterion op: {op}")


def classify_sample(record: Dict[str, Any]) -> Dict[str, Any]:
    """Return the CPCB designated best-use class for one sample record."""
    any_failure = False
    for entry in CPCB_USE_CLASSES:
        missing: List[str] = []
        failed = False
        for param, op, *limits in entry["criteria"]:
            result = _check(record, param, op, *limits)
            if result is None:
                missing.append(_PARAM_LABELS.get(param, param))
            elif result is False:
                failed = True
                break

        if failed:
            any_failure = True
            continue

        if len(missing) == len(entry["criteria"]):
            # Nothing about this class is checkable on the sample; do not
            # claim it, try the next class instead.
            continue

        result: Dict[str, Any] = {
            "class": entry["class"],
            "label": entry["label"],
            "partial": bool(missing),
            "missing": missing,
            "approximate": entry["class"] == "D",
        }
        if entry["class"] == "D":
            result["note"] = _CLASS_D_NOTE
        return result

    if not any_failure:
        return {
            "class": None,
            "label": "Not classifiable: no relevant parameters present",
            "partial": True,
            "missing": [],
            "approximate": False,
        }

    return {
        "class": "Below E",
        "label": "Meets none of the checkable A-E criteria",
        "partial": False,
        "missing": [],
        "approximate": False,
    }
