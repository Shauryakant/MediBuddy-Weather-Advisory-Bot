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


def _query_open_meteo_geocode(query: str, base_url: str) -> Optional[Dict[str, Any]]:
    """Helper to issue a single geocoding request to Open-Meteo with population ranking."""
    if not query or not query.strip():
        return None

    CITY_ALIASES = {
        "bangalore": "Bengaluru",
        "cherrapunji": "Cherrapunjee",
        "bombay": "Mumbai",
        "calcutta": "Kolkata",
        "madras": "Chennai",
        "poona": "Pune",
        "baroda": "Vadodara",
        "cochin": "Kochi",
        "trivandrum": "Thiruvananthapuram",
        "calicut": "Kozhikode",
        "pondicherry": "Puducherry",
    }

    q_str = query.strip()
    q_lower = q_str.lower()

    search_queries = [q_str]
    for k, v in CITY_ALIASES.items():
        if k in q_lower and q_lower.replace(k, v) not in search_queries:
            search_queries.append(q_lower.replace(k, v))

    candidates = []
    try:
        with httpx.Client(timeout=5.0) as client:
            for sq in search_queries:
                params = {
                    "name": sq,
                    "count": 10,
                    "language": "en",
                    "format": "json"
                }
                resp = client.get(base_url, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    results = data.get("results")
                    if results:
                        candidates.extend(results)

        if not candidates:
            return None

        # Score candidates based on population and administrative feature code
        def score(r):
            pop = r.get("population") or 0
            feat = r.get("feature_code", "")
            feat_score = 0
            if feat in ["PPLC", "PPLA"]:
                feat_score = 1000000
            elif feat in ["PPLA2", "PPL"]:
                feat_score = 100000
            return pop + feat_score

        sorted_candidates = sorted(candidates, key=score, reverse=True)
        return sorted_candidates[0]
    except Exception as e:
        logger.error(f"Geocoding query exception for '{query}': {e}")
        return None



def geocode_location(location_text: str, base_url: str = GEOCODING_API_URL) -> Optional[Dict[str, Any]]:
    """
    Geocodes a location text using Open-Meteo Geocoding API with smart landmark fallbacks.
    Returns dict with name, latitude, longitude, admin1, country or None on failure/empty.
    """
    if not location_text or not location_text.strip():
        return None

    query = location_text.strip()
    first = _query_open_meteo_geocode(query, base_url)

    # Check if a multi-word query (like "Leh Ladakh") gets a better match with comma formatting ("Leh, Ladakh")
    tokens = [t.strip() for t in query.replace(",", " ").split() if len(t.strip()) >= 2]
    if len(tokens) >= 2:
        comma_query = ", ".join(tokens)
        comma_res = _query_open_meteo_geocode(comma_query, base_url)
        if comma_res:
            # Prefer comma_res if first is missing, or if comma_res has a larger population / major admin region
            if not first or comma_res.get("population", 0) > first.get("population", 0) or comma_res.get("admin1"):
                first = comma_res

    # Fallback 1: Strip landmark words (e.g. "Juhu Beach Mumbai" -> "Juhu Mumbai")
    if not first:
        import re
        cleaned = re.sub(r'\b(beach|park|stadium|lake|garden|fort|temple|airport|station|resort|road|street|hill|mount)\b', '', query, flags=re.IGNORECASE).strip()
        if cleaned and cleaned.lower() != query.lower():
            first = _query_open_meteo_geocode(cleaned, base_url)

    # Fallback 2: Extract city/last token (e.g. "Juhu Beach Mumbai" -> "Mumbai")
    if not first:
        if tokens:
            city_query = tokens[-1]
            first = _query_open_meteo_geocode(city_query, base_url)

    # Fallback 3: Transliteration & city alias mappings (e.g. "Cherrapunji" -> "Cherrapunjee")
    if not first:
        CITY_ALIASES = {
            "cherrapunji": "Cherrapunjee",
            "pondicherry": "Puducherry",
            "trivandrum": "Thiruvananthapuram",
            "calicut": "Kozhikode",
            "cochin": "Kochi",
            "baroda": "Vadodara",
            "poona": "Pune",
            "calcutta": "Kolkata",
            "bombay": "Mumbai",
            "madras": "Chennai",
            "bangalore": "Bengaluru",
        }
        query_lower = query.lower()
        alt_name = None
        for k, v in CITY_ALIASES.items():
            if k in query_lower:
                alt_name = query_lower.replace(k, v)
                break
        if not alt_name and query_lower.endswith("ji"):
            alt_name = query[:-2] + "jee"

        if alt_name:
            first = _query_open_meteo_geocode(alt_name, base_url)

    # Fallback 4: Fuzzy Typo Matching against known locations (e.g. "chernujee" -> "Cherrapunjee")
    if not first:
        import difflib
        KNOWN_LOCATIONS = [
            "Cherrapunjee", "Cherrapunji", "Mumbai", "Bhopal", "Delhi", "Kolkata", "Chennai", "Bangalore",
            "Bengaluru", "Shimla", "Manali", "Leh", "Ladakh", "Srinagar", "Jaipur", "Udaipur", "Goa",
            "Pondicherry", "Puducherry", "Kochi", "Cochin", "Thiruvananthapuram", "Trivandrum", "Guwahati",
            "Shillong", "Darjeeling", "Gangtok", "Rishikesh", "Haridwar", "Agra", "Varanasi", "Pune"
        ]
        close = difflib.get_close_matches(query.capitalize(), KNOWN_LOCATIONS, n=1, cutoff=0.45)
        if close:
            first = _query_open_meteo_geocode(close[0], base_url)

    if not first:
        logger.info(f"No geocoding results found for '{location_text}'")
        return None

    return {
        "name": first.get("name", location_text),
        "latitude": float(first.get("latitude")),
        "longitude": float(first.get("longitude")),
        "admin1": first.get("admin1", ""),
        "country": first.get("country", ""),
        "display_name": f"{first.get('name')}, {first.get('admin1', '')}, {first.get('country', '')}".strip(", ")
    }


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

    available_hourly_metrics = [k for k in hourly.keys() if k != "time"]

    for window_name, win_info in windows_config.items():
        start_offset = win_info.get("start_hour", 0)
        end_offset = win_info.get("end_hour", 24)

        if window_name in ["today", "morning", "midday", "afternoon", "evening", "night", "tomorrow"]:
            # Absolute hour offsets relative to 00:00 start of day
            s_idx = max(0, start_offset)
            e_idx = min(len(times), end_offset)
        else:
            # Relative to current hour
            s_idx = max(0, ref_index + start_offset)
            e_idx = min(len(times), ref_index + end_offset)

        if s_idx >= len(times) or s_idx >= e_idx:
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
