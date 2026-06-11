"""
config.py — TIP ESG Platform · Central Configuration
=====================================================
Single source of truth for all file paths, year bounds, auth settings,
LLM endpoints, and tuneable constants.

To override any value in production, set it in .streamlit/secrets.toml
or as an environment variable with the same key name.

Example secrets.toml:
    DATA_YEAR_START = 2009
    DATA_YEAR_END   = 2024
    DSS_EMAIL_DOMAIN = "@consultdss.com"
"""

from __future__ import annotations
import os
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


def _secret(key: str, default: str = "") -> str:
    """Read from Streamlit secrets → env var → default (in that priority)."""
    try:
        import streamlit as st
        val = st.secrets.get(key, "")
        if val and isinstance(val, str) and val.strip():
            return val.strip()
    except Exception:
        pass
    return os.environ.get(key, default)


# ── Root paths ────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data_storage"

# ── Year bounds (updated dynamically from loaded data) ────────────────────────
DATA_YEAR_START: int = int(_secret("DATA_YEAR_START", "2009"))
DATA_YEAR_END:   int = int(_secret("DATA_YEAR_END",   "2023"))


def refresh_year_bounds(df=None) -> tuple[int, int]:
    """Derive year range from loaded DataFrame and update module globals."""
    global DATA_YEAR_START, DATA_YEAR_END
    if df is not None and not df.empty and "Year" in df.columns:
        try:
            years = sorted(df["Year"].dropna().astype(int).unique())
            if years:
                DATA_YEAR_START = years[0]
                DATA_YEAR_END   = years[-1]
                logger.info("[config] Year bounds: %d–%d", DATA_YEAR_START, DATA_YEAR_END)
                return DATA_YEAR_START, DATA_YEAR_END
        except Exception as e:
            logger.warning("[config] Could not derive year bounds: %s", e)
    return DATA_YEAR_START, DATA_YEAR_END


def hist_years() -> list[int]:
    """Historical years — excludes current reporting year."""
    return list(range(DATA_YEAR_START, DATA_YEAR_END))


def long_years() -> list[int]:
    """Full range including current reporting year."""
    return list(range(DATA_YEAR_START, DATA_YEAR_END + 1))


def curr_year() -> int:
    """Most recent data year."""
    return DATA_YEAR_END


# ── Storage paths (local; replaced by Azure SQL/Blob on migration) ────────────
MASTER_DIR   = DATA_DIR / "master"
VERSIONS_DIR = DATA_DIR / "versions"
MEMBERS_DIR  = DATA_DIR / "members"
REPORTS_DIR  = DATA_DIR / "reports" / "TIP"
LOGS_DIR     = DATA_DIR / "chat_logs"
VALIDATED_DIR = DATA_DIR / "validated"

# ── Authentication ─────────────────────────────────────────────────────────────
DSS_EMAIL_DOMAIN = _secret("DSS_EMAIL_DOMAIN", "@consultdss.com")


def load_clients() -> dict[str, str]:
    """
    Load email → company mapping.
    Production: set CLIENTS_JSON in secrets.toml.
    Falls back to demo dict for local development.
    """
    import json
    raw = _secret("CLIENTS_JSON", "")
    if raw:
        try:
            return json.loads(raw)
        except Exception as e:
            logger.warning("[config] CLIENTS_JSON parse error: %s", e)
    return {
        "verdatyres@tip-reporting.com":   "VerdaTyres Corp",
        "alphatread@tip-reporting.com":   "AlphaTread Ltd",
        "betarubber@tip-reporting.com":   "BetaRubber Inc",
        "gammatire@tip-reporting.com":    "GammaTire SA",
        "deltagrip@tip-reporting.com":    "DeltaGrip GmbH",
        "epsilonwheel@tip-reporting.com": "EpsilonWheel Co",
        "zetatrac@tip-reporting.com":     "ZetaTrac LLC",
        "etaroad@tip-reporting.com":      "EtaRoad AG",
        "thetadrive@tip-reporting.com":   "ThetaDrive NV",
        "iotatire@tip-reporting.com":     "IotaTire PLC",
    }


# ── LLM / AI (read by ai/llm_client.py) ──────────────────────────────────────
AZURE_OPENAI_ENDPOINT   = _secret("AZURE_OPENAI_ENDPOINT", "https://YOUR-RESOURCE.openai.azure.com")
AZURE_OPENAI_KEY        = _secret("AZURE_OPENAI_KEY",      "")
AZURE_OPENAI_DEPLOYMENT = _secret("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
OLLAMA_BASE_URL         = _secret("OLLAMA_URL",   "http://localhost:11434")
OLLAMA_DEFAULT_MODEL    = _secret("OLLAMA_MODEL", "phi3")

# ── Misc ──────────────────────────────────────────────────────────────────────
FILELOCK_TIMEOUT:   int = int(_secret("FILELOCK_TIMEOUT",   "10"))
LOG_RETENTION_DAYS: int = int(_secret("LOG_RETENTION_DAYS", "8"))
