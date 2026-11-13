"""ETL: Kaggle Favorita CSVs -> SQLite star schema with a modeled monthly P&L.

Usage:
    python -m src.etl                 # uses data/raw (real Kaggle files)
    python -m src.etl --sample        # generates + uses synthetic data in data/sample
    python -m src.etl --raw-dir path  # custom folder
"""
from __future__ import annotations

import argparse
import calendar
import sqlite3
import time
from pathlib import Path

import pandas as pd

from src import config, cost_model

CHUNK_SIZE = 500_000


def _month_str(dates: pd.Series) -> pd.Series:
    return dates.str.slice(0, 7)


def load_train_monthly(train_csv: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Aggregate the ~3M-row daily train.csv to store x family x month in chunks."""
    parts, day_parts = [], []
    reader = pd.read_csv(
        train_csv,
        usecols=["date", "store_nbr", "family", "sales", "onpromotion"],
        dtype={"store_nbr": "int16", "family": "category", "sales": "float64", "onpromotion": "float32"},
        chunksize=CHUNK_SIZE,
    )
    for chunk in reader:
        chunk["month"] = _month_str(chunk["date"])
        day_parts.append(chunk[["month", "date"]].drop_duplicates())
        agg = chunk.groupby(["month", "store_nbr", "family"], observed=True).agg(
            sales=("sales", "sum"), promo_sum=("onpromotion", "sum"), n_days=("date", "nunique")
        )
        parts.append(agg)

    monthly = pd.concat(parts).groupby(level=[0, 1, 2], observed=True).sum().reset_index()
    monthly["family"] = monthly["family"].astype(str)
    monthly["avg_promo_items"] = monthly["promo_sum"] / monthly["n_days"].clip(lower=1)
    days = pd.concat(day_parts).drop_duplicates()
    return monthly.drop(columns=["promo_sum", "n_days"]), days


def build_dim_month(days: pd.DataFrame) -> pd.DataFrame:
    dm = days.groupby("month")["date"].nunique().rename("days_observed").reset_index()
    dm["year"] = dm["month"].str.slice(0, 4).astype(int)
    mnum = dm["month"].str.slice(5, 7).astype(int)
    dm["quarter"] = dm["year"].astype(str) + "-Q" + ((mnum - 1) // 3 + 1).astype(str)
    dm["days_in_month"] = [calendar.monthrange(y, m)[1] for y, m in zip(dm["year"], mnum)]
    # Favorita closes on Dec 25 / Jan 1, so allow one missing day
    dm["is_complete"] = (dm["days_observed"] >= dm["days_in_month"] - 1).astype(int)
    return dm[["month", "year", "quarter", "days_in_month", "days_observed", "is_complete"]]


def build(raw_dir: Path, db_path: Path) -> dict:
    t0 = time.time()
    missing = [f for f in config.KAGGLE_FILES if not (raw_dir / f).exists()]
    if missing:
        raise FileNotFoundError(
            f"Missing {missing} in {raw_dir}. Download the Kaggle data (see README) "
            "or run `python -m src.etl --sample`."
        )

    print(f"[etl] reading {raw_dir / 'train.csv'} ...")
    sales, days = load_train_monthly(raw_dir / "train.csv")
    dim_month = build_dim_month(days)

    stores = pd.read_csv(raw_dir / "stores.csv").rename(columns={"type": "store_type"})

    oil = pd.read_csv(raw_dir / "oil.csv")
    oil["dcoilwtico"] = oil["dcoilwtico"].ffill().bfill()
    oil["month"] = _month_str(oil["date"])
    oil_m = oil.groupby("month")["dcoilwtico"].mean().rename("avg_oil_price").reset_index()

    txn = pd.read_csv(raw_dir / "transactions.csv")
    txn["month"] = _month_str(txn["date"])
    txn_m = txn.groupby(["month", "store_nbr"])["transactions"].sum().reset_index()

    hol = pd.read_csv(raw_dir / "holidays_events.csv")
    hol["month"] = _month_str(hol["date"])
    hol["transferred"] = hol["transferred"].astype(str).str.lower().eq("true").astype(int)

    # Product-level costs
    sales = cost_model.apply_product_costs(sales)

    # Store x month P&L
    sm = sales.groupby(["month", "store_nbr"]).agg(
        revenue=("sales", "sum"), cogs=("cogs", "sum"),
        markdown=("markdown", "sum"), gross_profit=("gross_profit", "sum"),
    ).reset_index()
    sm = (
        sm.merge(stores[["store_nbr", "store_type"]], on="store_nbr", how="left")
        .merge(txn_m, on=["month", "store_nbr"], how="left")
        .merge(oil_m, on="month", how="left")
        .merge(dim_month[["month", "days_observed", "days_in_month"]], on="month", how="left")
    )
    # Stores with no recorded revenue in a month (not yet open) carry no costs
    sm = sm[sm["revenue"] > 0]
    sm = cost_model.apply_store_opex(sm)

    pnl_cols = [
        "month", "store_nbr", "revenue", "cogs", "markdown", "gross_profit", "transactions",
        "avg_oil_price", "labor_cost", "occupancy_cost", "logistics_cost", "overhead_cost",
        "total_opex", "operating_profit",
    ]
    sales_cols = [
        "month", "store_nbr", "family", "sales", "avg_promo_items",
        "base_margin_rate", "markdown", "cogs", "gross_profit",
    ]

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as con:
        con.executescript((config.SQL_DIR / "schema.sql").read_text())
        stores[["store_nbr", "city", "state", "store_type", "cluster"]].to_sql("dim_store", con, if_exists="append", index=False)
        dim_month.to_sql("dim_month", con, if_exists="append", index=False)
        hol[["date", "month", "type", "locale", "locale_name", "description", "transferred"]].to_sql(
            "dim_holiday", con, if_exists="append", index=False)
        oil_m.to_sql("fact_oil_monthly", con, if_exists="append", index=False)
        sales[sales_cols].to_sql("fact_sales_monthly", con, if_exists="append", index=False, chunksize=20_000)
        sm[pnl_cols].to_sql("fact_store_pnl_monthly", con, if_exists="append", index=False, chunksize=20_000)
        con.execute("VACUUM")

    stats = {
        "db_path": str(db_path),
        "months": len(dim_month),
        "stores": stores["store_nbr"].nunique(),
        "families": sales["family"].nunique(),
        "sales_rows": len(sales),
        "total_revenue": float(sm["revenue"].sum()),
        "seconds": round(time.time() - t0, 1),
    }
    print(f"[etl] done: {stats}")
    return stats


def ensure_database(db_path: Path = config.DB_PATH) -> str:
    """Make sure a database exists. Returns 'kaggle', 'sample', or 'existing'."""
    if db_path.exists():
        return "existing"
    if all((config.RAW_DIR / f).exists() for f in config.KAGGLE_FILES):
        build(config.RAW_DIR, db_path)
        return "kaggle"
    from src import sample_data

    sample_data.generate(config.SAMPLE_DIR)
    build(config.SAMPLE_DIR, db_path)
    return "sample"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw-dir", type=Path, default=config.RAW_DIR)
    ap.add_argument("--db", type=Path, default=config.DB_PATH)
    ap.add_argument("--sample", action="store_true", help="generate and load synthetic demo data")
    args = ap.parse_args()

    raw_dir = args.raw_dir
    if args.sample:
        from src import sample_data

        sample_data.generate(config.SAMPLE_DIR)
        raw_dir = config.SAMPLE_DIR
    build(raw_dir, args.db)


if __name__ == "__main__":
    main()
