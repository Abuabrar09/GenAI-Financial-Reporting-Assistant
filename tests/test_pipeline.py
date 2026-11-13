"""End-to-end tests on a small synthetic dataset (no API keys or Kaggle download needed)."""
from __future__ import annotations

import json

import pytest

from src import analytics, db, etl, sample_data
from src.assistant import FinanceAssistant, is_change_question


@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("data")
    raw = sample_data.generate(tmp / "raw", start="2014-01-01", end="2016-12-31")
    path = tmp / "finance.db"
    etl.build(raw, path)
    return path


class FakeLLM:
    """Stands in for Claude/OpenAI so the LLM code path is tested deterministically."""

    available = True
    label = "fake"

    def __init__(self, sql_responses):
        self.sql_responses = list(sql_responses)
        self.prompts = []

    def complete(self, system, user, max_tokens=1200, temperature=0.2):
        self.prompts.append(user)
        return "**Answer** grounded in the facts."

    def complete_json(self, system, user, max_tokens=800):
        self.prompts.append(user)
        return json.loads(self.sql_responses.pop(0))


# --- SQL guardrails ----------------------------------------------------------
@pytest.mark.parametrize("bad", [
    "DROP TABLE dim_store",
    "SELECT 1; DELETE FROM dim_store",
    "UPDATE dim_store SET city='x'",
    "PRAGMA table_info(dim_store)",
    "ATTACH DATABASE 'x.db' AS x",
])
def test_unsafe_sql_rejected(bad):
    with pytest.raises(db.UnsafeSQLError):
        db.validate_sql(bad)


def test_safe_sql_runs(db_path):
    df = db.run_query("WITH t AS (SELECT * FROM dim_store) SELECT COUNT(*) n FROM t;", db_path)
    assert df["n"].iloc[0] == len(sample_data.STORES)


# --- Analytics -----------------------------------------------------------------
def test_bridge_reconciles(db_path):
    curr, prior = analytics.resolve_periods("2016 vs 2015", analytics.complete_months(db_path))
    bridge = analytics.profit_bridge(curr, prior, db_path)
    start, end = bridge["amount"].iloc[0], bridge["amount"].iloc[-1]
    steps = bridge.loc[bridge["measure"] == "relative", "amount"].sum()
    assert abs(start + steps - end) < 1.0


@pytest.mark.parametrize("q,curr,prior", [
    ("Why did operating profit decline in 2015?", "2015", "2014"),
    ("Explain Q3 2016 vs Q3 2015", "Q3 2016", "Q3 2015"),
    ("Q2 2016 profit change", "Q2 2016", "Q1 2016"),
    ("why did margin drop in April 2016", "Apr 2016", "2016-03"),
    ("Q1 2016 yoy", "Q1 2016", "Q1 2015"),
])
def test_period_parsing(db_path, q, curr, prior):
    c, p = analytics.resolve_periods(q, analytics.complete_months(db_path))
    assert (c.label, p.label) == (curr, prior)


def test_pnl_is_consistent(db_path):
    p = analytics.pnl(["2016-01", "2016-02", "2016-03"], db_path)
    assert p["revenue"] > 0
    assert abs(p["gross_profit"] - p["total_opex"] - p["operating_profit"]) < 1.0


# --- Assistant routing -----------------------------------------------------------
def test_change_question_detection():
    assert is_change_question("Why did operating profit decline?")
    assert is_change_question("revenue dropped in Q2, what happened")
    assert not is_change_question("Top 10 stores by revenue")


def test_offline_answers(db_path):
    fa = FinanceAssistant(db_path)
    fa.llm.provider = "offline"
    for q in ["Why did operating profit decline in 2015?", "Top 5 stores by revenue in 2016",
              "Revenue by product family", "monthly operating margin trend", "P&L by store type"]:
        ans = fa.ask(q)
        assert ans.kind != "error", ans.text
        assert ans.data is not None and not ans.data.empty


def test_llm_text_to_sql_with_self_correction(db_path):
    bad = json.dumps({"sql": "SELECT nope FROM missing_table", "chart": {}})
    good = json.dumps({"sql": "SELECT store_type, ROUND(SUM(revenue)) revenue FROM v_store_pnl_monthly GROUP BY 1",
                       "title": "Revenue by type", "chart": {"type": "bar", "x": "store_type", "y": ["revenue"]}})
    fa = FinanceAssistant(db_path, llm=FakeLLM([bad, good]))
    ans = fa.ask("Revenue by store type")
    assert ans.kind == "sql"
    assert list(ans.data.columns) == ["store_type", "revenue"]
    assert any("failed" in p for p in fa.llm.prompts)  # error was fed back to the model


def test_llm_explanation_is_grounded(db_path):
    fa = FinanceAssistant(db_path, llm=FakeLLM([]))
    ans = fa.ask("Why did operating profit change in 2016?")
    assert ans.kind == "explain_change"
    assert "OPERATING PROFIT BRIDGE" in fa.llm.prompts[-1]  # facts were passed to the model


def test_executive_summary_offline(db_path):
    fa = FinanceAssistant(db_path)
    fa.llm.provider = "offline"
    text, a, _ = fa.executive_summary("Q4 2016")
    assert "Executive summary" in text and a["current"].label == "Q4 2016"
