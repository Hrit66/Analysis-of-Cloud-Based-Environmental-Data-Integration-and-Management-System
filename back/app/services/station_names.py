"""Conservative, data-driven station-name merge suggestions.

The display cleaner can fix obvious typos, but merging two station rows is a
data decision: it must be proposed, not silently applied. This module compares
normalized names and only suggests pairs that are nearly identical. Names that
share a river but name different places ("Netravathi at Thumbe" vs "Netravathi
U/S of Dharmastala") are deliberately kept apart.

No station list is hardcoded: the suggestions work on any set of names.
"""
import difflib
import re
from collections import Counter
from typing import Dict, Iterable, List, Optional

from app.services import dataset_config

_GENERIC_TOKENS = {
    "at", "of", "the", "near", "on", "in", "and", "u", "s", "d", "us", "ds",
    "upstream", "downstream",
}
_NUMBER_RE = re.compile(r"^\d+$")


def normalize_station(name: str) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", str(name).lower())
    tokens = [token for token in text.split() if token]
    return " ".join(tokens)


def _tokens(name: str) -> List[str]:
    return [token for token in normalize_station(name).split() if token]


def _distinctive(tokens: List[str]) -> List[str]:
    return [token for token in tokens if token not in _GENERIC_TOKENS]


def _number_signature(tokens: List[str]) -> tuple:
    return tuple(sorted(token for token in tokens if _NUMBER_RE.match(token)))


def _similarity(left: str, right: str) -> tuple:
    left_tokens, right_tokens = _tokens(left), _tokens(right)
    left_distinct, right_distinct = _distinctive(left_tokens), _distinctive(right_tokens)
    if not left_distinct or not right_distinct:
        return 0.0, 0.0
    if _number_signature(left_tokens) != _number_signature(right_tokens):
        return 0.0, 0.0
    ratio = difflib.SequenceMatcher(
        None, normalize_station(left), normalize_station(right)
    ).ratio()
    shared = set(left_distinct) & set(right_distinct)
    union = set(left_distinct) | set(right_distinct)
    jaccard = len(shared) / len(union) if union else 0.0
    return ratio, jaccard


def suggest_station_merges(
    locations: Iterable,
    threshold: Optional[float] = None,
    min_token_overlap: Optional[float] = None,
    max_suggestions: Optional[int] = None,
) -> List[Dict[str, object]]:
    """Return groups of near-identical station names as suggestions only."""
    config = dataset_config.STATION_MATCH
    threshold = float(config["similarity_threshold"] if threshold is None else threshold)
    min_overlap = float(
        config["min_token_overlap"] if min_token_overlap is None else min_token_overlap
    )
    limit = int(config["max_suggestions"] if max_suggestions is None else max_suggestions)

    names = sorted({str(name).strip() for name in locations if str(name).strip()})
    parent = {name: name for name in names}

    def find(name: str) -> str:
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    def union(left: str, right: str) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    pairs: List[Dict[str, object]] = []
    for index, left in enumerate(names):
        for right in names[index + 1:]:
            ratio, jaccard = _similarity(left, right)
            if ratio >= threshold or (jaccard >= min_overlap and ratio >= 0.75):
                union(left, right)
                pairs.append({
                    "left": left,
                    "right": right,
                    "similarity": round(ratio, 3),
                    "token_overlap": round(jaccard, 3),
                })

    groups: Dict[str, List[str]] = {}
    for name in names:
        groups.setdefault(find(name), []).append(name)

    suggestions: List[Dict[str, object]] = []
    pair_lookup = {
        frozenset((pair["left"], pair["right"])): pair for pair in pairs
    }
    for variants in groups.values():
        if len(variants) < 2:
            continue
        counts = Counter(variants)
        canonical = min(
            variants,
            key=lambda value: (-counts[value], len(normalize_station(value)), value),
        )
        similarity = max(
            (
                pair_lookup[frozenset((left, right))]["similarity"]
                for left in variants for right in variants
                if left != right and frozenset((left, right)) in pair_lookup
            ),
            default=0.0,
        )
        suggestions.append({
            "suggested_name": canonical,
            "variants": sorted(variants),
            "count": sum(counts.values()),
            "similarity": similarity,
            "action": "confirm to merge; nothing has been changed",
        })

    suggestions.sort(key=lambda item: (-item["count"], item["suggested_name"]))
    return suggestions[:limit]
