-- Star schema for the Financial Reporting & BI Assistant (SQLite)
-- Grain: month x store (x product family). Built by src/etl.py.

DROP VIEW IF EXISTS v_company_pnl_monthly;
DROP VIEW IF EXISTS v_family_pnl_monthly;
DROP VIEW IF EXISTS v_store_pnl_monthly;
DROP TABLE IF EXISTS fact_sales_monthly;
DROP TABLE IF EXISTS fact_store_pnl_monthly;
DROP TABLE IF EXISTS fact_oil_monthly;
DROP TABLE IF EXISTS dim_holiday;
DROP TABLE IF EXISTS dim_month;
DROP TABLE IF EXISTS dim_store;

CREATE TABLE dim_store (
    store_nbr   INTEGER PRIMARY KEY,
    city        TEXT,
    state       TEXT,
    store_type  TEXT,      -- A..E
    cluster     INTEGER
);

CREATE TABLE dim_month (
    month          TEXT PRIMARY KEY,   -- 'YYYY-MM'
    year           INTEGER,
    quarter        TEXT,               -- 'YYYY-Qn'
    days_in_month  INTEGER,
    days_observed  INTEGER,
    is_complete    INTEGER             -- 1 if (almost) every day has data
);

CREATE TABLE dim_holiday (
    date         TEXT,
    month        TEXT,
    type         TEXT,
    locale       TEXT,
    locale_name  TEXT,
    description  TEXT,
    transferred  INTEGER
);

CREATE TABLE fact_oil_monthly (
    month          TEXT PRIMARY KEY,
    avg_oil_price  REAL
);

-- Revenue and product-level gross profit by store, family, month
CREATE TABLE fact_sales_monthly (
    month             TEXT,
    store_nbr         INTEGER,
    family            TEXT,
    sales             REAL,   -- revenue (actual)
    avg_promo_items   REAL,   -- avg daily # of items on promotion (actual)
    base_margin_rate  REAL,   -- modeled
    markdown          REAL,   -- modeled promo margin give-away
    cogs              REAL,   -- modeled
    gross_profit      REAL,   -- modeled
    PRIMARY KEY (month, store_nbr, family)
);

-- Full store P&L by month
CREATE TABLE fact_store_pnl_monthly (
    month             TEXT,
    store_nbr         INTEGER,
    revenue           REAL,
    cogs              REAL,
    markdown          REAL,
    gross_profit      REAL,
    transactions      REAL,   -- actual customer transactions
    avg_oil_price     REAL,   -- actual WTI oil price
    labor_cost        REAL,
    occupancy_cost    REAL,
    logistics_cost    REAL,
    overhead_cost     REAL,
    total_opex        REAL,
    operating_profit  REAL,
    PRIMARY KEY (month, store_nbr)
);

CREATE INDEX idx_sales_family ON fact_sales_monthly(family);
CREATE INDEX idx_sales_store ON fact_sales_monthly(store_nbr);

-- Company-level monthly P&L
CREATE VIEW v_company_pnl_monthly AS
SELECT
    p.month,
    m.year,
    m.quarter,
    m.is_complete,
    SUM(p.revenue)            AS revenue,
    SUM(p.cogs)               AS cogs,
    SUM(p.markdown)           AS markdown,
    SUM(p.gross_profit)       AS gross_profit,
    SUM(p.gross_profit) * 1.0 / NULLIF(SUM(p.revenue), 0) AS gross_margin_pct,
    SUM(p.labor_cost)         AS labor_cost,
    SUM(p.occupancy_cost)     AS occupancy_cost,
    SUM(p.logistics_cost)     AS logistics_cost,
    SUM(p.overhead_cost)      AS overhead_cost,
    SUM(p.total_opex)         AS total_opex,
    SUM(p.operating_profit)   AS operating_profit,
    SUM(p.operating_profit) * 1.0 / NULLIF(SUM(p.revenue), 0) AS operating_margin_pct,
    SUM(p.transactions)       AS transactions,
    AVG(p.avg_oil_price)      AS avg_oil_price
FROM fact_store_pnl_monthly p
JOIN dim_month m ON m.month = p.month
GROUP BY p.month, m.year, m.quarter, m.is_complete;

-- Product family monthly view
CREATE VIEW v_family_pnl_monthly AS
SELECT
    month,
    family,
    SUM(sales)        AS revenue,
    SUM(gross_profit) AS gross_profit,
    SUM(gross_profit) * 1.0 / NULLIF(SUM(sales), 0) AS gross_margin_pct,
    SUM(markdown)     AS markdown,
    AVG(avg_promo_items) AS avg_promo_items
FROM fact_sales_monthly
GROUP BY month, family;

-- Store P&L joined with store attributes
CREATE VIEW v_store_pnl_monthly AS
SELECT
    p.*,
    s.city,
    s.state,
    s.store_type,
    s.cluster,
    p.operating_profit * 1.0 / NULLIF(p.revenue, 0) AS operating_margin_pct
FROM fact_store_pnl_monthly p
JOIN dim_store s ON s.store_nbr = p.store_nbr;
