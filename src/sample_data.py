"""Synthetic data in the exact Kaggle Favorita file format.

Used for (1) running the app before you download the real data,
(2) a public Streamlit demo without redistributing Kaggle data, and (3) tests.
The real Kaggle data always takes priority when present in data/raw.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

FAMILIES = [
    "AUTOMOTIVE", "BABY CARE", "BEAUTY", "BEVERAGES", "BOOKS", "BREAD/BAKERY",
    "CELEBRATION", "CLEANING", "DAIRY", "DELI", "EGGS", "FROZEN FOODS",
    "GROCERY I", "GROCERY II", "HARDWARE", "HOME AND KITCHEN I",
    "HOME AND KITCHEN II", "HOME APPLIANCES", "HOME CARE", "LADIESWEAR",
    "LAWN AND GARDEN", "LINGERIE", "LIQUOR,WINE,BEER", "MAGAZINES", "MEATS",
    "PERSONAL CARE", "PET SUPPLIES", "PLAYERS AND ELECTRONICS", "POULTRY",
    "PREPARED FOODS", "PRODUCE", "SCHOOL AND OFFICE SUPPLIES", "SEAFOOD",
]
# Rough relative daily sales per family per store (USD)
FAMILY_SCALE = {
    "GROCERY I": 3500, "BEVERAGES": 2400, "PRODUCE": 1500, "CLEANING": 1050,
    "DAIRY": 700, "BREAD/BAKERY": 450, "POULTRY": 330, "MEATS": 330,
    "PERSONAL CARE": 280, "DELI": 250, "HOME CARE": 180, "EGGS": 170,
    "FROZEN FOODS": 150, "PREPARED FOODS": 95, "LIQUOR,WINE,BEER": 90,
    "SEAFOOD": 22, "GROCERY II": 21, "HOME AND KITCHEN I": 20,
}
STORES = [
    (1, "Quito", "Pichincha", "D", 13), (2, "Quito", "Pichincha", "D", 13),
    (3, "Quito", "Pichincha", "D", 8), (4, "Quito", "Pichincha", "D", 9),
    (5, "Santo Domingo", "Santo Domingo de los Tsachilas", "D", 4),
    (6, "Quito", "Pichincha", "D", 13), (7, "Quito", "Pichincha", "D", 8),
    (8, "Quito", "Pichincha", "D", 8), (9, "Quito", "Pichincha", "B", 6),
    (10, "Quito", "Pichincha", "C", 15), (24, "Guayaquil", "Guayas", "D", 1),
    (26, "Guayaquil", "Guayas", "D", 10), (44, "Quito", "Pichincha", "A", 5),
    (45, "Quito", "Pichincha", "A", 11), (46, "Quito", "Pichincha", "A", 14),
    (47, "Quito", "Pichincha", "A", 14), (48, "Quito", "Pichincha", "A", 14),
    (49, "Quito", "Pichincha", "A", 11), (51, "Guayaquil", "Guayas", "A", 17),
    (35, "Playas", "Guayas", "C", 3),
]


def _oil_path(dates: pd.DatetimeIndex, rng: np.random.Generator) -> np.ndarray:
    # Piecewise path mimicking WTI 2013-2017: ~95-105, crash late 2014, trough early 2016
    anchors = pd.to_datetime(["2013-01-01", "2014-06-30", "2015-01-31", "2015-06-30",
                              "2016-02-10", "2016-06-30", "2017-08-31"])
    values = np.array([93, 105, 47, 59, 28, 48, 48], dtype=float)
    base = np.interp(dates.asi8, anchors.asi8, values)
    return base + rng.normal(0, 1.2, len(dates))


def generate(out_dir: Path, seed: int = 42, start: str = "2013-01-01", end: str = "2017-08-15") -> Path:
    rng = np.random.default_rng(seed)
    out_dir.mkdir(parents=True, exist_ok=True)

    dates = pd.date_range(start, end, freq="D")
    dates = dates[~((dates.month == 12) & (dates.day == 25))]  # stores closed on Christmas
    n_d = len(dates)
    t = np.arange(n_d) / 365.0

    # Daily company-level multipliers
    trend = 1 + 0.06 * t                                   # ~6% annual growth
    dow = np.array([0.95, 0.9, 0.92, 0.93, 1.0, 1.15, 1.2])[dates.dayofweek]
    season = 1 + 0.25 * np.exp(-((dates.dayofyear - 355) ** 2) / 200)  # December peak
    payday = np.where((dates.day == 15) | dates.is_month_end, 1.08, 1.0)
    quake = np.where((dates >= "2016-04-16") & (dates <= "2016-05-15"), 1.12, 1.0)
    oil = _oil_path(dates, rng)
    # Ecuador is oil-dependent: lower oil -> softer consumer demand (lagged effect)
    macro = 1 + 0.002 * (pd.Series(oil).rolling(90, min_periods=1).mean().to_numpy() - 60)
    day_mult = np.asarray(trend * np.asarray(dow) * np.asarray(season) * payday * quake * macro, dtype=float)

    # Promotions start mid-2014 and ramp up
    promo_ramp = np.clip((t - 1.4) / 1.5, 0, 1)

    rows = []
    stores = pd.DataFrame(STORES, columns=["store_nbr", "city", "state", "type", "cluster"])
    type_scale = {"A": 1.6, "B": 0.9, "C": 0.6, "D": 1.0, "E": 0.5}
    for s in stores.itertuples():
        s_scale = type_scale[s.type] * rng.uniform(0.8, 1.2)
        opens = 0 if s.store_nbr not in (51,) else int(1.2 * 365)  # one late opener
        for fam in FAMILIES:
            f_scale = FAMILY_SCALE.get(fam, rng.uniform(2, 15))
            noise = rng.lognormal(0, 0.12, n_d)
            promo = np.round(promo_ramp * rng.poisson(FAMILY_SCALE.get(fam, 5) / 60 + 1, n_d)).astype(int)
            promo_lift = 1 + 0.015 * np.minimum(promo, 30)
            sales = f_scale * s_scale * day_mult * noise * promo_lift
            sales[:opens] = 0
            if fam in ("BOOKS", "BABY CARE") :
                sales = np.where(rng.random(n_d) < 0.6, 0, sales)
            rows.append(pd.DataFrame({
                "date": dates.strftime("%Y-%m-%d"), "store_nbr": s.store_nbr, "family": fam,
                "sales": np.round(sales, 3), "onpromotion": promo,
            }))

    train = pd.concat(rows, ignore_index=True).sort_values(["date", "store_nbr", "family"])
    train.insert(0, "id", np.arange(len(train)))
    train.to_csv(out_dir / "train.csv", index=False)

    stores.to_csv(out_dir / "stores.csv", index=False)

    oil_df = pd.DataFrame({"date": dates.strftime("%Y-%m-%d"), "dcoilwtico": np.round(oil, 2)})
    oil_df.loc[dates.dayofweek >= 5, "dcoilwtico"] = np.nan  # markets closed on weekends
    oil_df.to_csv(out_dir / "oil.csv", index=False)

    daily_store = train.groupby(["date", "store_nbr"])["sales"].sum().reset_index()
    daily_store = daily_store[daily_store["sales"] > 0]
    avg_basket = rng.uniform(7.5, 9.5)
    daily_store["transactions"] = np.round(daily_store["sales"] / avg_basket * rng.normal(1, 0.05, len(daily_store))).astype(int)
    daily_store[["date", "store_nbr", "transactions"]].to_csv(out_dir / "transactions.csv", index=False)

    hol = pd.DataFrame([
        (f"{y}-12-25", "Holiday", "National", "Ecuador", "Navidad", "False") for y in range(2013, 2017)
    ] + [
        (f"{y}-01-01", "Holiday", "National", "Ecuador", "Primer dia del ano", "False") for y in range(2013, 2018)
    ] + [
        ("2016-04-16", "Event", "National", "Ecuador", "Terremoto Manabi", "False"),
    ], columns=["date", "type", "locale", "locale_name", "description", "transferred"])
    hol.to_csv(out_dir / "holidays_events.csv", index=False)

    print(f"[sample] wrote {len(train):,} train rows for {len(stores)} stores to {out_dir}")
    return out_dir


if __name__ == "__main__":
    from src import config

    generate(config.SAMPLE_DIR)
