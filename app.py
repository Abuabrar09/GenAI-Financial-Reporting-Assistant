"""Generative AI Financial Reporting & Business Intelligence Assistant (Streamlit app).

Run:  streamlit run app.py
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src import analytics, config, cost_model, db
from src.assistant import Answer, FinanceAssistant
from src.etl import ensure_database

st.set_page_config(page_title="FinBI Assistant", page_icon="📊", layout="wide")

EXAMPLES = [
    "Why did operating profit decline in 2015?",
    "Explain the profit change in Q3 2016 vs Q3 2015",
    "Top 10 stores by operating profit in 2016",
    "Which product families drive the most gross profit?",
    "How do promotions affect gross margin?",
    "Show the monthly operating margin trend",
    "Compare P&L by store type",
    "How did oil prices affect logistics cost?",
]

COLORS = {"up": "#2E7D5B", "down": "#C0392B", "total": "#2F4B7C"}


# ---------------------------------------------------------------------------
# Setup (cached)
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner="Building the finance database (first run only)...")
def init() -> tuple[FinanceAssistant, str]:
    source = ensure_database(config.DB_PATH)
    if source == "existing":
        with db.connect() as con:
            n_stores = con.execute("SELECT COUNT(*) FROM dim_store").fetchone()[0]
        source = "kaggle" if n_stores >= 50 else "sample"
    return FinanceAssistant(config.DB_PATH), source


@st.cache_data
def months_info() -> pd.DataFrame:
    with db.connect() as con:
        return pd.read_sql_query("SELECT * FROM dim_month WHERE is_complete=1 ORDER BY month", con)


def fmt_pct(x: float) -> str:
    return f"{x:.1%}"


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------
def waterfall(bridge: pd.DataFrame, title: str = "") -> go.Figure:
    fig = go.Figure(go.Waterfall(
        x=bridge["step"], y=bridge["amount"], measure=bridge["measure"],
        text=[analytics.money(v) for v in bridge["amount"]], textposition="outside",
        increasing={"marker": {"color": COLORS["up"]}},
        decreasing={"marker": {"color": COLORS["down"]}},
        totals={"marker": {"color": COLORS["total"]}},
        connector={"line": {"color": "#999", "width": 1}},
    ))
    fig.update_layout(title=title, height=440, margin=dict(t=60, b=10, l=10, r=10),
                      yaxis_title="USD", showlegend=False)
    return fig


def auto_chart(ans: Answer):
    df, spec = ans.data, ans.chart or {}
    if df is None or df.empty:
        return None
    if spec.get("type") == "waterfall":
        return waterfall(df, ans.title)
    x = spec.get("x")
    ys = [y for y in (spec.get("y") or []) if y in df.columns]
    if x not in df.columns or not ys:
        # infer: first text/date column + numeric columns
        text_cols = [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])]
        num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        if not num_cols:
            return None
        x = text_cols[0] if text_cols else df.columns[0]
        ys = [c for c in num_cols if c != x][:2]
        spec = {"type": "line" if x == "month" else "bar"}
    plot_df = df.copy()
    plot_df[x] = plot_df[x].astype(str)
    if spec.get("type") == "line":
        fig = px.line(plot_df, x=x, y=ys, markers=len(plot_df) < 40, title=ans.title)
    elif spec.get("type") == "bar":
        fig = px.bar(plot_df, x=x, y=ys, barmode="group", title=ans.title)
    else:
        return None
    fig.update_layout(height=420, margin=dict(t=60, b=10, l=10, r=10), legend_title_text="")
    return fig


def render_answer(ans: Answer, key: str) -> None:
    st.markdown(ans.text.replace("$", r"\$"))
    fig = auto_chart(ans)
    if fig is not None:
        st.plotly_chart(fig, use_container_width=True, key=f"chart_{key}")
    if ans.kind == "explain_change" and ans.analysis:
        with st.expander("Biggest movers by product family and store"):
            c1, c2 = st.columns(2)
            c1.dataframe(ans.analysis["family_movers"], hide_index=True, use_container_width=True)
            c2.dataframe(ans.analysis["store_movers"], hide_index=True, use_container_width=True)
    if ans.sql:
        with st.expander("SQL & data behind this answer"):
            st.code(ans.sql, language="sql")
            st.dataframe(ans.data, hide_index=True, use_container_width=True)
            st.download_button("Download CSV", ans.data.to_csv(index=False), "result.csv",
                               "text/csv", key=f"dl_{key}")
    st.caption(f"Engine: {ans.engine}")


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
assistant, source = init()

with st.sidebar:
    st.title("📊 FinBI Assistant")
    st.caption("Generative AI financial reporting for a supermarket chain")
    st.markdown(f"**AI engine:** {assistant.llm.label}")
    if source == "kaggle":
        st.success("Data: Kaggle Corporación Favorita (54 stores, 2013–2017)")
    else:
        st.warning("Data: synthetic demo in Kaggle format. Add the Kaggle CSVs to data/raw for real data.")
    if not assistant.llm.available:
        st.info("Add ANTHROPIC_API_KEY or OPENAI_API_KEY to secrets for AI-written answers "
                "and free-form questions.")
    st.markdown("---")
    st.markdown("Built with Python · SQL (SQLite) · LLM API · Streamlit")

tab_ask, tab_summary, tab_explore, tab_data = st.tabs(
    ["💬 Ask your data", "📝 Executive summary", "📈 P&L explorer", "⚙️ Data & assumptions"]
)

# ---- Ask -------------------------------------------------------------------
with tab_ask:
    st.subheader("Ask a business question in plain English")
    if "history" not in st.session_state:
        st.session_state.history = []

    cols = st.columns(4)
    clicked = None
    for i, ex in enumerate(EXAMPLES):
        if cols[i % 4].button(ex, key=f"ex_{i}", use_container_width=True):
            clicked = ex

    question = st.chat_input("e.g. Why did operating profit decline in Q2 2016?")
    question = question or clicked
    if question:
        with st.spinner("Analyzing..."):
            st.session_state.history.insert(0, assistant.ask(question))

    for i, ans in enumerate(st.session_state.history):
        with st.chat_message("user"):
            st.markdown(ans.question)
        with st.chat_message("assistant"):
            render_answer(ans, key=str(len(st.session_state.history) - i))

# ---- Executive summary -------------------------------------------------------
with tab_summary:
    st.subheader("Automated management report")
    mi = months_info()
    c1, c2 = st.columns([1, 2])
    grain = c1.radio("Period type", ["Month", "Quarter", "Year"], horizontal=True)
    if grain == "Month":
        options = mi["month"].tolist()[::-1]
    elif grain == "Quarter":
        counts = mi.groupby("quarter").size()
        options = [q.replace("-Q", " Q") for q in counts[counts == 3].index.tolist()[::-1]]
        options = [f"Q{o.split(' Q')[1]} {o.split(' Q')[0]}" for o in options]
    else:
        counts = mi.groupby("year").size()
        options = [str(y) for y in counts[counts >= 11].index.tolist()[::-1]]
    period = c2.selectbox("Period", options)

    if st.button("Generate report", type="primary"):
        with st.spinner("Writing the report..."):
            text, a, a_yoy = assistant.executive_summary(period)
        pc, pp = a["pnl_current"], a["pnl_prior"]
        k = st.columns(4)
        k[0].metric("Revenue", analytics.money(pc["revenue"]), analytics.pct_change(pc["revenue"], pp["revenue"]))
        k[1].metric("Gross margin", fmt_pct(pc["gross_margin_pct"]),
                    f"{(pc['gross_margin_pct'] - pp['gross_margin_pct']) * 100:+.1f} pts")
        k[2].metric("Operating profit", analytics.money(pc["operating_profit"]),
                    analytics.pct_change(pc["operating_profit"], pp["operating_profit"]))
        k[3].metric("Operating margin", fmt_pct(pc["operating_margin_pct"]),
                    f"{(pc['operating_margin_pct'] - pp['operating_margin_pct']) * 100:+.1f} pts")
        st.caption(f"Compared with {a['prior'].label}")
        left, right = st.columns([1.1, 1])
        with left:
            st.markdown(text.replace("$", r"\$"))
            st.download_button("Download report (.md)", text, f"management_report_{period}.md")
        with right:
            st.plotly_chart(waterfall(a["bridge"], f"Operating profit bridge vs {a['prior'].label}"),
                            use_container_width=True)

# ---- Explorer -----------------------------------------------------------------
with tab_explore:
    st.subheader("Monthly P&L explorer")
    with db.connect() as con:
        types = [r[0] for r in con.execute("SELECT DISTINCT store_type FROM dim_store ORDER BY 1")]
        cities = [r[0] for r in con.execute("SELECT DISTINCT city FROM dim_store ORDER BY 1")]
    f1, f2, f3 = st.columns(3)
    sel_types = f1.multiselect("Store type", types, default=types)
    sel_cities = f2.multiselect("City", cities, default=[])
    metric = f3.selectbox("Metric", ["revenue", "gross_profit", "operating_profit", "total_opex",
                                    "logistics_cost", "markdown"])
    where = ["m.is_complete = 1"]
    params: list = []
    if sel_types:
        where.append(f"store_type IN ({','.join('?' * len(sel_types))})")
        params += sel_types
    if sel_cities:
        where.append(f"city IN ({','.join('?' * len(sel_cities))})")
        params += sel_cities
    sql = f"""SELECT v.month, SUM(revenue) revenue, SUM(gross_profit) gross_profit, SUM(markdown) markdown,
                     SUM(total_opex) total_opex, SUM(logistics_cost) logistics_cost,
                     SUM(operating_profit) operating_profit
              FROM v_store_pnl_monthly v JOIN dim_month m ON m.month = v.month
              WHERE {' AND '.join(where)} GROUP BY v.month ORDER BY v.month"""
    with db.connect() as con:
        trend = pd.read_sql_query(sql, con, params=params)
    if trend.empty:
        st.info("No data for these filters.")
    else:
        trend["operating_margin"] = trend["operating_profit"] / trend["revenue"]
        st.plotly_chart(px.line(trend, x="month", y=metric, title=metric.replace("_", " ").title()),
                        use_container_width=True)
        trend["year"] = trend["month"].str[:4]
        annual = trend.groupby("year")[["revenue", "gross_profit", "total_opex", "operating_profit"]].sum()
        annual["gross_margin"] = annual["gross_profit"] / annual["revenue"]
        annual["operating_margin"] = annual["operating_profit"] / annual["revenue"]
        st.markdown("**Annual P&L (complete months only)**")
        st.dataframe(annual.style.format({
            "revenue": "${:,.0f}", "gross_profit": "${:,.0f}", "total_opex": "${:,.0f}",
            "operating_profit": "${:,.0f}", "gross_margin": "{:.1%}", "operating_margin": "{:.1%}",
        }), use_container_width=True)

# ---- Data & assumptions ---------------------------------------------------------
with tab_data:
    st.subheader("Data source")
    st.markdown(
        "Kaggle **Store Sales – Time Series Forecasting** (Corporación Favorita, Ecuador): "
        "daily sales by store and product family, promotions, transactions, oil prices, holidays. "
        "Aggregated by the ETL into a monthly star schema in SQLite."
    )
    st.subheader("Cost model assumptions")
    st.caption("The dataset has revenue but no costs, so costs are modeled transparently:")
    st.dataframe(cost_model.assumptions_table(), hide_index=True, use_container_width=True)
    st.subheader("Database schema (what the LLM sees)")
    st.code(assistant.schema, language="sql")
