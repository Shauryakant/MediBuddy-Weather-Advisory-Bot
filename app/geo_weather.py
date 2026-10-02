"""
geo_weather.py: Open-Meteo geocoding, forecast data fetcher, and time-window metric aggregator.
Uses httpx with timeouts and retries.
"""
from typing import Dict, Any, Optional, Set, List
import httpx
import logging
from datetime import datetime, timezone, timedelta
from app.config import load_time_windows

logger = logging.getLogger(__name__)

GEOCODING_API_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_API_URL = "https://api.open-meteo.com/v1/forecast"


def geocode_location(location_text: str, base_url: str = GEOCODING_API_URL) -> Optional[Dict[str, Any]]:
    """
    Geocodes a location text using Open-Meteo Geocoding API.
    Returns dict with name, latitude, longitude, admin1, country or None on failure/empty.
    """
    if not location_text or not location_text.strip():
        return None

    params = {
        "name": location_text.strip(),
        "count": 1,
        "language": "en",
        "format": "json"
    }

    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(base_url, params=params)
            # 1 retry if status not ok
            if resp.status_code != 200:
                resp = client.get(base_url, params=params)

            if resp.status_code != 200:
                logger.error(f"Geocoding HTTP error {resp.status_code} for {location_text}")
                return None

            data = resp.json()
            results = data.get("results")
            if not results or len(results) == 0:
                logger.info(f"No geocoding results found for '{location_text}'")
                return None

            first = results[0]
            return {
                "name": first.get("name", location_text),
                "latitude": float(first.get("latitude")),
                "longitude": float(first.get("longitude")),
                "admin1": first.get("admin1", ""),
                "country": first.get("country", ""),
                "display_name": f"{first.get('name')}, {first.get('admin1', '')}, {first.get('country', '')}".strip(", ")
            }
    except Exception as e:
        logger.error(f"Geocoding exception for '{location_text}': {e}")
        return None


def fetch_weather(
    latitude: float,
    longitude: float,
    metrics: Set[str],
    base_url: str = FORECAST_API_URL
) -> Optional[Dict[str, Any]]:
    """
    Fetches forecast data from Open-Meteo for the requested metrics set.
    Returns raw JSON dictionary or None on error.
    """
    if not metrics:
        metrics = {"temperature_2m", "apparent_temperature", "wind_speed_10m", "precipitation"}

    # Standardize field names for Open-Meteo
    hourly_fields = sorted(list(metrics))
    current_fields = [m for m in ["temperature_2m", "apparent_temperature", "wind_speed_10m", "precipitation", "weather_code"] if m in metrics]
    if not current_fields:
        current_fields = ["temperature_2m", "wind_speed_10m", "precipitation"]

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": ",".join(hourly_fields),
        "current": ",".join(current_fields),
        "wind_speed_unit": "kmh",
        "timezone": "auto"
    }

    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(base_url, params=params)
            if resp.status_code != 200:
                # 1 retry
                resp = client.get(base_url, params=params)

            if resp.status_code != 200:
                logger.error(f"Weather API HTTP error {resp.status_code}")
                return None

            return resp.json()
    except Exception as e:
        logger.error(f"Weather API exception: {e}")
        return None


def aggregate_metrics(
    weather_data: Dict[str, Any],
    time_ref: Optional[str] = "today",
    required_metrics: Optional[Set[str]] = None
) -> Dict[str, Any]:
    """
    Aggregates hourly weather metrics into windowed values (value, max, min, sum, mean, delta).
    Returns dictionary mapping 'metric.agg.window' -> numeric value or None.
    """
    if not weather_data or "hourly" not in weather_data:
        return {}

    hourly = weather_data.get("hourly", {})
    times = hourly.get("time", [])
    if not times:
        return {}

    windows_config = load_time_windows()
    current_data = weather_data.get("current", {})

    # Determine reference index in hourly data
    ref_index = 0
    if "time" in current_data:
        curr_time_str = current_data["time"]
        for idx, t_str in enumerate(times):
            if t_str >= curr_time_str:
                ref_index = idx
                break

    aggregated: Dict[str, Any] = {}

    # Current values
    for m, val in current_data.items():
        if m != "time":
            aggregated[f"{m}.value.now"] = val
            aggregated[f"{m}.max.now"] = val
            aggregated[f"{m}.min.now"] = val
            aggregated[f"{m}.sum.now"] = val
            aggregated[f"{m}.mean.now"] = val
            aggregated[f"{m}.delta.now"] = 0.0

    # Process each metric and window
    available_hourly_metrics = [k for k in hourly.keys() if k != "time"]

    for window_name, win_info in windows_config.items():
        start_offset = win_info.get("start_hour", 0)
        end_offset = win_info.get("end_hour", 24)

        s_idx = max(0, ref_index + start_offset)
        e_idx = min(len(times), ref_index + end_offset)

        if s_idx >= len(times) or s_idx >= e_idx:
            # Fallback to full available slice
            s_idx = 0
            e_idx = min(24, len(times))

        for metric in available_hourly_metrics:
            series = hourly[metric][s_idx:e_idx]
            valid_vals = [v for v in series if v is not None]

            key_base = f"{metric}"

            if not valid_vals:
                aggregated[f"{key_base}.value.{window_name}"] = None
                aggregated[f"{key_base}.max.{window_name}"] = None
                aggregated[f"{key_base}.min.{window_name}"] = None
                aggregated[f"{key_base}.sum.{window_name}"] = None
                aggregated[f"{key_base}.mean.{window_name}"] = None
                aggregated[f"{key_base}.delta.{window_name}"] = None
            else:
                aggregated[f"{key_base}.value.{window_name}"] = valid_vals[0]
                aggregated[f"{key_base}.max.{window_name}"] = round(max(valid_vals), 2)
                aggregated[f"{key_base}.min.{window_name}"] = round(min(valid_vals), 2)
                aggregated[f"{key_base}.sum.{window_name}"] = round(sum(valid_vals), 2)
                aggregated[f"{key_base}.mean.{window_name}"] = round(sum(valid_vals) / len(valid_vals), 2)
                aggregated[f"{key_base}.delta.{window_name}"] = round(valid_vals[-1] - valid_vals[0], 2)

    return aggregated
