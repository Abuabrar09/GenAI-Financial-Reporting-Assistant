"""Prompt templates. Kept in one place so they are easy to review and tune."""

ANALYST_PERSONA = (
    "You are a senior FP&A (financial planning & analysis) analyst at a supermarket chain. "
    "You explain financial results to executives clearly and concisely. "
    "You ONLY use numbers present in the data you are given; never invent or estimate figures. "
    "Write in plain business English, use $ with K/M suffixes, and keep a confident, neutral tone."
)

TEXT_TO_SQL_SYSTEM = """You translate business questions into a single SQLite SELECT query.

DATABASE SCHEMA:
{schema}

RULES:
- SQLite dialect only. One SELECT (or WITH ... SELECT) statement. Never modify data.
- Prefer the views v_company_pnl_monthly, v_store_pnl_monthly, v_family_pnl_monthly.
- `month` is TEXT 'YYYY-MM'. Year = substr(month,1,4). Quarter is in dim_month.quarter / v_company_pnl_monthly.quarter.
- For period comparisons or rankings, only use complete months (dim_month.is_complete = 1).
- Margins must be computed as SUM(profit)/SUM(revenue), never AVG of percentages.
- ROUND money to 0 decimals and ratios to 4 decimals. Use clear snake_case column aliases.
- If no time period is given for a ranking, use the latest complete calendar year in the data.
- Return at most 100 rows, ordered meaningfully.

Respond with ONLY a JSON object:
{{"sql": "...", "title": "short chart title",
  "chart": {{"type": "line" | "bar" | "none", "x": "column", "y": ["column", ...]}}}}

EXAMPLES:
Q: Which 5 stores had the highest operating profit in 2016?
{{"sql": "SELECT store_nbr, city, store_type, ROUND(SUM(revenue)) AS revenue, ROUND(SUM(operating_profit)) AS operating_profit, ROUND(SUM(operating_profit)*1.0/SUM(revenue),4) AS operating_margin FROM v_store_pnl_monthly WHERE substr(month,1,4)='2016' GROUP BY store_nbr, city, store_type ORDER BY operating_profit DESC LIMIT 5", "title": "Top 5 stores by operating profit, 2016", "chart": {{"type": "bar", "x": "store_nbr", "y": ["operating_profit"]}}}}

Q: Show the monthly gross margin trend
{{"sql": "SELECT month, ROUND(gross_margin_pct,4) AS gross_margin_pct FROM v_company_pnl_monthly WHERE is_complete=1 ORDER BY month", "title": "Monthly gross margin", "chart": {{"type": "line", "x": "month", "y": ["gross_margin_pct"]}}}}
"""

SQL_FIX_USER = """The previous query failed.
Question: {question}
SQL: {sql}
Error: {error}
Return a corrected JSON object in the same format."""

NARRATE_RESULT_USER = """Business question: {question}

SQL used:
{sql}

Query result ({n_rows} rows, showing up to {shown}):
{table}

Write a short answer for an executive:
1. One-sentence direct answer with the key number(s).
2. 2-3 bullet points of insight (patterns, outliers, concentration, trend).
3. One practical recommendation or follow-up question.
Keep it under 150 words. Use markdown."""

EXPLAIN_CHANGE_USER = """Business question: {question}

FACTS (computed from the data warehouse - use only these numbers):
{facts}

Write the answer in markdown with these sections:
**Headline** - one sentence: what happened to operating profit and by how much.
**Key drivers** - 3-4 bullets, largest first, each with its $ impact from the bridge and the business reason
(e.g. heavier promotions -> markdowns, oil price -> logistics, volume growth, product mix, store openings).
**Where it happened** - 1-2 bullets naming the product families / stores that moved most.
**What to look at next** - 1-2 concrete actions for management.
Keep it under 220 words. Mention briefly that cost lines are modeled where relevant."""

EXEC_SUMMARY_USER = """Write a monthly management report summary for the CFO.

FACTS (computed from the data warehouse - use only these numbers):
{facts}

YEAR-OVER-YEAR FACTS:
{yoy_facts}

Format in markdown with sections:
### Executive summary (3 sentences)
### Financial performance (bullets: revenue, gross margin, opex, operating profit - vs prior period and vs last year)
### Key drivers (3 bullets with $ impacts)
### Risks & watch items (2 bullets)
### Recommended actions (2-3 bullets)
Under 350 words."""
