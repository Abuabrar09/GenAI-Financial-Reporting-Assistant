"""Cost model that turns Favorita sales into a store-level P&L.

The Kaggle dataset contains revenue (sales), promotions, transactions and oil
prices -- but no costs. To answer finance questions such as
"Why did operating profit decline?" we layer a transparent, documented set of
ASSUMPTIONS on top of the real sales data. Every number below is an
assumption, chosen to be realistic for a grocery retailer, and is surfaced in
the app's "Assumptions" panel so users always know what is modeled vs. actual.

Sales are treated as revenue in USD (Ecuador's currency is the US dollar).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# --- Base gross margin % by product family (before promotional markdowns) ---
GROSS_MARGIN_BY_FAMILY: dict[str, float] = {
    "AUTOMOTIVE": 0.32, "BABY CARE": 0.30, "BEAUTY": 0.40, "BEVERAGES": 0.30,
    "BOOKS": 0.35, "BREAD/BAKERY": 0.45, "CELEBRATION": 0.42, "CLEANING": 0.31,
    "DAIRY": 0.27, "DELI": 0.40, "EGGS": 0.22, "FROZEN FOODS": 0.29,
    "GROCERY I": 0.24, "GROCERY II": 0.26, "HARDWARE": 0.36,
    "HOME AND KITCHEN I": 0.38, "HOME AND KITCHEN II": 0.38,
    "HOME APPLIANCES": 0.25, "HOME CARE": 0.32, "LADIESWEAR": 0.48,
    "LAWN AND GARDEN": 0.37, "LINGERIE": 0.50, "LIQUOR,WINE,BEER": 0.28,
    "MAGAZINES": 0.30, "MEATS": 0.22, "PERSONAL CARE": 0.35,
    "PET SUPPLIES": 0.33, "PLAYERS AND ELECTRONICS": 0.20, "POULTRY": 0.20,
    "PREPARED FOODS": 0.42, "PRODUCE": 0.35, "SCHOOL AND OFFICE SUPPLIES": 0.38,
    "SEAFOOD": 0.25,
}
DEFAULT_GROSS_MARGIN = 0.28

# --- Promotional markdown: margin given away when items are on promotion ---
# markdown_rate = MAX_MARKDOWN * promo_items / (promo_items + PROMO_HALF_SATURATION)
MAX_MARKDOWN = 0.12
PROMO_HALF_SATURATION = 20.0

# --- Store operating expenses (per store per month unless noted) ---
FIXED_LABOR_BY_TYPE = {"A": 40_000, "B": 30_000, "C": 22_000, "D": 28_000, "E": 20_000}
VARIABLE_LABOR_PCT = 0.06          # of revenue
OCCUPANCY_BY_TYPE = {"A": 25_000, "B": 18_000, "C": 12_000, "D": 16_000, "E": 10_000}
LOGISTICS_COST_PER_TXN = 0.25      # USD per customer transaction at the baseline oil price
OIL_BASELINE = 60.0                # USD/bbl; logistics scales with oil / baseline
OIL_ELASTICITY = 0.5               # 50% of logistics cost moves with fuel
CORPORATE_OVERHEAD_PCT = 0.02      # of revenue, allocated to stores


def gross_margin_rate(family: pd.Series) -> pd.Series:
    return family.map(GROSS_MARGIN_BY_FAMILY).fillna(DEFAULT_GROSS_MARGIN)


def markdown_rate(promo_items: pd.Series | np.ndarray) -> np.ndarray:
    p = np.asarray(promo_items, dtype=float).clip(min=0)
    return MAX_MARKDOWN * p / (p + PROMO_HALF_SATURATION)


def apply_product_costs(df: pd.DataFrame) -> pd.DataFrame:
    """Add base_margin_rate, markdown, cogs, gross_profit to a sales frame.

    Expects columns: family, sales, onpromotion (avg daily items on promo).
    """
    out = df.copy()
    out["base_margin_rate"] = gross_margin_rate(out["family"])
    out["markdown"] = out["sales"] * markdown_rate(out["avg_promo_items"])
    out["cogs"] = out["sales"] * (1 - out["base_margin_rate"]) + out["markdown"]
    out["gross_profit"] = out["sales"] - out["cogs"]
    return out


def apply_store_opex(store_month: pd.DataFrame) -> pd.DataFrame:
    """Add opex lines and operating profit to a store x month frame.

    Expects columns: store_type, revenue, gross_profit, transactions,
    avg_oil_price, days_observed, days_in_month.
    """
    out = store_month.copy()
    month_fraction = out["days_observed"] / out["days_in_month"]
    oil = out["avg_oil_price"].fillna(OIL_BASELINE)
    fuel_index = (1 - OIL_ELASTICITY) + OIL_ELASTICITY * (oil / OIL_BASELINE)

    out["labor_cost"] = (
        out["store_type"].map(FIXED_LABOR_BY_TYPE).fillna(25_000) * month_fraction
        + VARIABLE_LABOR_PCT * out["revenue"]
    )
    out["occupancy_cost"] = out["store_type"].map(OCCUPANCY_BY_TYPE).fillna(15_000) * month_fraction
    out["logistics_cost"] = out["transactions"].fillna(0) * LOGISTICS_COST_PER_TXN * fuel_index
    out["overhead_cost"] = CORPORATE_OVERHEAD_PCT * out["revenue"]
    out["total_opex"] = out[["labor_cost", "occupancy_cost", "logistics_cost", "overhead_cost"]].sum(axis=1)
    out["operating_profit"] = out["gross_profit"] - out["total_opex"]
    return out


def assumptions_table() -> pd.DataFrame:
    rows = [
        ("Revenue", "Kaggle `sales` column treated as USD revenue", "Actual data"),
        ("Gross margin", "20%–50% by product family (e.g. Grocery I 24%, Bakery 45%)", "Assumption"),
        ("Promo markdown", f"Up to {MAX_MARKDOWN:.0%} of sales, rising with # items on promotion", "Assumption"),
        ("Labor", f"Fixed by store type (A–E) + {VARIABLE_LABOR_PCT:.0%} of revenue", "Assumption"),
        ("Occupancy", "Fixed monthly rent by store type", "Assumption"),
        ("Logistics", f"${LOGISTICS_COST_PER_TXN}/transaction, {OIL_ELASTICITY:.0%} indexed to WTI oil vs ${OIL_BASELINE:.0f}", "Assumption on actual transactions + oil"),
        ("Corporate overhead", f"{CORPORATE_OVERHEAD_PCT:.0%} of revenue", "Assumption"),
    ]
    return pd.DataFrame(rows, columns=["Line item", "Rule", "Source"])
