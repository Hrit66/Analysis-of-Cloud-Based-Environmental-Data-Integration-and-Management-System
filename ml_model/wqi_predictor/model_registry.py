"""
wqi_predictor/model_registry.py
================================
Model registry manager for WQI predictor artifacts.
"""

from __future__ import annotations

import glob
import json
import logging
import re
from pathlib import Path
from typing import Optional, Union

import joblib

logger = logging.getLogger(__name__)

_DEFAULT_REGISTRY_DIR = Path(__file__).resolve().parent.parent / "models" / "wqi_predictor"
_ARTIFACT_PREFIX = "xgb_wqi"


def _parse_version(filename: str, prefix: str = _ARTIFACT_PREFIX) -> Optional[tuple[int, int, int]]:
    pattern = rf"{prefix}_v(\d+)\.(\d+)\.(\d+)\.joblib$"
    match = re.search(pattern, Path(filename).name)
    if match:
        return int(match.group(1)), int(match.group(2)), int(match.group(3))
    return None


def get_next_version(registry_dir: Union[str, Path] = _DEFAULT_REGISTRY_DIR, prefix: str = _ARTIFACT_PREFIX) -> str:
    registry_dir = Path(registry_dir)
    pattern = str(registry_dir / f"{prefix}_v*.joblib")
    files = glob.glob(pattern)
    versions = [_parse_version(f, prefix) for f in files]
    valid_versions = [v for v in versions if v is not None]
    if not valid_versions:
        return "1.0.0"
    latest = max(valid_versions)
    return f"{latest[0]}.{latest[1]}.{latest[2] + 1}"


def save_model(
    model: dict,
    metadata: dict,
    registry_dir: Union[str, Path] = _DEFAULT_REGISTRY_DIR,
    prefix: str = _ARTIFACT_PREFIX,
    version: Optional[str] = None,
) -> dict[str, str]:
    registry_dir = Path(registry_dir)
    registry_dir.mkdir(parents=True, exist_ok=True)

    if version is None:
        version = get_next_version(registry_dir, prefix)

    metadata["version"] = version
    model_filename = f"{prefix}_v{version}.joblib"
    meta_filename = f"{prefix}_v{version}_meta.json"

    model_path = registry_dir / model_filename
    meta_path = registry_dir / meta_filename

    joblib.dump(model, model_path)
    logger.info("Model saved -> %s", model_path)

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, default=str)
    logger.info("Metadata saved -> %s", meta_path)

    return {"model_path": str(model_path), "meta_path": str(meta_path)}


def load_latest_model(
    registry_dir: Union[str, Path] = _DEFAULT_REGISTRY_DIR,
    prefix: str = _ARTIFACT_PREFIX,
) -> tuple[dict, dict]:
    registry_dir = Path(registry_dir)
    pattern = str(registry_dir / f"{prefix}_v*.joblib")
    files = glob.glob(pattern)

    versioned = []
    for f in files:
        v = _parse_version(f, prefix)
        if v:
            versioned.append((v, f))

    if not versioned:
        raise FileNotFoundError(f"No model artifacts matching '{prefix}_v*.joblib' in {registry_dir}")

    versioned.sort(key=lambda x: x[0])
    latest_model_path = Path(versioned[-1][1])
    meta_path = latest_model_path.with_name(latest_model_path.name.replace(".joblib", "_meta.json"))

    model = joblib.load(latest_model_path)
    metadata = {}
    if meta_path.exists():
        with open(meta_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

    return model, metadata
