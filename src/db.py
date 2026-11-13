"""Read-only, guarded SQL access for LLM-generated queries."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pandas as pd

from src import config

FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum|reindex|truncate|grant)\b",
    re.IGNORECASE,
)


class UnsafeSQLError(ValueError):
    """Raised when generated SQL is not a single read-only SELECT."""


def connect(db_path: Path = config.DB_PATH) -> sqlite3.Connection:
    # mode=ro: the database file itself cannot be modified through this connection
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)


def validate_sql(sql: str) -> str:
    cleaned = sql.strip().strip("`").strip()
    cleaned = re.sub(r"^sql\s*", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = cleaned.rstrip(";").strip()
    if ";" in cleaned:
        raise UnsafeSQLError("Only a single SQL statement is allowed.")
    if not re.match(r"^(select|with)\b", cleaned, re.IGNORECASE):
        raise UnsafeSQLError("Only SELECT queries are allowed.")
    if FORBIDDEN.search(cleaned):
        raise UnsafeSQLError("Query contains a forbidden keyword.")
    return cleaned


def run_query(sql: str, db_path: Path = config.DB_PATH, max_rows: int = config.MAX_RESULT_ROWS) -> pd.DataFrame:
    safe = validate_sql(sql)
    wrapped = f"SELECT * FROM ({safe}) LIMIT {int(max_rows)}"
    with connect(db_path) as con:
        return pd.read_sql_query(wrapped, con)


def schema_description(db_path: Path = config.DB_PATH) -> str:
    """Compact schema text (tables/views + columns + sample values) for the LLM prompt."""
    lines = []
    with connect(db_path) as con:
        objs = con.execute(
            "SELECT name, type FROM sqlite_master WHERE type IN ('table','view') "
            "AND name NOT LIKE 'sqlite_%' ORDER BY type DESC, name"
        ).fetchall()
        for name, kind in objs:
            cols = [r[1] for r in con.execute(f"PRAGMA table_info('{name}')").fetchall()]
            lines.append(f"{kind.upper()} {name}({', '.join(cols)})")
        months = con.execute("SELECT MIN(month), MAX(month) FROM dim_month").fetchone()
        last_complete = con.execute("SELECT MAX(month) FROM dim_month WHERE is_complete=1").fetchone()[0]
        families = [r[0] for r in con.execute("SELECT DISTINCT family FROM fact_sales_monthly ORDER BY 1")]
        types = [r[0] for r in con.execute("SELECT DISTINCT store_type FROM dim_store ORDER BY 1")]
    lines.append(f"-- Data covers months {months[0]} to {months[1]}; last complete month is {last_complete}.")
    lines.append(f"-- family values: {', '.join(families)}")
    lines.append(f"-- store_type values: {', '.join(types)}")
    return "\n".join(lines)
