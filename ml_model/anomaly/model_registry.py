"""
anomaly/model_registry.py
=========================
Versioned model persistence for the anomaly-detection module.

Each save produces two files:
  models/anomaly/<prefix>_v<version>.joblib  – the fitted sklearn model
  models/anomaly/<prefix>_v<version>_meta.json – metadata about the training run

``latest_version()`` reads all existing meta files and returns the highest
version number so that inference code can always resolve "latest".
"""

from __future__ import annotations

import glob
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import joblib

logger = logging.getLogger(__name__)

# Root of the ml_model package – models/ lives next to anomaly/
_ML_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_REGISTRY_DIR = _ML_ROOT / "models" / "anomaly"


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

def save_model(
    model: Any,
    metadata: dict[str, Any],
    version: Optional[str] = None,
    prefix: str = "isolation_forest",
    registry_dir: Optional[Path] = None,
) -> dict[str, str]:
    """Persist model artefact + metadata JSON to the registry directory.

    Parameters
    ----------
    model        : Fitted sklearn estimator.
    metadata     : Training metadata dict (hyperparams, metrics, dataset info…).
    version      : Explicit version string (e.g. "1.2.0").  If None, auto-increments.
    prefix       : Filename prefix (from config.yaml).
    registry_dir : Override the default registry path.

    Returns
    -------
    Dict with keys 'model_path' and 'meta_path'.
    """
    reg = Path(registry_dir) if registry_dir else _DEFAULT_REGISTRY_DIR
    reg.mkdir(parents=True, exist_ok=True)

    if version is None:
        version = _next_version(prefix, reg)

    timestamp = datetime.now(tz=timezone.utc).isoformat()

    model_filename = f"{prefix}_v{version}.joblib"
    meta_filename = f"{prefix}_v{version}_meta.json"

    model_path = reg / model_filename
    meta_path = reg / meta_filename

    # Persist model
    joblib.dump(model, model_path, compress=3)
    logger.info("Model saved → %s", model_path)

    # Persist metadata
    full_meta = {
        "name": prefix,
        "version": version,
        "saved_at": timestamp,
        "model_path": str(model_path),
        **metadata,
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(full_meta, f, indent=2, default=str)
    logger.info("Metadata saved → %s", meta_path)

    return {"model_path": str(model_path), "meta_path": str(meta_path)}


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load_model(
    version: Optional[str] = None,
    prefix: str = "isolation_forest",
    registry_dir: Optional[Path] = None,
) -> tuple[Any, dict[str, Any]]:
    """Load a versioned model + metadata from the local registry.

    If ``version`` is None, loads the latest registered version.

    Returns
    -------
    (model, metadata)
    """
    reg = Path(registry_dir) if registry_dir else _DEFAULT_REGISTRY_DIR

    if version is None:
        version = latest_version(prefix, reg)
        if version is None:
            raise FileNotFoundError(
                f"No registered models found in {reg} for prefix '{prefix}'."
            )

    model_path = reg / f"{prefix}_v{version}.joblib"
    meta_path = reg / f"{prefix}_v{version}_meta.json"

    if not model_path.exists():
        raise FileNotFoundError(f"Model artifact not found: {model_path}")

    model = joblib.load(model_path)
    metadata: dict[str, Any] = {}
    if meta_path.exists():
        with open(meta_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

    logger.info("Loaded model v%s from %s", version, model_path)
    return model, metadata


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------

def latest_version(
    prefix: str = "isolation_forest",
    registry_dir: Optional[Path] = None,
) -> Optional[str]:
    """Return the highest version string found in the registry, or None."""
    reg = Path(registry_dir) if registry_dir else _DEFAULT_REGISTRY_DIR
    pattern = str(reg / f"{prefix}_v*_meta.json")
    meta_files = glob.glob(pattern)

    if not meta_files:
        return None

    def _version_key(path: str) -> tuple[int, ...]:
        match = re.search(r"_v([\d.]+)_meta\.json$", path)
        if match:
            return tuple(int(x) for x in match.group(1).split("."))
        return (0,)

    latest = max(meta_files, key=_version_key)
    match = re.search(r"_v([\d.]+)_meta\.json$", latest)
    return match.group(1) if match else None


def _next_version(prefix: str, reg: Path) -> str:
    """Auto-increment patch version (e.g. 1.0.0 → 1.0.1)."""
    current = latest_version(prefix, reg)
    if current is None:
        return "1.0.0"
    parts = current.split(".")
    parts[-1] = str(int(parts[-1]) + 1)
    return ".".join(parts)


# ---------------------------------------------------------------------------
# List registry
# ---------------------------------------------------------------------------

def list_versions(
    prefix: str = "isolation_forest",
    registry_dir: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """Return a list of metadata dicts for all registered versions."""
    reg = Path(registry_dir) if registry_dir else _DEFAULT_REGISTRY_DIR
    pattern = str(reg / f"{prefix}_v*_meta.json")
    meta_files = sorted(glob.glob(pattern))
    versions = []
    for path in meta_files:
        with open(path, "r", encoding="utf-8") as f:
            versions.append(json.load(f))
    return versions
