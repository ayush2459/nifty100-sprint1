-- =============================================================================
-- notebooks/exploratory_queries.sql
-- Sprint 1 · Day 07 · Exploratory Queries
--
-- 10 queries to validate the data load and begin preliminary analysis.
-- All queries target nifty100.db.
-- Run:  sqlite3 nifty100.db < notebooks/exploratory_queries.sql
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- Q1 : Validate company count  (Exit criterion: should return 92)
-- ─────────────────────────────────────────────────────────────────────────────
.print "Q1 — Company count (expected: 92)"
SELECT COUNT(*)           AS total_companies,
       SUM(is_nifty50)    AS nifty50_count,
       COUNT(DISTINCT sector_id) AS sectors_covered
FROM   companies;


-- ─────────────────────────────────────────────────────────────────────────────
-- Q2 : Row counts across all core tables
-- ─────────────────────────────────────────────────────────────────────────────
.print ""
.print "Q2 — Core table row counts"
SELECT 'companies'        AS tbl, COUNT(*) AS rows FROM companies
UNION ALL
SELECT 'profitandloss',          COUNT(*)          FROM profitandloss
UNION ALL
SELECT 'balancesheet',           COUNT(*)          FROM balancesheet
UNION ALL
SELECT 'cashflow',               COUNT(*)          FROM cashflow
UNION ALL
SELECT 'stock_prices',           COUNT(*)          FROM stock_prices
UNION ALL
SELECT 'financial_ratios',       COUNT(*)          FROM financial_ratios
UNION ALL
SELECT 'analysis',               COUNT(*)          FROM analysis
UNION ALL
SELECT 'documents',              COUNT(*)          FROM documents
UNION ALL
SELECT 'prosandcons',            COUNT(*)          FROM prosandcons
UNION ALL
SELECT 'peer_groups',            COUNT(*)          FROM peer_groups
UNION ALL
SELECT 'sectors',                COUNT(*)          FROM sectors;


-- ─────────────────────────────────────────────────────────────────────────────
-- Q3 : FK integrity check  (Exit criterion: 0 rows)
-- ─────────────────────────────────────────────────────────────────────────────
.print ""
.print "Q3 — FK integrity check (expected: 0 rows)"
PRAGMA foreign_key_check;


-- ─────────────────────────────────────────────────────────────────────────────
-- Q4 : Year coverage per company – top 10 by data depth
-- ─────────────────────────────────────────────────────────────────────────────
.print ""
.print "Q4 — Companies with deepest P&L coverage"
SELECT  c.ticker,
        c.company_name,
        COUNT(p.year)           AS pnl_years,
        MIN(p.year)             AS first_year,
        MAX(p.year)             AS last_year
FROM    companies c
JOIN    profitandloss p USING (company_id)
GROUP   BY c.company_id
ORDER   BY pnl_years DESC
LIMIT   10;


-- ─────────────────────────────────────────────────────────────────────────────
-- Q5 : Companies with < 5 years of P&L data (need manual review on Day 06)
-- ─────────────────────────────────────────────────────────────────────────────
.print ""
.print "Q5 — Companies with fewer than 5 years of P&L data"
SELECT  c.ticker,
        c.company_name,
        s.sector_name,
        COUNT(p.year) AS pnl_years
FROM    companies c
LEFT    JOIN profitandloss p USING (company_id)
LEFT    JOIN sectors       s USING (sector_id)
GROUP   BY c.company_id
HAVING  pnl_years < 5
ORDER   BY pnl_years ASC, c.ticker;


-- ─────────────────────────────────────────────────────────────────────────────
-- Q6 : Top-10 companies by FY2024 revenue  (₹ Crore)
-- ─────────────────────────────────────────────────────────────────────────────
.print ""
.print "Q6 — Top 10 by revenue FY2024"
SELECT  c.ticker,
        c.company_name,
        s.sector_name,
        ROUND(p.revenue_cr, 2)   AS revenue_cr,
        ROUND(p.opm_pct,    2)   AS opm_pct,
        ROUND(p.pat_cr,     2)   AS pat_cr,
        ROUND(p.basic_eps,  2)   AS eps
FROM    profitandloss p
JOIN    companies c USING (company_id)
LEFT    JOIN sectors s USING (sector_id)
WHERE   p.year = (SELECT MAX(year) FROM profitandloss)
ORDER   BY revenue_cr DESC NULLS LAST
LIMIT   10;


