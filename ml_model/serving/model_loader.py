"""
serving/model_loader.py
=======================
Secure, self-contained model fetching and in-memory caching layer.

Architecture
------------
This module is the ONLY place that talks to cloud storage (S3 / GCS).
The backend container needs NO AWS or GCS credentials – it simply calls
the inference functions in serving/inference.py which delegate loading here.

Cloud Storage Strategy
----------------------
The module supports three backends, resolved in this priority order:

  1. LOCAL_OVERRIDE environment variable  → load directly from local disk.
     (used in development / unit tests)
  2. AWS S3  → if CLOUD_PROVIDER=s3 (default) or CLOUD_PROVIDER unset.
     Credentials: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY (or IAM role).
  3. GCS     → if CLOUD_PROVIDER=gcs.
     Credentials: GOOGLE_APPLICATION_CREDENTIALS path (or Workload Identity).

Pre-signed URL Support
----------------------
If S3_PRESIGNED_URL_{ARTIFACT_KEY} or GCS_PRESIGNED_URL_{ARTIFACT_KEY} env
vars are set, the file is fetched via plain HTTPS (no SDK credentials needed
in the backend container).  This is the recommended production pattern.

In-Memory Cache
---------------
Models are loaded once and stored in ``_MODEL_CACHE``.  Subsequent calls
return the cached object instantly (zero network I/O).

Environment Variables
---------------------
CLOUD_PROVIDER           : "s3" | "gcs" | "local"  (default: "local")
CLOUD_BUCKET             : S3 bucket name or GCS bucket name
CLOUD_PREFIX             : Key prefix inside the bucket (e.g. "ml_model/")
LOCAL_MODEL_DIR          : Override path for local model artefacts
S3_REGION                : AWS region (default: "ap-south-1" for India)
S3_PRESIGNED_URL_ANOMALY : Pre-signed URL for anomaly model .joblib
S3_PRESIGNED_URL_FORECAST: Pre-signed URL for forecast model .joblib
S3_PRESIGNED_URL_AQI     : Pre-signed URL for AQI predictor model .joblib
GCS_PRESIGNED_URL_ANOMALY: Same but for GCS
GCS_PRESIGNED_URL_FORECAST:
GCS_PRESIGNED_URL_AQI    :
"""

from __future__ import annotations

import io
import logging
import os
import threading
from pathlib import Path
from typing import Any, Optional

import joblib

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory cache (thread-safe)
# ---------------------------------------------------------------------------

_MODEL_CACHE: dict[str, Any] = {}
_CACHE_LOCK = threading.Lock()

_ML_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Artifact key → default local path mapping
# ---------------------------------------------------------------------------

_DEFAULT_LOCAL_PATHS: dict[str, str] = {
    "anomaly":   "models/anomaly",
    "forecast":  "models/forecast",
    "aqi":       "models/aqi_predictor",
    "wqi":       "models/wqi_predictor",
}

_DEFAULT_PREFIXES: dict[str, str] = {
    "anomaly":   "isolation_forest",
    "forecast":  "xgb_forecast",
    "aqi":       "xgb_aqi",
    "wqi":       "xgb_wqi",
}


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------

def load(artifact_key: str, version: Optional[str] = None, force_reload: bool = False) -> Any:
    """Load a model pipeline from cache, local disk, or cloud storage.

    Parameters
    ----------
    artifact_key : One of "anomaly", "forecast", "aqi".
    version      : Specific version string (None = latest).
    force_reload : Bypass cache and re-fetch.

    Returns
    -------
    The loaded pipeline dict (scaler + model + feature_cols, etc.)
    """
    cache_key = f"{artifact_key}:{version or 'latest'}"

    if not force_reload:
        with _CACHE_LOCK:
            if cache_key in _MODEL_CACHE:
                logger.debug("Cache hit for '%s'.", cache_key)
                return _MODEL_CACHE[cache_key]

    pipeline = _fetch(artifact_key, version)

    with _CACHE_LOCK:
        _MODEL_CACHE[cache_key] = pipeline
    logger.info("Model '%s' loaded and cached.", cache_key)
    return pipeline


def evict(artifact_key: Optional[str] = None) -> None:
    """Remove one or all entries from the in-memory cache."""
    with _CACHE_LOCK:
        if artifact_key is None:
            _MODEL_CACHE.clear()
            logger.info("Model cache cleared.")
        else:
            keys = [k for k in _MODEL_CACHE if k.startswith(f"{artifact_key}:")]
            for k in keys:
                del _MODEL_CACHE[k]
            logger.info("Evicted %d cache entries for '%s'.", len(keys), artifact_key)


# ---------------------------------------------------------------------------
# Internal fetch logic
# ---------------------------------------------------------------------------

def _fetch(artifact_key: str, version: Optional[str]) -> Any:
    """Resolve fetch strategy and return the loaded pipeline."""
    provider = os.environ.get("CLOUD_PROVIDER", "local").lower()

    # 1. Pre-signed URL (no credentials in backend – most secure)
    presigned = _get_presigned_url(artifact_key, provider)
    if presigned:
        logger.info("Fetching '%s' via pre-signed URL.", artifact_key)
        return _fetch_presigned(presigned)

    # 2. Local override / local provider
    if provider == "local" or os.environ.get("LOCAL_MODEL_DIR"):
        return _fetch_local(artifact_key, version)

    # 3. S3
    if provider == "s3":
        return _fetch_s3(artifact_key, version)

    # 4. GCS
    if provider == "gcs":
        return _fetch_gcs(artifact_key, version)

    raise ValueError(f"Unknown CLOUD_PROVIDER: '{provider}'")


# ---------------------------------------------------------------------------
# Pre-signed URL fetch
# ---------------------------------------------------------------------------

