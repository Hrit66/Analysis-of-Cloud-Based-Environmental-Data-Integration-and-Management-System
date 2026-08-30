"""
forecast/model_registry.py
==========================
Versioned model persistence for the XGBoost forecasting module.
Mirrors the anomaly registry pattern exactly.
"""

from __future__ import annotations

import glob
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import joblib

logger = logging.getLogger(__name__)

_ML_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_REGISTRY_DIR = _ML_ROOT / "models" / "forecast"


def save_model(
    model: Any,
    metadata: dict[str, Any],
    version: Optional[str] = None,
    prefix: str = "xgb_forecast",
    registry_dir: Optional[Path] = None,
) -> dict[str, str]:
    reg = Path(registry_dir) if registry_dir else _DEFAULT_REGISTRY_DIR
    reg.mkdir(parents=True, exist_ok=True)

    if version is None:
        version = _next_version(prefix, reg)

    model_path = reg / f"{prefix}_v{version}.joblib"
    meta_path = reg / f"{prefix}_v{version}_meta.json"

    joblib.dump(model, model_path, compress=3)
    logger.info("Model saved → %s", model_path)

    full_meta = {
        "name": prefix,
        "version": version,
        "saved_at": datetime.now(tz=timezone.utc).isoformat(),
        "model_path": str(model_path),
        **metadata,
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(full_meta, f, indent=2, default=str)
    logger.info("Metadata saved → %s", meta_path)

    return {"model_path": str(model_path), "meta_path": str(meta_path)}


def load_model(
    version: Optional[str] = None,
    prefix: str = "xgb_forecast",
    registry_dir: Optional[Path] = None,
) -> tuple[Any, dict[str, Any]]:
    reg = Path(registry_dir) if registry_dir else _DEFAULT_REGISTRY_DIR

    if version is None:
        version = latest_version(prefix, reg)
        if version is None:
            raise FileNotFoundError(f"No registered forecast models in {reg}.")

    model_path = reg / f"{prefix}_v{version}.joblib"
    meta_path = reg / f"{prefix}_v{version}_meta.json"

    model = joblib.load(model_path)
    metadata: dict[str, Any] = {}
    if meta_path.exists():
        with open(meta_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

    logger.info("Loaded forecast model v%s", version)
    return model, metadata


def latest_version(prefix: str = "xgb_forecast", registry_dir: Optional[Path] = None) -> Optional[str]:
    reg = Path(registry_dir) if registry_dir else _DEFAULT_REGISTRY_DIR
    pattern = str(reg / f"{prefix}_v*_meta.json")
    meta_files = glob.glob(pattern)
    if not meta_files:
        return None

    def _key(p: str) -> tuple[int, ...]:
        m = re.search(r"_v([\d.]+)_meta\.json$", p)
        return tuple(int(x) for x in m.group(1).split(".")) if m else (0,)

    latest = max(meta_files, key=_key)
    m = re.search(r"_v([\d.]+)_meta\.json$", latest)
    return m.group(1) if m else None


def _next_version(prefix: str, reg: Path) -> str:
    current = latest_version(prefix, reg)
    if current is None:
        return "1.0.0"
    parts = current.split(".")
    parts[-1] = str(int(parts[-1]) + 1)
    return ".".join(parts)


def list_versions(prefix: str = "xgb_forecast", registry_dir: Optional[Path] = None) -> list[dict]:
    reg = Path(registry_dir) if registry_dir else _DEFAULT_REGISTRY_DIR
    pattern = str(reg / f"{prefix}_v*_meta.json")
    versions = []
    for path in sorted(glob.glob(pattern)):
        with open(path, "r", encoding="utf-8") as f:
            versions.append(json.load(f))
    return versions
