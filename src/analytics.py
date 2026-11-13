"""Deterministic finance analytics: period parsing, P&L, operating-profit bridge.

The LLM never invents numbers: every figure in a narrative comes from here,
and the LLM's job is to explain these facts in plain business language.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src import config
from src.db import connect

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], start=1)}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})


@dataclass
class Period:
    label: str
    months: list[str] = field(default_factory=list)


# ----------------------------------------------------------------------------
# Period helpers
# ----------------------------------------------------------------------------
def complete_months(db_path: Path = config.DB_PATH) -> list[str]:
    with connect(db_path) as con:
        return [r[0] for r in con.execute("SELECT month FROM dim_month WHERE is_complete=1 ORDER BY month")]


def _quarter_months(year: int, q: int) -> list[str]:
    return [f"{year}-{m:02d}" for m in range(3 * q - 2, 3 * q + 1)]


def _shift_month(month: str, delta: int) -> str:
    y, m = int(month[:4]), int(month[5:7])
    idx = y * 12 + (m - 1) + delta
    return f"{idx // 12}-{idx % 12 + 1:02d}"


def _prev_quarter(year: int, q: int) -> tuple[int, int]:
    return (year, q - 1) if q > 1 else (year - 1, 4)


def _find_period_tokens(text: str) -> list[Period]:
    """Find explicit periods in the order they appear in the question."""
    t = text.lower()
    found: list[tuple[int, Period]] = []
    taken: list[tuple[int, int]] = []

    def add(span, period):
        if any(s < span[1] and span[0] < e for s, e in taken):
            return
        taken.append(span)
        found.append((span[0], period))

    for m in re.finditer(r"\b(20\d\d)[-\s]?q([1-4])\b|\bq([1-4])[\s-]*(20\d\d)\b", t):
        y = int(m.group(1) or m.group(4))
        q = int(m.group(2) or m.group(3))
        add(m.span(), Period(f"Q{q} {y}", _quarter_months(y, q)))
    for m in re.finditer(r"\b(20\d\d)-(0[1-9]|1[0-2])\b", t):
        add(m.span(), Period(f"{m.group(1)}-{m.group(2)}", [f"{m.group(1)}-{m.group(2)}"]))
    month_names = "|".join(sorted(MONTHS, key=len, reverse=True))
    for m in re.finditer(rf"\b({month_names})\.?\s+(20\d\d)\b", t):
        mm = MONTHS[m.group(1)]
        y = int(m.group(2))
        add(m.span(), Period(f"{m.group(1).title()[:3]} {y}", [f"{y}-{mm:02d}"]))
    for m in re.finditer(r"\b(20\d\d)\b", t):
        y = int(m.group(1))
        add(m.span(), Period(str(y), [f"{y}-{mm:02d}" for mm in range(1, 13)]))
    return [p for _, p in sorted(found, key=lambda x: x[0])]


def resolve_periods(question: str, available: list[str]) -> tuple[Period, Period]:
    """Return (current, prior) periods restricted to complete months."""
    avail = set(available)
    last = available[-1]
    q_lower = question.lower()
    yoy = bool(re.search(r"\byoy\b|year[- ]over[- ]year|same (period|quarter|month) last year|vs\.? last year", q_lower))

    def keep(p: Period) -> Period:
        return Period(p.label, [m for m in p.months if m in avail])

    tokens = [keep(p) for p in _find_period_tokens(question)]
    tokens = [p for p in tokens if p.months]

    if len(tokens) >= 2:
        a, b = tokens[0], tokens[1]
        curr, prior = (a, b) if max(a.months) >= max(b.months) else (b, a)
        # Like-for-like: if comparing a partial year with a full year, align months
        if re.fullmatch(r"\d{4}", curr.label) and re.fullmatch(r"\d{4}", prior.label):
            mm = {m[5:] for m in curr.months} & {m[5:] for m in prior.months}
            if len(mm) < max(len(curr.months), len(prior.months)):
                curr = Period(f"{curr.label} YTD", [m for m in curr.months if m[5:] in mm])
                prior = Period(f"{prior.label} same months", [m for m in prior.months if m[5:] in mm])
    elif len(tokens) == 1:
        curr = tokens[0]
        if curr.label.startswith("Q"):
            y, q = int(curr.label.split()[1]), int(curr.label[1])
            if yoy:
                prior = Period(f"Q{q} {y - 1}", _quarter_months(y - 1, q))
            else:
                py, pq = _prev_quarter(y, q)
                prior = Period(f"Q{pq} {py}", _quarter_months(py, pq))
        elif re.fullmatch(r"\d{4}", curr.label):  # a year (maybe partial)
            prior_months = [_shift_month(m, -12) for m in curr.months]
            label = str(int(curr.label) - 1) if len(curr.months) == 12 else f"{int(curr.label[:4]) - 1} same months"
            if len(curr.months) < 12:
                curr = Period(f"{curr.label} YTD ({curr.months[0][5:]}–{curr.months[-1][5:]})", curr.months)
            prior = Period(label, prior_months)
        else:
            delta = -12 if yoy else -1
            pm = _shift_month(curr.months[0], delta)
            prior = Period(pm, [pm])
    else:
        if re.search(r"\b(month|monthly|mom)\b", q_lower):
            curr = Period(last, [last])
            pm = _shift_month(last, -12 if yoy else -1)
            prior = Period(pm, [pm])
        elif re.search(r"\b(year|annual|yearly)\b", q_lower) and not yoy:
            full_years = sorted({m[:4] for m in available if sum(x[:4] == m[:4] for x in available) >= 11})
            y = int(full_years[-1])
            curr = keep(Period(str(y), [f"{y}-{mm:02d}" for mm in range(1, 13)]))
            prior = keep(Period(str(y - 1), [f"{y - 1}-{mm:02d}" for mm in range(1, 13)]))
        else:  # default: latest complete quarter vs previous quarter (or YoY)
            y, mo = int(last[:4]), int(last[5:7])
            q = (mo - 1) // 3 + 1
            if mo % 3 != 0:  # last quarter not complete -> step back
                y, q = _prev_quarter(y, q)
            curr = Period(f"Q{q} {y}", _quarter_months(y, q))
            if yoy:
                prior = Period(f"Q{q} {y - 1}", _quarter_months(y - 1, q))
            else:
                py, pq = _prev_quarter(y, q)
                prior = Period(f"Q{pq} {py}", _quarter_months(py, pq))

    curr, prior = keep(curr), keep(prior)
    if not curr.months or not prior.months:
        raise ValueError(
            f"Not enough complete data to compare '{curr.label}' with '{prior.label}'. "
            f"Data covers {available[0]} to {available[-1]}."
        )
    return curr, prior


# ----------------------------------------------------------------------------
# P&L and bridge
# ----------------------------------------------------------------------------
def _in_clause(months: list[str]) -> str:
    return ",".join(f"'{m}'" for m in months)


def pnl(months: list[str], db_path: Path = config.DB_PATH) -> dict:
    sql = f"""
        SELECT SUM(revenue) revenue, SUM(cogs) cogs, SUM(markdown) markdown,
               SUM(gross_profit) gross_profit, SUM(labor_cost) labor_cost,
               SUM(occupancy_cost) occupancy_cost, SUM(logistics_cost) logistics_cost,
               SUM(overhead_cost) overhead_cost, SUM(total_opex) total_opex,
               SUM(operating_profit) operating_profit, SUM(transactions) transactions,
               AVG(avg_oil_price) avg_oil_price, COUNT(DISTINCT store_nbr) stores
        FROM fact_store_pnl_monthly WHERE month IN ({_in_clause(months)})"""
    with connect(db_path) as con:
        row = pd.read_sql_query(sql, con).iloc[0].to_dict()
        promo = con.execute(
            f"SELECT AVG(avg_promo_items) FROM fact_sales_monthly WHERE month IN ({_in_clause(months)})"
        ).fetchone()[0]
    rev = row["revenue"] or 0.0
    row["gross_margin_pct"] = row["gross_profit"] / rev if rev else 0.0
    row["operating_margin_pct"] = row["operating_profit"] / rev if rev else 0.0
    row["markdown_pct"] = row["markdown"] / rev if rev else 0.0
    row["avg_ticket"] = rev / row["transactions"] if row["transactions"] else 0.0
    row["avg_promo_items"] = promo or 0.0
    return row


def _family_frame(months: list[str], db_path: Path) -> pd.DataFrame:
    sql = f"""SELECT family, SUM(sales) revenue, SUM(gross_profit) gross_profit, SUM(markdown) markdown
              FROM fact_sales_monthly WHERE month IN ({_in_clause(months)}) GROUP BY family"""
    with connect(db_path) as con:
        return pd.read_sql_query(sql, con).set_index("family")


def profit_bridge(curr: Period, prior: Period, db_path: Path = config.DB_PATH) -> pd.DataFrame:
    """Operating-profit walk from prior to current period. Steps sum exactly."""
    pc, pp = pnl(curr.months, db_path), pnl(prior.months, db_path)
    fc, fp = _family_frame(curr.months, db_path), _family_frame(prior.months, db_path)
    fam = fc.join(fp, lsuffix="_c", rsuffix="_p", how="outer").fillna(0.0)

    rev_c, rev_p = pc["revenue"], pp["revenue"]
    gm_p = pp["gross_margin_pct"]
    volume = (rev_c - rev_p) * gm_p
    share_c = fam["revenue_c"] / rev_c if rev_c else 0
    share_p = fam["revenue_p"] / rev_p if rev_p else 0
    fam_gm_p = (fam["gross_profit_p"] / fam["revenue_p"]).where(fam["revenue_p"] > 0, gm_p)
    mix = rev_c * float(((share_c - share_p) * fam_gm_p).sum())
    rate = (pc["gross_profit"] - pp["gross_profit"]) - volume - mix

    steps = [
        (f"Operating profit {prior.label}", pp["operating_profit"], "total"),
        ("Revenue volume", volume, "relative"),
        ("Product mix", mix, "relative"),
        ("Margin rate & promo markdowns", rate, "relative"),
        ("Labor", -(pc["labor_cost"] - pp["labor_cost"]), "relative"),
        ("Occupancy", -(pc["occupancy_cost"] - pp["occupancy_cost"]), "relative"),
        ("Logistics (fuel-linked)", -(pc["logistics_cost"] - pp["logistics_cost"]), "relative"),
        ("Corporate overhead", -(pc["overhead_cost"] - pp["overhead_cost"]), "relative"),
        (f"Operating profit {curr.label}", pc["operating_profit"], "total"),
    ]
    return pd.DataFrame(steps, columns=["step", "amount", "measure"])


def top_movers(curr: Period, prior: Period, dimension: str = "family", n: int = 5,
               db_path: Path = config.DB_PATH) -> pd.DataFrame:
    if dimension == "family":
        sql = """SELECT family AS name, SUM(sales) revenue, SUM(gross_profit) profit
                 FROM fact_sales_monthly WHERE month IN ({m}) GROUP BY family"""
        metric = "gross_profit"
    else:
        sql = """SELECT 'Store ' || p.store_nbr || ' (' || s.city || ', type ' || s.store_type || ')' AS name,
                        SUM(p.revenue) revenue, SUM(p.operating_profit) profit
                 FROM fact_store_pnl_monthly p JOIN dim_store s USING (store_nbr)
                 WHERE p.month IN ({m}) GROUP BY p.store_nbr"""
        metric = "operating_profit"
    with connect(db_path) as con:
        c = pd.read_sql_query(sql.format(m=_in_clause(curr.months)), con).set_index("name")
        p = pd.read_sql_query(sql.format(m=_in_clause(prior.months)), con).set_index("name")
    df = c.join(p, lsuffix="_curr", rsuffix="_prior", how="outer").fillna(0.0)
    df["revenue_change"] = df["revenue_curr"] - df["revenue_prior"]
    df[f"{metric}_change"] = df["profit_curr"] - df["profit_prior"]
    df = df.rename(columns={"profit_curr": f"{metric}_curr", "profit_prior": f"{metric}_prior"})
    df = df.sort_values(f"{metric}_change")
    return pd.concat([df.head(n), df.tail(n)]).drop_duplicates().reset_index()


def events_in(months: list[str], db_path: Path = config.DB_PATH) -> list[str]:
    with connect(db_path) as con:
        rows = con.execute(
            f"SELECT DISTINCT description FROM dim_holiday WHERE month IN ({_in_clause(months)}) "
            "AND locale='National' AND transferred=0 LIMIT 8"
        ).fetchall()
    return [r[0] for r in rows]


def analyze_change(question: str, db_path: Path = config.DB_PATH) -> dict:
    """Everything needed to answer 'why did X change between two periods?'."""
    curr, prior = resolve_periods(question, complete_months(db_path))
    pc, pp = pnl(curr.months, db_path), pnl(prior.months, db_path)
    return {
        "current": curr,
        "prior": prior,
        "pnl_current": pc,
        "pnl_prior": pp,
        "bridge": profit_bridge(curr, prior, db_path),
        "family_movers": top_movers(curr, prior, "family", 5, db_path),
        "store_movers": top_movers(curr, prior, "store", 3, db_path),
        "events": events_in(curr.months, db_path),
    }


# ----------------------------------------------------------------------------
# Formatting for prompts and offline narratives
# ----------------------------------------------------------------------------
def money(x: float) -> str:
    sign = "-" if x < 0 else ""
    x = abs(x)
    if x >= 1e9:
        return f"{sign}${x / 1e9:.2f}B"
    if x >= 1e6:
        return f"{sign}${x / 1e6:.2f}M"
    if x >= 1e3:
        return f"{sign}${x / 1e3:.1f}K"
    return f"{sign}${x:,.0f}"


def pct_change(c: float, p: float) -> str:
    return "n/a" if not p else f"{(c - p) / abs(p):+.1%}"


def facts_text(a: dict) -> str:
    """Compact, factual brief used to ground the LLM (no raw tables)."""
    pc, pp = a["pnl_current"], a["pnl_prior"]
    cl, pl = a["current"].label, a["prior"].label
    lines = [f"Comparison: {cl} (current) vs {pl} (prior). Currency USD.", "", "KEY P&L:"]
    for k, name in [("revenue", "Revenue"), ("gross_profit", "Gross profit"),
                    ("total_opex", "Operating expenses"), ("operating_profit", "Operating profit")]:
        lines.append(f"- {name}: {money(pc[k])} vs {money(pp[k])} ({pct_change(pc[k], pp[k])})")
    lines += [
        f"- Gross margin: {pc['gross_margin_pct']:.2%} vs {pp['gross_margin_pct']:.2%}",
        f"- Operating margin: {pc['operating_margin_pct']:.2%} vs {pp['operating_margin_pct']:.2%}",
        f"- Promo markdowns as % of revenue: {pc['markdown_pct']:.2%} vs {pp['markdown_pct']:.2%}",
        f"- Avg items on promotion per store-family-day: {pc['avg_promo_items']:.1f} vs {pp['avg_promo_items']:.1f}",
        f"- Transactions: {pc['transactions']:,.0f} vs {pp['transactions']:,.0f} ({pct_change(pc['transactions'], pp['transactions'])})",
        f"- Avg ticket: ${pc['avg_ticket']:.2f} vs ${pp['avg_ticket']:.2f}",
        f"- Avg WTI oil price: ${pc['avg_oil_price']:.1f} vs ${pp['avg_oil_price']:.1f}",
        f"- Stores trading: {pc['stores']:.0f} vs {pp['stores']:.0f}",
        "", "OPERATING PROFIT BRIDGE (positive = increases profit):",
    ]
    for r in a["bridge"].itertuples():
        lines.append(f"- {r.step}: {money(r.amount)}")
    fm = a["family_movers"]
    lines.append("")
    lines.append("PRODUCT FAMILIES - biggest gross profit changes:")
    for r in fm.itertuples():
        lines.append(f"- {r.name}: GP change {money(r.gross_profit_change)}, revenue change {money(r.revenue_change)}")
    lines.append("")
    lines.append("STORES - biggest operating profit changes:")
    for r in a["store_movers"].itertuples():
        lines.append(f"- {r.name}: OP change {money(r.operating_profit_change)}, revenue change {money(r.revenue_change)}")
    if a["events"]:
        lines += ["", "National holidays/events in current period: " + "; ".join(a["events"])]
    lines += ["", "NOTE: Revenue, promotions, transactions and oil prices are actual data. "
              "Cost lines come from a documented cost model (assumptions)."]
    return "\n".join(lines)


def template_narrative(a: dict) -> str:
    """Rule-based explanation used when no LLM API key is configured."""
    pc, pp = a["pnl_current"], a["pnl_prior"]
    cl, pl = a["current"].label, a["prior"].label
    d_op = pc["operating_profit"] - pp["operating_profit"]
    direction = "declined" if d_op < 0 else "increased"
    bridge = a["bridge"][a["bridge"]["measure"] == "relative"].copy()
    neg = bridge[bridge["amount"] < 0].sort_values("amount")
    pos = bridge[bridge["amount"] > 0].sort_values("amount", ascending=False)

    out = [
        f"**Operating profit {direction} {money(abs(d_op))} ({pct_change(pc['operating_profit'], pp['operating_profit'])})** "
        f"from {money(pp['operating_profit'])} in {pl} to {money(pc['operating_profit'])} in {cl}. "
        f"Operating margin moved from {pp['operating_margin_pct']:.1%} to {pc['operating_margin_pct']:.1%}.",
        "",
    ]
    if len(neg):
        out.append("**What pulled profit down:**")
        out += [f"- {r.step}: {money(r.amount)}" for r in neg.head(3).itertuples()]
    if len(pos):
        out.append("**What offset it:**" if d_op < 0 else "**What drove the improvement:**")
        out += [f"- {r.step}: +{money(r.amount)}" for r in pos.head(3).itertuples()]
    out.append("")
    out.append(
        f"Revenue was {money(pc['revenue'])} ({pct_change(pc['revenue'], pp['revenue'])}); gross margin "
        f"{pp['gross_margin_pct']:.1%} → {pc['gross_margin_pct']:.1%}, with promo markdowns at "
        f"{pc['markdown_pct']:.1%} of sales (vs {pp['markdown_pct']:.1%}). Average oil price "
        f"${pp['avg_oil_price']:.0f} → ${pc['avg_oil_price']:.0f}."
    )
    worst = a["family_movers"].iloc[0]
    best = a["family_movers"].iloc[-1]
    out.append(
        f"Largest family swing down: **{worst['name']}** ({money(worst['gross_profit_change'])} GP); "
        f"up: **{best['name']}** ({money(best['gross_profit_change'])} GP)."
    )
    return "\n".join(out)
