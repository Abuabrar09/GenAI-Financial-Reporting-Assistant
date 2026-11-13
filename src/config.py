"""Central configuration: paths, LLM settings, and secrets lookup."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
SAMPLE_DIR = ROOT / "data" / "sample"
PROCESSED_DIR = ROOT / "data" / "processed"
DB_PATH = Path(os.getenv("FINBI_DB_PATH", PROCESSED_DIR / "finance.db"))
SQL_DIR = ROOT / "sql"

# Files expected from the Kaggle "store-sales-time-series-forecasting" competition
KAGGLE_FILES = ["train.csv", "stores.csv", "oil.csv", "transactions.csv", "holidays_events.csv"]

# Max rows the natural-language SQL engine may return to the UI / LLM
MAX_RESULT_ROWS = 500
MAX_ROWS_TO_LLM = 60


def get_secret(name: str, default: str | None = None) -> str | None:
    """Read a secret from Streamlit secrets (when running in Streamlit) or env vars."""
    try:
        import streamlit as st  # noqa: WPS433

        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return os.getenv(name, default)


def llm_settings() -> dict:
    """Resolve which LLM provider to use. Falls back to 'offline' if no key is set."""
    provider = (get_secret("LLM_PROVIDER") or "").lower().strip()
    anthropic_key = get_secret("ANTHROPIC_API_KEY")
    openai_key = get_secret("OPENAI_API_KEY")

    if not provider:
        provider = "anthropic" if anthropic_key else "openai" if openai_key else "offline"

    return {
        "provider": provider,
        "anthropic_key": anthropic_key,
        "openai_key": openai_key,
        "anthropic_model": get_secret("ANTHROPIC_MODEL", "claude-sonnet-5-5"),
        "openai_model": get_secret("OPENAI_MODEL", "gpt-4.1-mini"),
    }
