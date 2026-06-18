-- =============================================================================
-- Nifty 100 Financial Analytics Database Schema
-- Sprint 1 · Data Foundation
-- Engine: SQLite 3  |  11 tables  |  PRAGMA foreign_keys = ON
-- =============================================================================

PRAGMA foreign_keys = ON;
PRAGMA journal_mode  = WAL;
PRAGMA synchronous   = NORMAL;

-- ---------------------------------------------------------------------------
-- 1. sectors
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sectors (
    sector_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    sector_name TEXT    NOT NULL UNIQUE,
    nifty_index TEXT,                         -- e.g. "NIFTY BANK", "NIFTY IT"
    description TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------------
-- 2. companies   (92 rows)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS companies (
    company_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker       TEXT    NOT NULL UNIQUE,      -- NSE symbol, e.g. "RELIANCE"
    company_name TEXT    NOT NULL,
    bse_code     TEXT,                         -- 6-digit BSE scrip code
    nse_code     TEXT,                         -- same as ticker for most
    isin         TEXT    UNIQUE,               -- INE...
    sector_id    INTEGER,
    industry     TEXT,
    face_value   REAL,
    market_cap_cr REAL,
    is_nifty50   INTEGER NOT NULL DEFAULT 0 CHECK(is_nifty50 IN (0,1)),
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (sector_id) REFERENCES sectors(sector_id)
);
CREATE INDEX IF NOT EXISTS idx_companies_ticker    ON companies(ticker);
CREATE INDEX IF NOT EXISTS idx_companies_sector_id ON companies(sector_id);
CREATE INDEX IF NOT EXISTS idx_companies_bse_code  ON companies(bse_code);

-- ---------------------------------------------------------------------------
-- 3. profitandloss   (~1 276 rows; ~13.9 years/company)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS profitandloss (
    pl_id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id              INTEGER NOT NULL,
    year                    INTEGER NOT NULL,   -- fiscal year end, e.g. 2024
    revenue_cr              REAL,               -- Net Sales / Total Revenue
    raw_material_cr         REAL,
    change_in_inventory_cr  REAL,
    employee_cost_cr        REAL,
    other_expenses_cr       REAL,
    total_expenses_cr       REAL,
    ebitda_cr               REAL,               -- Operating Profit
    opm_pct                 REAL,               -- OPM %
    other_income_cr         REAL,
    depreciation_cr         REAL,
    ebit_cr                 REAL,
    interest_cr             REAL,
    pbt_cr                  REAL,
    tax_pct                 REAL,               -- Effective tax rate %
    tax_cr                  REAL,
    pat_cr                  REAL,               -- Profit After Tax
    minority_interest_cr    REAL,
    pat_after_minority_cr   REAL,
    basic_eps               REAL,
    diluted_eps             REAL,
    dividend_per_share      REAL,
    dividend_payout_pct     REAL,
    npm_pct                 REAL,               -- Net Profit Margin %
    source_file             TEXT,
    UNIQUE (company_id, year),
    FOREIGN KEY (company_id) REFERENCES companies(company_id)
        ON DELETE CASCADE ON UPDATE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_pl_company_year ON profitandloss(company_id, year);

-- ---------------------------------------------------------------------------
-- 4. balancesheet   (~1 312 rows)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS balancesheet (
    bs_id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id                  INTEGER NOT NULL,
    year                        INTEGER NOT NULL,
    -- LIABILITIES
    share_capital_cr            REAL,
    reserves_cr                 REAL,
    total_equity_cr             REAL,
    long_term_borrowings_cr     REAL,
    short_term_borrowings_cr    REAL,
    total_borrowings_cr         REAL,
    trade_payables_cr           REAL,
    other_liabilities_cr        REAL,
    total_liabilities_cr        REAL,
    -- ASSETS
    fixed_assets_cr             REAL,           -- Net Block
    cwip_cr                     REAL,           -- Capital Work-in-Progress
    intangible_assets_cr        REAL,
    investments_cr              REAL,
    inventory_cr                REAL,
    debtors_cr                  REAL,
    cash_equivalents_cr         REAL,
    loans_advances_cr           REAL,
    other_assets_cr             REAL,
    total_assets_cr             REAL,
    source_file                 TEXT,
    UNIQUE (company_id, year),
    FOREIGN KEY (company_id) REFERENCES companies(company_id)
        ON DELETE CASCADE ON UPDATE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_bs_company_year ON balancesheet(company_id, year);

-- ---------------------------------------------------------------------------
-- 5. cashflow   (~1 187 rows)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cashflow (
    cf_id               INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id          INTEGER NOT NULL,
    year                INTEGER NOT NULL,
    cfo_cr              REAL,    -- Cash from Operating Activity
    cfi_cr              REAL,    -- Cash from Investing Activity
    cff_cr              REAL,    -- Cash from Financing Activity
    net_cash_flow_cr    REAL,    -- Net Cash Flow (CFO + CFI + CFF)
    capex_cr            REAL,    -- Capital Expenditure (negative = outflow)
    free_cash_flow_cr   REAL,    -- FCF = CFO - abs(capex)
    source_file         TEXT,
    UNIQUE (company_id, year),
    FOREIGN KEY (company_id) REFERENCES companies(company_id)
        ON DELETE CASCADE ON UPDATE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cf_company_year ON cashflow(company_id, year);

-- ---------------------------------------------------------------------------
-- 6. stock_prices   (5 520 rows; 60 months × 92 companies)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stock_prices (
    price_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id      INTEGER NOT NULL,
    price_date      TEXT    NOT NULL,   -- ISO-8601 "YYYY-MM-DD"
    open_price      REAL,
    high_price      REAL,
    low_price       REAL,
    close_price     REAL,
    adj_close_price REAL,
    volume          INTEGER,
    market_cap_cr   REAL,
    pe_ratio        REAL,
    source_file     TEXT,
    UNIQUE (company_id, price_date),
    FOREIGN KEY (company_id) REFERENCES companies(company_id)
        ON DELETE CASCADE ON UPDATE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sp_company_date ON stock_prices(company_id, price_date);
CREATE INDEX IF NOT EXISTS idx_sp_date         ON stock_prices(price_date);

-- ---------------------------------------------------------------------------
-- 7. financial_ratios   (one row per company per year; computed in Sprint 2)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS financial_ratios (
    ratio_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id          INTEGER NOT NULL,
    year                INTEGER NOT NULL,
    pe_ratio            REAL,
    pb_ratio            REAL,
    ev_ebitda           REAL,
    roce_pct            REAL,    -- Return on Capital Employed
    roe_pct             REAL,    -- Return on Equity
    roa_pct             REAL,    -- Return on Assets
    debt_to_equity      REAL,
    current_ratio       REAL,
    quick_ratio         REAL,
    asset_turnover      REAL,
    interest_coverage   REAL,
    dividend_yield_pct  REAL,
    source_file         TEXT,
    UNIQUE (company_id, year),
    FOREIGN KEY (company_id) REFERENCES companies(company_id)
        ON DELETE CASCADE ON UPDATE CASCADE
);

-- ---------------------------------------------------------------------------
-- 8. analysis   (one row per company; analyst ratings & summaries)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analysis (
    analysis_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id      INTEGER NOT NULL UNIQUE,
    analyst_rating  TEXT,                     -- "BUY" / "SELL" / "HOLD"
    target_price    REAL,
    current_price   REAL,
    upside_pct      REAL,
    recommendation  TEXT,
    analysis_date   TEXT,
    summary         TEXT,
    source_file     TEXT,
    FOREIGN KEY (company_id) REFERENCES companies(company_id)
        ON DELETE CASCADE ON UPDATE CASCADE
);

-- ---------------------------------------------------------------------------
-- 9. documents   (annual reports, investor presentations, URLs)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS documents (
    doc_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id  INTEGER NOT NULL,
    doc_type    TEXT    NOT NULL,             -- "ANNUAL_REPORT", "PRESENTATION", "NOTICE"
    doc_year    INTEGER,
    doc_url     TEXT,
    description TEXT,
    source_file TEXT,
    FOREIGN KEY (company_id) REFERENCES companies(company_id)
        ON DELETE CASCADE ON UPDATE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_doc_company ON documents(company_id);

-- ---------------------------------------------------------------------------
-- 10. prosandcons
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS prosandcons (
    pc_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id  INTEGER NOT NULL,
    type        TEXT    NOT NULL CHECK (type IN ('PRO', 'CON')),
    description TEXT    NOT NULL,
    category    TEXT,                         -- "Growth", "Valuation", "Risk", etc.
    source_file TEXT,
    FOREIGN KEY (company_id) REFERENCES companies(company_id)
        ON DELETE CASCADE ON UPDATE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_pc_company ON prosandcons(company_id);

-- ---------------------------------------------------------------------------
-- 11. peer_groups
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS peer_groups (
    peer_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id       INTEGER NOT NULL,
    peer_company_id  INTEGER NOT NULL,
    group_name       TEXT,
    source_file      TEXT,
    UNIQUE (company_id, peer_company_id),
    FOREIGN KEY (company_id)      REFERENCES companies(company_id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (peer_company_id) REFERENCES companies(company_id)
        ON DELETE CASCADE ON UPDATE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_pg_company ON peer_groups(company_id);

-- ---------------------------------------------------------------------------
-- Audit table (internal – tracks every load run)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS _load_audit (
    audit_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name  TEXT    NOT NULL,
    source_file TEXT,
    rows_loaded INTEGER NOT NULL DEFAULT 0,
    rows_rejected INTEGER NOT NULL DEFAULT 0,
    load_status TEXT    NOT NULL DEFAULT 'PENDING',   -- PENDING/SUCCESS/PARTIAL/FAILED
    run_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    notes       TEXT
);