-- ─────────────────────────────────────────────────────────────────────────────
-- Q7 : Sector summary for latest year – avg OPM and total revenue
-- ─────────────────────────────────────────────────────────────────────────────
.print ""
.print "Q7 — Sector summary (latest fiscal year)"
WITH latest AS (
    SELECT MAX(year) AS yr FROM profitandloss
)
SELECT  s.sector_name,
        COUNT(DISTINCT c.company_id)    AS company_count,
        ROUND(SUM(p.revenue_cr),   2)   AS total_revenue_cr,
        ROUND(AVG(p.opm_pct),      2)   AS avg_opm_pct,
        ROUND(AVG(p.pat_cr),       2)   AS avg_pat_cr,
        ROUND(SUM(p.pat_cr),       2)   AS total_pat_cr
FROM    profitandloss p
JOIN    companies   c USING (company_id)
JOIN    sectors     s USING (sector_id)
JOIN    latest      l ON p.year = l.yr
GROUP   BY s.sector_id
ORDER   BY total_revenue_cr DESC NULLS LAST;


-- ─────────────────────────────────────────────────────────────────────────────
-- Q8 : Balance-sheet health — Debt-to-Equity for latest year
-- ─────────────────────────────────────────────────────────────────────────────
.print ""
.print "Q8 — Top 10 most-leveraged companies (D/E ratio, latest year)"
WITH latest AS (
    SELECT MAX(year) AS yr FROM balancesheet
)
SELECT  c.ticker,
        c.company_name,
        s.sector_name,
        ROUND(b.total_borrowings_cr, 2) AS total_debt_cr,
        ROUND(b.total_equity_cr,     2) AS equity_cr,
        ROUND(b.total_borrowings_cr  /
              NULLIF(b.total_equity_cr, 0), 2) AS debt_to_equity
FROM    balancesheet b
JOIN    companies   c USING (company_id)
LEFT    JOIN sectors s USING (sector_id)
JOIN    latest      l ON b.year = l.yr
WHERE   b.total_equity_cr > 0
ORDER   BY debt_to_equity DESC NULLS LAST
LIMIT   10;


-- ─────────────────────────────────────────────────────────────────────────────
-- Q9 : Cash-flow quality — Free Cash Flow leaders (latest year)
-- ─────────────────────────────────────────────────────────────────────────────
.print ""
.print "Q9 — Top 10 Free-Cash-Flow generators (latest year)"
WITH latest AS (
    SELECT MAX(year) AS yr FROM cashflow
)
SELECT  c.ticker,
        c.company_name,
        ROUND(cf.cfo_cr,            2)  AS cfo_cr,
        ROUND(cf.cfi_cr,            2)  AS cfi_cr,
        ROUND(cf.free_cash_flow_cr, 2)  AS fcf_cr,
        ROUND(cf.net_cash_flow_cr,  2)  AS net_cash_cr
FROM    cashflow cf
JOIN    companies c USING (company_id)
JOIN    latest    l ON cf.year = l.yr
ORDER   BY fcf_cr DESC NULLS LAST
LIMIT   10;


-- ─────────────────────────────────────────────────────────────────────────────
-- Q10 : Stock-price trend snapshot — 5 most recent monthly closes
--        for 5 random Nifty 100 constituents
-- ─────────────────────────────────────────────────────────────────────────────
.print ""
.print "Q10 — Recent stock-price closes (sample: 5 companies × 5 dates)"
SELECT  c.ticker,
        sp.price_date,
        ROUND(sp.close_price,  2) AS close_price,
        ROUND(sp.market_cap_cr,2) AS market_cap_cr,
        ROUND(sp.pe_ratio,     2) AS pe_ratio
FROM    stock_prices sp
JOIN    companies    c USING (company_id)
WHERE   c.company_id IN (
            SELECT company_id FROM companies
            ORDER BY RANDOM()
            LIMIT 5
        )
ORDER   BY c.ticker, sp.price_date DESC
LIMIT   25;


-- ─────────────────────────────────────────────────────────────────────────────
-- Summary banner
-- ─────────────────────────────────────────────────────────────────────────────
.print ""
.print "═══════════════════════════════════════════════════════"
.print " Sprint 1 exploratory queries complete."
.print " Review Q3 (FK check) and Q5 (sparse coverage) outputs."
.print "═══════════════════════════════════════════════════════"
