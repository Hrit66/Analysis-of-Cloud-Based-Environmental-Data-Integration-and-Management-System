"""Weighted Arithmetic Water Quality Index (WQI) - core headline + extended.

Method reference
----------------
CPCB weighted arithmetic index. Limits come from BIS IS:10500-2012
(drinking water) for the dissolved parameters and from the CPCB
designated-best-use classes B/C for BOD and DO. Lower is better.

Headline (core) index
---------------------
The headline index is scored on a FIXED core set - pH, DO, BOD - so that
every scored sample is comparable. Parameter availability in these files
changes over time (turbidity and nitrate exist only in the 2020 rows), and
an index that renormalises over whatever is present would step with the
file's schema, not with the water. A sample is scored only when ALL THREE
core parameters are present; otherwise its index is None.

Formula (for each core parameter i):

    Qi = 100 * (Vi - Vid) / (Si - Vid)

with the two documented deviations:

  * DO is reversed:  Qi = 100 * (Vid - Vi) / (Vid - Si)
  * pH uses the ABSOLUTE deviation from the ideal:
    Qi = 100 * |Vi - 7.0| / (8.5 - 7.0), so pH 6.5 and pH 7.5 both
    score 33.33. Deviation below the ideal is penalised exactly like
    deviation above it; the plain signed formula would REWARD acidic
    water (pH 6.5 scoring -33.33, better than neutral).

    Wi = K / Si,  with K = 1 / sum(1 / Sj over the 12-parameter set)
    WQI = sum(Qi * Wi) / sum(Wi over the scored parameters)

K is constant and cancels in the ratio, so the score only depends on the
limits: WQI = sum(Qi / Si) / sum(1 / Si).

- ``Vi`` measured value, ``Si`` standard limit, ``Vid`` ideal value
  (7.0 for pH, 14.6 for DO saturation, 0 for the rest).
- Sub-indices are clamped to 0..200: capped above at 200 and floored at 0
  (DO measured above its 14.6 saturation ideal no longer yields a negative
  sub-index that would improve the score).
- The final score is additionally floored at 0 (the scale is 0-200).
- Missing parameters null the score (no renormalisation on the headline).

Core limits (Si / Vid): ph 8.5 / 7.0 (BIS), do 5.0 / 14.6 (CPCB class B/C,
ideal is the WQI saturation convention), bod 3.0 / 0 (CPCB classes B/C;
BIS has no BOD limit).

Extended index (reported separately, labelled with its parameter count)
-----------------------------------------------------------------------
When extra parameters exist, a second index scores EVERY present parameter
over the full 12-parameter limit set. It requires at least 3 present
parameters including DO or BOD, otherwise it is None. It is identified by
its parameter count and is NOT comparable between samples with different
parameter sets - never use it for trends.

Extended limits (Si / Vid):
    ph 8.5 / 7.0 (BIS)                | turbidity 5 (NTU, BIS)
    tds 500 | hardness 300 | chlorides 250 | sulfates 200 |
    nitrates 45 (as NO3) | fluorides 1.0 | iron 0.3 | manganese 0.1
    do 5.0 / 14.6 (CPCB class B/C)    | bod 3.0 (CPCB classes B/C)

Nitrate units: the source files report nitrate as N (``no3_n``). The
import converts nitrate-N to nitrate (x 4.4266) so the BIS 45 mg/L limit -
which is defined for nitrate as NO3 - applies correctly.

Deliberately excluded
---------------------
- total coliform / fecal coliform: BIS IS:10500 sets the limit at
  "shall not be detectable" (0), so the ratio Qi = 100*(Vi-0)/(0-0) is
  undefined; MPN counts also span up to ~9.2e9 which would swamp every
  other parameter. The dashboard shows a separate bacteriological flag
  against the CPCB class limits instead (Class A 50, Class B 500, Class C
  5,000 MPN/100 mL).
- ammonia, conductivity: no BIS IS:10500 limit used by this method.
  Stored with the data but not scored. Repeated low ammonia values
  (e.g. 0.40 mg/L) are kept exactly as measured, not converted to a
  below-detection value.

Categories (score band, lower is better)
----------------------------------------
    0-25 Excellent | 25-50 Good | 50-75 Poor | 75-100 Very Poor |
    >100 Unsuitable (>100)      (75 itself is "Very Poor")

Golden values (core set, verifiable against the live dashboard)
---------------------------------------------------------------
    ph 7.1, do 5.7, bod 5  -> 115.03   (Ibbalur Lake, 6 Dec 2021)
    ph 6.9, do 2.0, bod 16 -> 143.94   (Ibbalur Lake, 19 May 2021)
    ph 7.1, do 6.2, bod 4  -> 96.36    (Ibbalur Lake, 30 Dec 2020;
                                        extended index: see below)
    ph 8.0, do 6.4, bod 4  -> 106.56   (Allasandra, 8 Dec 2021)
    ph only (7.1)          -> None     (minimum-parameter rule)
    do 15 (rest unchanged) -> Q_do = 0 (clamped, no negative DO sub-index)

The 30 Dec 2020 Ibbalur sample additionally carries turbidity 6.6 NTU and
nitrate-N 1.3 mg/L; its extended index (5 parameters) is reported
separately and is not part of the headline series or its window mean.
"""

import math
from typing import Dict, List, Optional, Sequence, Tuple

from app.services import dataset_config
from app.services.cpcb_classes import classify_sample

