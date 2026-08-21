import json
from typing import Dict, Optional
import urllib.request
import pandas as pd


def fetch_api_data(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 30,
) -> pd.DataFrame:
    """Fetch JSON data from a REST endpoint and return as a pandas DataFrame.

    This is a pure data retrieval helper that does not persist data to any database.

    Args:
        url (str): The HTTP/HTTPS endpoint URL.
        headers (Optional[Dict[str, str]]): HTTP headers to include in the request.
        timeout (int): Request timeout in seconds.

    Returns:
        pd.DataFrame: Loaded records as a DataFrame.

    Raises:
        ValueError: If URL is empty or invalid.
        RuntimeError: If the HTTP request fails.
    """
    if not url or not isinstance(url, str):
        raise ValueError("A valid URL string must be provided.")

    req_headers = headers or {"User-Agent": "EnvironmentalDataPipeline/1.0"}
    req = urllib.request.Request(url, headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        raise RuntimeError(f"Failed to fetch data from '{url}': {e}") from e

    if isinstance(payload, list):
        return pd.DataFrame(payload)
    elif isinstance(payload, dict):
        for key in ("data", "results", "records", "items"):
            if key in payload and isinstance(payload[key], list):
                return pd.DataFrame(payload[key])
        return pd.DataFrame([payload])
    else:
        raise ValueError(f"Unexpected JSON response type from '{url}': {type(payload).__name__}")