def _get_presigned_url(artifact_key: str, provider: str) -> Optional[str]:
    key_upper = artifact_key.upper()
    provider_upper = provider.upper() if provider != "local" else "S3"
    env_var = f"{provider_upper}_PRESIGNED_URL_{key_upper}"
    return os.environ.get(env_var)


def _fetch_presigned(url: str) -> Any:
    """Download a joblib artifact from a pre-signed URL (no cloud credentials needed)."""
    import urllib.request
    logger.info("Downloading model from pre-signed URL…")
    with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310
        data = response.read()
    return joblib.load(io.BytesIO(data))


# ---------------------------------------------------------------------------
# Local file-system fetch
# ---------------------------------------------------------------------------

def _fetch_local(artifact_key: str, version: Optional[str]) -> Any:
    """Load the latest (or versioned) .joblib from the local models/ directory."""
    import glob
    import re

    local_dir_override = os.environ.get("LOCAL_MODEL_DIR")
    if local_dir_override:
        base_dir = Path(local_dir_override) / artifact_key
    else:
        base_dir = _ML_ROOT / _DEFAULT_LOCAL_PATHS[artifact_key]

    prefix = _DEFAULT_PREFIXES[artifact_key]

    if version:
        model_path = base_dir / f"{prefix}_v{version}.joblib"
        if not model_path.exists():
            raise FileNotFoundError(f"Model not found: {model_path}")
    else:
        # Find latest version
        pattern = str(base_dir / f"{prefix}_v*.joblib")
        files = sorted(glob.glob(pattern))
        if not files:
            raise FileNotFoundError(
                f"No local model artefacts found in {base_dir} "
                f"(pattern: {prefix}_v*.joblib). "
                "Run the corresponding train.py script first."
            )

        def _version_key(p: str) -> tuple[int, ...]:
            m = re.search(r"_v([\d.]+)\.joblib$", p)
            return tuple(int(x) for x in m.group(1).split(".")) if m else (0,)

        model_path = Path(max(files, key=_version_key))

    logger.info("Loading local model: %s", model_path)
    return joblib.load(model_path)


# ---------------------------------------------------------------------------
# AWS S3 fetch
# ---------------------------------------------------------------------------

def _fetch_s3(artifact_key: str, version: Optional[str]) -> Any:
    """Download .joblib from S3, deserialise in-memory (no disk write)."""
    try:
        import boto3  # type: ignore
    except ImportError:
        raise ImportError("boto3 is required for S3 fetching: pip install boto3")

    bucket = os.environ.get("CLOUD_BUCKET", "")
    prefix = os.environ.get("CLOUD_PREFIX", "ml_model/")
    region = os.environ.get("S3_REGION", "ap-south-1")
    artifact_prefix = _DEFAULT_PREFIXES[artifact_key]

    if not bucket:
        raise ValueError("CLOUD_BUCKET env var is required for S3 fetching.")

    s3 = boto3.client("s3", region_name=region)

    if version:
        key = f"{prefix}{artifact_key}/{artifact_prefix}_v{version}.joblib"
    else:
        # List objects and find the latest version
        resp = s3.list_objects_v2(Bucket=bucket, Prefix=f"{prefix}{artifact_key}/{artifact_prefix}_v")
        objects = resp.get("Contents", [])
        if not objects:
            raise FileNotFoundError(f"No S3 objects found under s3://{bucket}/{prefix}{artifact_key}/")

        import re
        def _vkey(obj: dict) -> tuple[int, ...]:
            m = re.search(r"_v([\d.]+)\.joblib$", obj["Key"])
            return tuple(int(x) for x in m.group(1).split(".")) if m else (0,)

        latest_obj = max(objects, key=_vkey)
        key = latest_obj["Key"]

    logger.info("Fetching s3://%s/%s", bucket, key)
    buf = io.BytesIO()
    s3.download_fileobj(bucket, key, buf)
    buf.seek(0)
    return joblib.load(buf)


# ---------------------------------------------------------------------------
# Google Cloud Storage fetch
# ---------------------------------------------------------------------------

def _fetch_gcs(artifact_key: str, version: Optional[str]) -> Any:
    """Download .joblib from GCS, deserialise in-memory (no disk write)."""
    try:
        from google.cloud import storage as gcs_storage  # type: ignore
    except ImportError:
        raise ImportError(
            "google-cloud-storage is required for GCS fetching: "
            "pip install google-cloud-storage"
        )

    bucket_name = os.environ.get("CLOUD_BUCKET", "")
    prefix = os.environ.get("CLOUD_PREFIX", "ml_model/")
    artifact_prefix = _DEFAULT_PREFIXES[artifact_key]

    if not bucket_name:
        raise ValueError("CLOUD_BUCKET env var is required for GCS fetching.")

    client = gcs_storage.Client()
    bucket = client.bucket(bucket_name)

    if version:
        blob_name = f"{prefix}{artifact_key}/{artifact_prefix}_v{version}.joblib"
        blob = bucket.blob(blob_name)
    else:
        import re
        blobs = list(client.list_blobs(bucket_name, prefix=f"{prefix}{artifact_key}/{artifact_prefix}_v"))
        if not blobs:
            raise FileNotFoundError(f"No GCS objects found under gs://{bucket_name}/{prefix}{artifact_key}/")

        def _vkey(b: Any) -> tuple[int, ...]:
            m = re.search(r"_v([\d.]+)\.joblib$", b.name)
            return tuple(int(x) for x in m.group(1).split(".")) if m else (0,)

        blob = max(blobs, key=_vkey)

    logger.info("Fetching gs://%s/%s", bucket_name, blob.name)
    buf = io.BytesIO()
    blob.download_to_file(buf)
    buf.seek(0)
    return joblib.load(buf)