# BIS IS:10500-2012 / CPCB limits used by the extended index. The live table
# lives in dataset_config so tests/users can override it; this alias is kept
# for backwards-compatible imports.
WQI_PARAMS: Dict[str, Dict[str, float]] = dataset_config.wqi_params()


# The headline index is always scored on exactly these three parameters.
CORE_PARAMS: Tuple[str, ...] = dataset_config.wqi_core()

# The extended index needs at least this many parameters, and at least one
# of DO / BOD (a score without any oxygen-demand information is meaningless).
MIN_EXTENDED_PARAMS = dataset_config.WQI["min_extended_params"]
REQUIRED_EXTENDED_ANY = dataset_config.WQI["required_extended_any"]

WQI_CATEGORIES = [
    (0, 25, "Excellent"),
    (25, 50, "Good"),
    (50, 75, "Poor"),
    (75, 100, "Very Poor"),
    (100, 999999, "Unsuitable (>100)"),
]

K_CONST = 1.0 / sum(1.0 / p["Si"] for p in WQI_PARAMS.values())


def _is_missing(value) -> bool:
    if value is None:
        return True
    try:
        return math.isnan(float(value))
    except (TypeError, ValueError):
        return True


def _sub_index(param: str, stds: Dict[str, float], value) -> float:
    """Qi for one parameter, clamped to 0..config.WQI["sub_index_max"]."""
    val = float(value)
    si, vid = stds["Si"], stds["Vid"]

    if param == "do":
        qi = 100.0 * (vid - val) / (vid - si) if (vid - si) != 0 else 0.0
    elif param == "ph":
        qi = 100.0 * abs(val - vid) / (si - vid) if (si - vid) != 0 else 0.0
    else:
        qi = 100.0 * (val - vid) / (si - vid) if (si - vid) != 0 else 0.0

    return max(0.0, min(qi, float(dataset_config.WQI["sub_index_max"])))


def _category(score: float) -> str:
    for lo, hi, name in WQI_CATEGORIES:
        if lo <= score < hi:
            return name
    return "Unsuitable (>100)"


def _score(parameter_values: Dict[str, Optional[float]], params: Sequence[str]):
    """Score exactly the given parameters; None unless every one is present."""
    limits = dataset_config.wqi_params()
    weighted_sum = 0.0
    weight_total = 0.0
    sub_indices: Dict[str, float] = {}

    for param in params:
        value = parameter_values.get(param)
        if _is_missing(value):
            return None, None, {}
        if param not in limits:
            return None, None, {}

        qi = _sub_index(param, limits[param], value)
        wi = 1.0 / limits[param]["Si"]

        weighted_sum += qi * wi
        weight_total += wi
        sub_indices[param] = round(qi, 2)

    if weight_total <= 0:
        return None, None, {}

    score = max(0.0, round(weighted_sum / weight_total, 2))
    return score, _category(score), sub_indices


def calculate_wqi(parameter_values: Dict[str, Optional[float]]) -> Tuple[Optional[float], Optional[str], Dict[str, float]]:
    """Headline core-set index (pH, DO, BOD). None when any core value is missing."""
    return _score(parameter_values, dataset_config.wqi_core())


def calculate_extended_wqi(parameter_values: Dict[str, Optional[float]]) -> Tuple[Optional[float], Optional[str], Dict[str, float]]:
    """Extended index over all present parameters, at least 3 incl. DO or BOD."""
    limits = dataset_config.wqi_params()
    present = [p for p in limits if not _is_missing(parameter_values.get(p))]
    min_params = int(dataset_config.WQI["min_extended_params"])
    required_any = tuple(dataset_config.WQI["required_extended_any"])
    if len(present) < min_params or not any(p in present for p in required_any):
        return None, None, {}

    return _score(parameter_values, present)


def compute_wqi_for_record(record: dict) -> dict:
    parameter_values = {param: record.get(param) for param in dataset_config.wqi_params()}
    score, category, sub_indices = calculate_wqi(parameter_values)
    ext_score, ext_category, ext_sub_indices = calculate_extended_wqi(parameter_values)

    return {
        "wqi": score,
        "wqi_category": category,
        "sub_indices": sub_indices,
        "extended_wqi": ext_score,
        "extended_wqi_category": ext_category,
        "extended_param_count": len(ext_sub_indices) if ext_score is not None else None,
        "extended_sub_indices": ext_sub_indices,
        "cpcb_use_class": classify_sample(record),
    }


MIN_SAMPLES_FOR_RANK = 3


def add_station_ranks(results: List[dict], min_samples: int = MIN_SAMPLES_FOR_RANK) -> List[dict]:
    """Add rank_pct / rank_of / rank_samples to per-station summary rows.

    Stations are ranked on their mean WQI over the window against stations with
    at least min_samples scored samples; a rank is never returned without its
    sample count (rank_samples), and ties are not counted as better. Single
    station pools and under-sampled stations get None.
    """
    ranked = [
        r for r in results
        if (r.get("scored_count") or 0) >= min_samples and r.get("avg_wqi") is not None
    ]
    ranked_locs = {r["location"] for r in ranked}
    pool_size = len(ranked)

    for r in results:
        r["rank_pct"] = None
        r["rank_of"] = None
        r["rank_samples"] = None
        if r["location"] not in ranked_locs or pool_size < 2:
            continue
        better = sum(
            1 for other in ranked
            if other["location"] != r["location"] and other["avg_wqi"] < r["avg_wqi"]
        )
        r["rank_pct"] = round(100 * better / (pool_size - 1))
        r["rank_of"] = pool_size
        r["rank_samples"] = r["scored_count"]

    return results
