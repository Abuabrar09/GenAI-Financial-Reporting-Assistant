"""The assistant: routes a natural-language question to the right engine.

  1. "Why did X change?"   -> deterministic profit bridge + LLM explanation
  2. Any other data query  -> LLM text-to-SQL -> safe execution -> LLM insight
  3. No API key            -> rule-based SQL templates + templated narrative
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src import analytics, config, db, prompts
from src.llm import LLMClient


@dataclass
class Answer:
    question: str
    text: str
    kind: str                       # 'explain_change' | 'sql' | 'error'
    sql: str | None = None
    data: pd.DataFrame | None = None
    chart: dict = field(default_factory=dict)
    title: str = ""
    analysis: dict | None = None
    engine: str = ""


WHY_PATTERN = re.compile(
    r"\b(why|what (caused|drove|happened)|drivers?|explain|reason|bridge|walk)\b.*"
    r"\b(profit|margin|earnings|ebit|revenue|sales|income|cost|expense|performance)\b"
    r"|\b(profit|margin|revenue|sales)\b.*\b(decline|declined|drop|dropped|fall|fell|decrease|increase|grow|grew|change|changed)\b",
    re.IGNORECASE,
)


def is_change_question(q: str) -> bool:
    return bool(WHY_PATTERN.search(q))


def _year_in(q: str, db_path: Path) -> str:
    m = re.search(r"\b(20\d\d)\b", q)
    if m:
        return m.group(1)
    months = analytics.complete_months(db_path)
    years = pd.Series([x[:4] for x in months]).value_counts()
    return max(y for y, n in years.items() if n >= 11)


# ----------------------------------------------------------------------------
# Offline router (works with zero API keys -> great for public demos)
# ----------------------------------------------------------------------------
def offline_sql(q: str, db_path: Path) -> tuple[str, str, dict]:
    ql = q.lower()
    year = _year_in(q, db_path)
    metric = "operating_profit"
    if re.search(r"revenue|sales", ql):
        metric = "revenue"
    elif "gross" in ql:
        metric = "gross_profit"
    order = "ASC" if re.search(r"worst|bottom|lowest|least|loss", ql) else "DESC"
    n = int(m.group(1)) if (m := re.search(r"\b(?:top|bottom|best|worst)\s+(\d+)", ql)) else 10

    if re.search(r"store type|by type|format", ql):
        sql = f"""SELECT store_type, COUNT(DISTINCT store_nbr) AS stores, ROUND(SUM(revenue)) AS revenue,
                 ROUND(SUM(operating_profit)) AS operating_profit,
                 ROUND(SUM(operating_profit)*1.0/SUM(revenue),4) AS operating_margin
                 FROM v_store_pnl_monthly WHERE substr(month,1,4)='{year}'
                 GROUP BY store_type ORDER BY operating_profit DESC"""
        return sql, f"P&L by store type, {year}", {"type": "bar", "x": "store_type", "y": ["operating_profit"]}
    if re.search(r"\bstores?\b", ql) and not re.search(r"trend|month", ql):
        if "gross" in ql:  # gross profit lives at family grain; aggregate per store
            sql = f"""SELECT s.store_nbr, s.city, s.store_type, ROUND(SUM(f.sales)) AS revenue,
                     ROUND(SUM(f.gross_profit)) AS gross_profit
                     FROM fact_sales_monthly f JOIN dim_store s USING (store_nbr)
                     WHERE substr(f.month,1,4)='{year}' GROUP BY s.store_nbr ORDER BY gross_profit {order} LIMIT {n}"""
        else:
            sql = f"""SELECT store_nbr, city, store_type, ROUND(SUM(revenue)) AS revenue,
                     ROUND(SUM(operating_profit)) AS operating_profit,
                     ROUND(SUM(operating_profit)*1.0/SUM(revenue),4) AS operating_margin
                     FROM v_store_pnl_monthly WHERE substr(month,1,4)='{year}'
                     GROUP BY store_nbr, city, store_type ORDER BY {metric} {order} LIMIT {n}"""
        word = "Bottom" if order == "ASC" else "Top"
        return sql, f"{word} {n} stores by {metric.replace('_', ' ')}, {year}", {
            "type": "bar", "x": "store_nbr", "y": [metric]}
    if re.search(r"famil|categor|department|product", ql):
        sql = f"""SELECT family, ROUND(SUM(revenue)) AS revenue, ROUND(SUM(gross_profit)) AS gross_profit,
                 ROUND(SUM(gross_profit)*1.0/SUM(revenue),4) AS gross_margin
                 FROM v_family_pnl_monthly WHERE substr(month,1,4)='{year}'
                 GROUP BY family ORDER BY {'revenue' if metric == 'revenue' else 'gross_profit'} {order} LIMIT {n}"""
        return sql, f"Product families, {year}", {"type": "bar", "x": "family", "y": ["revenue" if metric == "revenue" else "gross_profit"]}
    if re.search(r"promo|markdown|discount", ql):
        sql = """SELECT p.month, ROUND(p.markdown*1.0/p.revenue,4) AS markdown_pct, ROUND(p.gross_margin_pct,4) AS gross_margin_pct,
                 ROUND(f.avg_promo,2) AS avg_items_on_promo
                 FROM v_company_pnl_monthly p
                 JOIN (SELECT month, AVG(avg_promo_items) avg_promo FROM fact_sales_monthly GROUP BY month) f USING (month)
                 WHERE p.is_complete=1 ORDER BY p.month"""
        return sql, "Promotions vs. margin", {"type": "line", "x": "month", "y": ["markdown_pct", "gross_margin_pct"]}
    if re.search(r"oil|fuel|logistic|freight", ql):
        sql = """SELECT month, ROUND(avg_oil_price,2) AS avg_oil_price, ROUND(logistics_cost) AS logistics_cost
                 FROM v_company_pnl_monthly WHERE is_complete=1 ORDER BY month"""
        return sql, "Oil price vs. logistics cost", {"type": "line", "x": "month", "y": ["logistics_cost"]}
    if re.search(r"city|state|region|province", ql):
        sql = f"""SELECT city, COUNT(DISTINCT store_nbr) AS stores, ROUND(SUM(revenue)) AS revenue,
                 ROUND(SUM(operating_profit)) AS operating_profit
                 FROM v_store_pnl_monthly WHERE substr(month,1,4)='{year}'
                 GROUP BY city ORDER BY revenue DESC LIMIT 20"""
        return sql, f"Performance by city, {year}", {"type": "bar", "x": "city", "y": ["revenue"]}
    if re.search(r"trend|month|over time|monthly", ql):
        col = {"revenue": "revenue", "gross_profit": "gross_profit"}.get(metric, "operating_profit")
        if "margin" in ql:
            col = "gross_margin_pct" if "gross" in ql else "operating_margin_pct"
        sql = f"""SELECT month, ROUND({col}{',4' if 'pct' in col else ''}) AS {col}
                 FROM v_company_pnl_monthly WHERE is_complete=1 ORDER BY month"""
        return sql, f"Monthly {col.replace('_', ' ')}", {"type": "line", "x": "month", "y": [col]}
    sql = """SELECT CAST(year AS TEXT) AS year, ROUND(SUM(revenue)) AS revenue, ROUND(SUM(gross_profit)) AS gross_profit,
             ROUND(SUM(gross_profit)*1.0/SUM(revenue),4) AS gross_margin,
             ROUND(SUM(total_opex)) AS opex, ROUND(SUM(operating_profit)) AS operating_profit,
             ROUND(SUM(operating_profit)*1.0/SUM(revenue),4) AS operating_margin,
             SUM(is_complete) AS complete_months
             FROM v_company_pnl_monthly GROUP BY year ORDER BY year"""
    return sql, "Annual P&L summary", {"type": "bar", "x": "year", "y": ["revenue", "operating_profit"]}


def offline_narrative(df: pd.DataFrame, title: str, metric: str | None = None) -> str:
    if df.empty:
        return "No rows matched that question."
    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    label_col = df.columns[0]
    lines = [f"**{title}** — {len(df)} rows."]
    money_cols = [c for c in num_cols if not re.search(r"pct|margin|stores|months|items|price|nbr|year", c)]
    if metric in df.columns:
        money_cols = [metric]
    if money_cols and len(df) > 1 and label_col not in ("month", "year"):
        c = money_cols[-1]
        top = df.iloc[0]
        total = df[c].sum()
        share = top[c] / total if total else 0
        lines.append(f"- First: **{top[label_col]}** with {analytics.money(top[c])} {c.replace('_', ' ')} "
                     f"({share:.0%} of the rows shown).")
        lines.append(f"- Last: **{df.iloc[-1][label_col]}** with {analytics.money(df.iloc[-1][c])}.")
    elif label_col in ("month", "year") and num_cols:
        c = metric if metric in df.columns else [x for x in num_cols if x != "year"][-1]
        first, last = df.iloc[0], df.iloc[-1]
        fmt = (lambda v: f"{v:.1%}") if re.search(r"pct|margin", c) else (lambda v: analytics.money(v) if abs(v) >= 1000 else f"{v:,.2f}")
        lines.append(f"- {c.replace('_', ' ').title()} went from {fmt(first[c])} ({first[label_col]}) to {fmt(last[c])} ({last[label_col]}).")
        peak = df.loc[df[c].idxmax()]
        lines.append(f"- Peak: {fmt(peak[c])} in {peak[label_col]}.")
    lines.append("\n_Offline mode: add an LLM API key for richer, AI-written insights and free-form questions._")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# Main entry points
# ----------------------------------------------------------------------------
class FinanceAssistant:
    def __init__(self, db_path: Path = config.DB_PATH, llm: LLMClient | None = None):
        self.db_path = db_path
        self.llm = llm or LLMClient()
        self._schema: str | None = None

    @property
    def schema(self) -> str:
        if self._schema is None:
            self._schema = db.schema_description(self.db_path)
        return self._schema

    def ask(self, question: str) -> Answer:
        question = question.strip()
        try:
            if is_change_question(question):
                return self._explain_change(question)
            return self._sql_answer(question)
        except Exception as exc:  # surface errors in the UI instead of crashing
            return Answer(question, f"Sorry, I couldn't answer that: {exc}", "error", engine=self.llm.label)

    def _explain_change(self, question: str) -> Answer:
        a = analytics.analyze_change(question, self.db_path)
        if self.llm.available:
            text = self.llm.complete(
                prompts.ANALYST_PERSONA,
                prompts.EXPLAIN_CHANGE_USER.format(question=question, facts=analytics.facts_text(a)),
            )
        else:
            text = analytics.template_narrative(a)
        title = f"Operating profit bridge: {a['prior'].label} → {a['current'].label}"
        return Answer(question, text, "explain_change", data=a["bridge"], analysis=a,
                      chart={"type": "waterfall"}, title=title, engine=self.llm.label)

    def _sql_answer(self, question: str) -> Answer:
        if not self.llm.available:
            sql, title, chart = offline_sql(question, self.db_path)
            df = db.run_query(sql, self.db_path)
            metric = (chart.get("y") or [None])[-1]
            return Answer(question, offline_narrative(df, title, metric), "sql", sql=" ".join(sql.split()),
                          data=df, chart=chart, title=title, engine=self.llm.label)

        system = prompts.TEXT_TO_SQL_SYSTEM.format(schema=self.schema)
        spec = self.llm.complete_json(system, question)
        sql = spec.get("sql", "")
        try:
            df = db.run_query(sql, self.db_path)
        except Exception as err:  # one self-correction round
            spec = self.llm.complete_json(system, prompts.SQL_FIX_USER.format(question=question, sql=sql, error=err))
            sql = spec.get("sql", "")
            df = db.run_query(sql, self.db_path)

        shown = df.head(config.MAX_ROWS_TO_LLM)
        text = self.llm.complete(
            prompts.ANALYST_PERSONA,
            prompts.NARRATE_RESULT_USER.format(
                question=question, sql=sql, n_rows=len(df), shown=len(shown),
                table=shown.to_csv(index=False),
            ),
            max_tokens=600,
        )
        return Answer(question, text, "sql", sql=sql, data=df, chart=spec.get("chart") or {},
                      title=spec.get("title", ""), engine=self.llm.label)

    # ------------------------------------------------------------------
    def executive_summary(self, period_question: str = "latest month") -> tuple[str, dict, dict]:
        """Automated management report for a period vs prior period and vs last year."""
        a = analytics.analyze_change(period_question, self.db_path)
        yoy_q = period_question + " year over year"
        try:
            a_yoy = analytics.analyze_change(yoy_q, self.db_path)
        except ValueError:
            a_yoy = a
        if self.llm.available:
            text = self.llm.complete(
                prompts.ANALYST_PERSONA,
                prompts.EXEC_SUMMARY_USER.format(facts=analytics.facts_text(a), yoy_facts=analytics.facts_text(a_yoy)),
                max_tokens=1200,
            )
        else:
            text = offline_exec_summary(a, a_yoy)
        return text, a, a_yoy


def offline_exec_summary(a: dict, a_yoy: dict) -> str:
    pc, pp, py = a["pnl_current"], a["pnl_prior"], a_yoy["pnl_prior"]
    cl, pl, yl = a["current"].label, a["prior"].label, a_yoy["prior"].label
    m = analytics.money
    pch = analytics.pct_change
    bridge = a["bridge"][a["bridge"]["measure"] == "relative"].copy()
    bridge["abs"] = bridge["amount"].abs()
    drivers = bridge.sort_values("abs", ascending=False).head(3)
    lines = [
        f"### Executive summary — {cl}",
        f"Revenue was {m(pc['revenue'])} ({pch(pc['revenue'], pp['revenue'])} vs {pl}, "
        f"{pch(pc['revenue'], py['revenue'])} vs {yl}). Operating profit was {m(pc['operating_profit'])} "
        f"at a {pc['operating_margin_pct']:.1%} margin ({pch(pc['operating_profit'], pp['operating_profit'])} vs {pl}).",
        "",
        "### Financial performance",
        f"- **Revenue:** {m(pc['revenue'])} | vs {pl}: {pch(pc['revenue'], pp['revenue'])} | vs {yl}: {pch(pc['revenue'], py['revenue'])}",
        f"- **Gross margin:** {pc['gross_margin_pct']:.1%} (prior {pp['gross_margin_pct']:.1%}, LY {py['gross_margin_pct']:.1%})",
        f"- **Operating expenses:** {m(pc['total_opex'])} ({pch(pc['total_opex'], pp['total_opex'])} vs {pl})",
        f"- **Operating profit:** {m(pc['operating_profit'])} | vs {pl}: {pch(pc['operating_profit'], pp['operating_profit'])} | vs {yl}: {pch(pc['operating_profit'], py['operating_profit'])}",
        "",
        "### Key drivers (vs prior period)",
    ]
    lines += [f"- {r.step}: {'+' if r.amount > 0 else ''}{m(r.amount)}" for r in drivers.itertuples()]
    lines += [
        "",
        "### Risks & watch items",
        f"- Promo markdowns at {pc['markdown_pct']:.1%} of revenue (prior {pp['markdown_pct']:.1%}).",
        f"- Oil averaged ${pc['avg_oil_price']:.0f}/bbl — affects logistics cost and consumer demand in Ecuador.",
        "",
        "### Recommended actions",
        f"- Review the weakest product family: **{a['family_movers'].iloc[0]['name']}**.",
        f"- Investigate the store with the largest profit decline: **{a['store_movers'].iloc[0]['name']}**.",
    ]
    return "\n".join(lines)
