"""
config.py: Environment setup, configuration loader, and time window definitions.
Supports os.environ with fallback to st.secrets for Streamlit Cloud.
"""
import os
from pathlib import Path
from typing import Dict, Any, Optional
import yaml
import logging

logger = logging.getLogger(__name__)

# Base Paths
BASE_DIR = Path(__file__).resolve().parent.parent
SOPS_DIR = BASE_DIR / "sops"
CONFIG_DIR = BASE_DIR / "config"
TIME_WINDOWS_FILE = CONFIG_DIR / "time_windows.yaml"

def get_secret_or_env(key: str, default: Optional[str] = None) -> Optional[str]:
    """Retrieve key from environment variables, with fallback to st.secrets."""
    val = os.environ.get(key)
    if val:
        return val
    try:
        import streamlit as st
        if hasattr(st, "secrets") and key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return default

# LLM Configuration
LLM_PROVIDER = get_secret_or_env("LLM_PROVIDER", "groq")
LLM_MODEL = get_secret_or_env("LLM_MODEL", "llama-3.3-70b-versatile")
GROQ_API_KEY = get_secret_or_env("GROQ_API_KEY")
ANTHROPIC_API_KEY = get_secret_or_env("ANTHROPIC_API_KEY")
OPENAI_API_KEY = get_secret_or_env("OPENAI_API_KEY")
GEMINI_API_KEY = get_secret_or_env("GEMINI_API_KEY") or get_secret_or_env("GOOGLE_API_KEY")

def load_time_windows() -> Dict[str, Dict[str, Any]]:
    """Load time window definitions from config/time_windows.yaml."""
    if not TIME_WINDOWS_FILE.exists():
        return {
            "now": {"start_hour": 0, "end_hour": 1},
            "today": {"start_hour": 0, "end_hour": 24},
            "morning": {"start_hour": 6, "end_hour": 12},
            "midday": {"start_hour": 11, "end_hour": 16},
            "afternoon": {"start_hour": 12, "end_hour": 17},
            "evening": {"start_hour": 17, "end_hour": 22},
            "night": {"start_hour": 22, "end_hour": 28},
            "tomorrow": {"start_hour": 24, "end_hour": 48},
        }
    with open(TIME_WINDOWS_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}
