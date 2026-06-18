"""
tests/etl/test_validator.py
===========================
Unit tests for src/etl/validator.py

Each DQ rule is tested with:
  • A "clean" fixture that produces 0 violations.
  • One or more "dirty" fixtures that produce the expected violations.

All tests use an in-memory SQLite database populated with minimal fixture
data – no files are read from disk.

Run with:
    pytest tests/etl/test_validator.py -v
"""

import sqlite3
from pathlib import Path

import pytest

from src.etl.validator import DataQualityValidator, Violation


# ===========================================================================
# Fixtures
# ===========================================================================

SCHEMA_PATH = Path(__file__).parents[2] / "db" / "schema.sql"


def _make_db() -> sqlite3.Connection:
    """Return an empty in-memory DB with schema applied."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    schema = SCHEMA_PATH.read_text()
    conn.executescript(schema)
    return conn


def _seed_sector(conn, name="Technology") -> int:
    cur = conn.execute(
        "INSERT INTO sectors(sector_name) VALUES (?)", (name,)
    )
    conn.commit()
    return cur.lastrowid


def _seed_company(conn, ticker="TCS", sector_id=None, bse_code="532540") -> int:
    cur = conn.execute(
        """INSERT INTO companies(ticker, company_name, bse_code, sector_id)
           VALUES (?,?,?,?)""",
        (ticker, f"{ticker} Ltd", bse_code, sector_id),
    )
    conn.commit()
    return cur.lastrowid


def _seed_pnl(conn, company_id, year=2024, revenue=1000, ebitda=300,
              opm=30.0, pat=200, eps=50.0, tax_pct=25.0,
              dividend_payout=40.0):
    conn.execute(
        """INSERT INTO profitandloss
               (company_id, year, revenue_cr, ebitda_cr, opm_pct,
                pat_cr, basic_eps, tax_pct, dividend_payout_pct,
                pbt_cr, interest_cr)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (company_id, year, revenue, ebitda, opm,
         pat, eps, tax_pct, dividend_payout,
         pat / (1 - tax_pct / 100), 20),
    )
    conn.commit()


def _seed_bs(conn, company_id, year=2024,
             total_assets=1000, total_liabilities=600, total_equity=400,
             total_borrowings=400):
    conn.execute(
        """INSERT INTO balancesheet
               (company_id, year, total_assets_cr, total_liabilities_cr,
                total_equity_cr, total_borrowings_cr)
           VALUES (?,?,?,?,?,?)""",
        (company_id, year, total_assets, total_liabilities, total_equity,
         total_borrowings),
    )
    conn.commit()


def _seed_cf(conn, company_id, year=2024,
             cfo=300, cfi=-150, cff=-100, net_cash=50):
    conn.execute(
        """INSERT INTO cashflow
               (company_id, year, cfo_cr, cfi_cr, cff_cr, net_cash_flow_cr)
           VALUES (?,?,?,?,?,?)""",
        (company_id, year, cfo, cfi, cff, net_cash),
    )
    conn.commit()


@pytest.fixture
def clean_db():
    """Fully populated clean database – should produce 0 violations for most rules."""
    conn = _make_db()
    sid  = _seed_sector(conn)
    cid  = _seed_company(conn, ticker="TCS", sector_id=sid, bse_code="532540")
    for yr in range(2020, 2025):
        _seed_pnl(conn, cid, year=yr)
        _seed_bs(conn, cid, year=yr)
        _seed_cf(conn, cid, year=yr)
    return conn


# ===========================================================================
# DQ-01 : PK Uniqueness
# ===========================================================================

class TestDQ01:
    def test_clean_no_violations(self, clean_db):
        v = DataQualityValidator(clean_db)
        assert v.dq_01_pk_uniqueness() == []

    def test_duplicate_ticker_detected(self):
        # Use a schema WITHOUT the UNIQUE index on ticker so we can insert duplicates
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.executescript("""
            CREATE TABLE sectors  (sector_id INTEGER PRIMARY KEY, sector_name TEXT);
            CREATE TABLE companies (
                company_id  INTEGER PRIMARY KEY,
                ticker      TEXT NOT NULL,
                company_name TEXT NOT NULL,
                bse_code TEXT, nse_code TEXT, isin TEXT,
                sector_id INTEGER, industry TEXT, face_value REAL,
                market_cap_cr REAL, is_nifty50 INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );
        """)
        conn.execute("INSERT INTO companies(company_id,ticker,company_name) VALUES (1,'DUPE','A')")
        conn.execute("INSERT INTO companies(company_id,ticker,company_name) VALUES (2,'DUPE','B')")
        conn.commit()
        v = DataQualityValidator(conn)
        violations = v.dq_01_pk_uniqueness()
        assert any("DUPE" in (viol.ticker or "") or "DUPE" in viol.message
                   for viol in violations)


# ===========================================================================
# DQ-02 : Composite PK
# ===========================================================================

class TestDQ02:
    def test_clean_no_violations(self, clean_db):
        v = DataQualityValidator(clean_db)
        assert v.dq_02_composite_pk() == []

    def test_duplicate_company_year_detected(self):
        # Build a schema WITHOUT the UNIQUE(company_id,year) constraint on P&L
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.executescript("""
            CREATE TABLE sectors  (sector_id INTEGER PRIMARY KEY, sector_name TEXT);
            CREATE TABLE companies (
                company_id INTEGER PRIMARY KEY, ticker TEXT NOT NULL UNIQUE,
                company_name TEXT, bse_code TEXT, nse_code TEXT, isin TEXT,
                sector_id INTEGER, industry TEXT, face_value REAL,
                market_cap_cr REAL, is_nifty50 INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE profitandloss (
                pl_id      INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                year       INTEGER NOT NULL,
                revenue_cr REAL
                -- deliberately NO UNIQUE(company_id, year)
            );
            CREATE TABLE balancesheet (bs_id INTEGER PRIMARY KEY, company_id INTEGER, year INTEGER);
            CREATE TABLE cashflow     (cf_id INTEGER PRIMARY KEY, company_id INTEGER, year INTEGER);
        """)
        conn.execute("INSERT INTO companies(company_id,ticker,company_name) VALUES (1,'DUP2','Dup Co')")
        conn.execute("INSERT INTO profitandloss(company_id,year,revenue_cr) VALUES (1,2023,1000)")
        conn.execute("INSERT INTO profitandloss(company_id,year,revenue_cr) VALUES (1,2023,999)")
        conn.commit()
        v = DataQualityValidator(conn)
        violations = v.dq_02_composite_pk()
        assert len(violations) >= 1
        assert violations[0].year == 2023
        assert violations[0].severity == "CRITICAL"


# ===========================================================================
# DQ-03 : FK Integrity
# ===========================================================================

class TestDQ03:
    def test_clean_no_violations(self, clean_db):
        v = DataQualityValidator(clean_db)
        assert v.dq_03_fk_integrity() == []

    def test_orphan_pnl_row_detected(self):
        conn = _make_db()
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            "INSERT INTO profitandloss(company_id, year, revenue_cr) VALUES (999, 2024, 100)"
        )
        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")
        v = DataQualityValidator(conn)
        violations = v.dq_03_fk_integrity()
        assert len(violations) >= 1
        assert violations[0].severity == "CRITICAL"


# ===========================================================================
# DQ-04 : BS Balance
# ===========================================================================

class TestDQ04:
    def test_balanced_bs_no_violation(self, clean_db):
        v = DataQualityValidator(clean_db)
        assert v.dq_04_bs_balance() == []

    def test_imbalanced_bs_detected(self):
        conn = _make_db()
        sid  = _seed_sector(conn)
        cid  = _seed_company(conn, "IMBAL", sid)
        # assets=1000 but L+E=500 → 50% imbalance (well above 1% threshold)
        _seed_bs(conn, cid, total_assets=1000,
                 total_liabilities=300, total_equity=200,
                 total_borrowings=200)
        v = DataQualityValidator(conn)
        violations = v.dq_04_bs_balance()
        assert len(violations) == 1
        assert violations[0].severity == "WARNING"
        assert "imbalance" in violations[0].message.lower()


# ===========================================================================
# DQ-05 : OPM Cross-check
# ===========================================================================

class TestDQ05:
    def test_correct_opm_no_violation(self, clean_db):
        v = DataQualityValidator(clean_db)
        assert v.dq_05_opm_crosscheck() == []

    def test_wrong_opm_detected(self):
        conn = _make_db()
        sid  = _seed_sector(conn)
        cid  = _seed_company(conn, "OMISAL", sid)
        # Real OPM = 200/1000 = 20% but stored as 35%
        conn.execute(
            """INSERT INTO profitandloss(company_id, year, revenue_cr, ebitda_cr, opm_pct)
               VALUES (?,2024,1000,200,35.0)""", (cid,)
        )
        conn.commit()
        v = DataQualityValidator(conn)
        violations = v.dq_05_opm_crosscheck()
        assert len(violations) == 1
        assert "OPM" in violations[0].message


# ===========================================================================
# DQ-06 : Positive Sales
# ===========================================================================

class TestDQ06:
    def test_positive_revenue_no_violation(self, clean_db):
        v = DataQualityValidator(clean_db)
        assert v.dq_06_positive_sales() == []

    def test_zero_revenue_detected(self):
        conn = _make_db()
        sid  = _seed_sector(conn)
        cid  = _seed_company(conn, "ZERO", sid)
        conn.execute(
            "INSERT INTO profitandloss(company_id, year, revenue_cr) VALUES (?,2024,0)",
            (cid,),
        )
        conn.commit()
        v = DataQualityValidator(conn)
        violations = v.dq_06_positive_sales()
        assert len(violations) == 1
        assert violations[0].severity == "CRITICAL"

    def test_null_revenue_detected(self):
        conn = _make_db()
        sid  = _seed_sector(conn)
        cid  = _seed_company(conn, "NULLREV", sid)
        conn.execute(
            "INSERT INTO profitandloss(company_id, year, revenue_cr) VALUES (?,2024,NULL)",
            (cid,),
        )
        conn.commit()
        v = DataQualityValidator(conn)
        violations = v.dq_06_positive_sales()
        assert len(violations) == 1


# ===========================================================================
# DQ-07 : Net-Cash Reconciliation
# ===========================================================================

class TestDQ07:
    def test_balanced_cashflow_no_violation(self, clean_db):
        v = DataQualityValidator(clean_db)
        assert v.dq_07_netcash_reconcile() == []

    def test_cashflow_mismatch_detected(self):
        conn = _make_db()
        sid  = _seed_sector(conn)
        cid  = _seed_company(conn, "CFLOW", sid)
        # CFO+CFI+CFF = 50 but net stored as 200 → large mismatch
        _seed_cf(conn, cid, cfo=200, cfi=-100, cff=-50, net_cash=200)
        v = DataQualityValidator(conn)
        violations = v.dq_07_netcash_reconcile()
        assert len(violations) == 1
        assert "CFO+CFI+CFF" in violations[0].message


# ===========================================================================
# DQ-08 : Tax-Rate Sanity
# ===========================================================================

class TestDQ08:
    def test_normal_tax_rate_no_violation(self, clean_db):
        v = DataQualityValidator(clean_db)
        assert v.dq_08_tax_rate_sanity() == []

    def test_excessive_tax_rate_detected(self):
        conn = _make_db()
        sid  = _seed_sector(conn)
        cid  = _seed_company(conn, "HIGHTAX", sid)
        conn.execute(
            """INSERT INTO profitandloss(company_id, year, revenue_cr, pbt_cr, tax_pct)
               VALUES (?,2024,1000,300,75.0)""", (cid,)
        )
        conn.commit()
        v = DataQualityValidator(conn)
        violations = v.dq_08_tax_rate_sanity()
        assert len(violations) == 1
        assert violations[0].severity == "WARNING"

    def test_negative_tax_rate_on_profit_detected(self):
        conn = _make_db()
        sid  = _seed_sector(conn)
        cid  = _seed_company(conn, "NEGTAX", sid)
        conn.execute(
            """INSERT INTO profitandloss(company_id, year, revenue_cr, pbt_cr, tax_pct)
               VALUES (?,2024,1000,300,-5.0)""", (cid,)
        )
        conn.commit()
        v = DataQualityValidator(conn)
        violations = v.dq_08_tax_rate_sanity()
        assert len(violations) == 1


# ===========================================================================
# DQ-09 : Dividend Cap
# ===========================================================================

class TestDQ09:
    def test_normal_dividend_no_violation(self, clean_db):
        v = DataQualityValidator(clean_db)
        assert v.dq_09_dividend_cap() == []

    def test_excessive_dividend_detected(self):
        conn = _make_db()
        sid  = _seed_sector(conn)
        cid  = _seed_company(conn, "BIGDIV", sid)
        # Dividend payout = 200% of PAT
        conn.execute(
            """INSERT INTO profitandloss
                   (company_id, year, revenue_cr, pat_cr, dividend_payout_pct)
               VALUES (?,2024,1000,500,200.0)""", (cid,)
        )
        conn.commit()
        v = DataQualityValidator(conn)
        violations = v.dq_09_dividend_cap()
        assert len(violations) == 1
        assert "200.0%" in violations[0].message or "200" in violations[0].message


# ===========================================================================
# DQ-10 : URL Format
# ===========================================================================

class TestDQ10:
    def test_no_documents_no_violation(self, clean_db):
        v = DataQualityValidator(clean_db)
        assert v.dq_10_url_format() == []

    def test_valid_url_no_violation(self):
        conn = _make_db()
        sid  = _seed_sector(conn)
        cid  = _seed_company(conn, "URLTST", sid)
        conn.execute(
            "INSERT INTO documents(company_id, doc_type, doc_url) VALUES (?,?,?)",
            (cid, "ANNUAL_REPORT", "https://example.com/report.pdf"),
        )
        conn.commit()
        v = DataQualityValidator(conn)
        assert v.dq_10_url_format() == []

    def test_invalid_url_detected(self):
        conn = _make_db()
        sid  = _seed_sector(conn)
        cid  = _seed_company(conn, "BADURL", sid)
        conn.execute(
            "INSERT INTO documents(company_id, doc_type, doc_url) VALUES (?,?,?)",
            (cid, "ANNUAL_REPORT", "not-a-url"),
        )
        conn.commit()
        v = DataQualityValidator(conn)
        violations = v.dq_10_url_format()
        assert len(violations) == 1
        assert violations[0].severity == "INFO"


# ===========================================================================
# DQ-11 : EPS Sign Consistency
# ===========================================================================

class TestDQ11:
    def test_matching_signs_no_violation(self, clean_db):
        v = DataQualityValidator(clean_db)
        assert v.dq_11_eps_sign() == []

    def test_positive_pat_negative_eps_detected(self):
        conn = _make_db()
        sid  = _seed_sector(conn)
        cid  = _seed_company(conn, "EPSBAD", sid)
        conn.execute(
            """INSERT INTO profitandloss(company_id, year, revenue_cr, pat_cr, basic_eps)
               VALUES (?,2024,1000,200,-5.0)""", (cid,)
        )
        conn.commit()
        v = DataQualityValidator(conn)
        violations = v.dq_11_eps_sign()
        assert len(violations) == 1
        assert "sign mismatch" in violations[0].message.lower()


# ===========================================================================
# DQ-12 : BSE Code Format
# ===========================================================================

class TestDQ12:
    def test_valid_bse_code_no_violation(self, clean_db):
        v = DataQualityValidator(clean_db)
        assert v.dq_12_bse_code_format() == []

    def test_short_bse_code_detected(self):
        conn = _make_db()
        sid  = _seed_sector(conn)
        _seed_company(conn, "SHORTBSE", sid, bse_code="5325")
        v = DataQualityValidator(conn)
        violations = v.dq_12_bse_code_format()
        assert len(violations) == 1
        assert violations[0].severity == "INFO"

    def test_alpha_bse_code_detected(self):
        conn = _make_db()
        sid  = _seed_sector(conn)
        _seed_company(conn, "ALPHABSE", sid, bse_code="ABCDEF")
        v = DataQualityValidator(conn)
        violations = v.dq_12_bse_code_format()
        assert len(violations) == 1


# ===========================================================================
# DQ-13 : Year Coverage
# ===========================================================================

class TestDQ13:
    def test_sufficient_coverage_no_violation(self, clean_db):
        v = DataQualityValidator(clean_db)
        assert v.dq_13_year_coverage() == []

    def test_insufficient_years_detected(self):
        conn = _make_db()
        sid  = _seed_sector(conn)
        cid  = _seed_company(conn, "SPARSE", sid)
        # Only 1 year of data – below the 3-year minimum
        _seed_pnl(conn, cid, year=2024)
        v = DataQualityValidator(conn)
        violations = v.dq_13_year_coverage()
        # Should flag profitandloss (1 year < 3 minimum)
        pnl_flags = [v2 for v2 in violations if v2.table_name == "profitandloss"]
        assert len(pnl_flags) >= 1


# ===========================================================================
# DQ-14 : Year Range
# ===========================================================================

class TestDQ14:
    def test_valid_years_no_violation(self, clean_db):
        v = DataQualityValidator(clean_db)
        assert v.dq_14_year_range() == []

    def test_year_too_old_detected(self):
        conn = _make_db()
        sid  = _seed_sector(conn)
        cid  = _seed_company(conn, "OLD", sid)
        conn.execute(
            "INSERT INTO profitandloss(company_id, year, revenue_cr) VALUES (?,?,?)",
            (cid, 1995, 500),
        )
        conn.commit()
        v = DataQualityValidator(conn)
        violations = v.dq_14_year_range()
        assert any(viol.year == 1995 for viol in violations)
        assert violations[0].severity == "CRITICAL"


# ===========================================================================
# DQ-15 : Non-Negative Debt
# ===========================================================================

class TestDQ15:
    def test_positive_debt_no_violation(self, clean_db):
        v = DataQualityValidator(clean_db)
        assert v.dq_15_nonnegative_debt() == []

    def test_negative_borrowings_detected(self):
        conn = _make_db()
        sid  = _seed_sector(conn)
        cid  = _seed_company(conn, "NEGDEBT", sid)
        conn.execute(
            """INSERT INTO balancesheet
                   (company_id, year, total_assets_cr, total_borrowings_cr)
               VALUES (?,2024,1000,-200)""", (cid,)
        )
        conn.commit()
        v = DataQualityValidator(conn)
        violations = v.dq_15_nonnegative_debt()
        assert len(violations) >= 1
        assert violations[0].severity == "WARNING"


# ===========================================================================
# DQ-16 : Field Completeness
# ===========================================================================

class TestDQ16:
    def test_complete_fields_no_violation(self, clean_db):
        v = DataQualityValidator(clean_db)
        assert v.dq_16_field_completeness() == []

    def test_null_revenue_in_recent_year_detected(self):
        conn = _make_db()
        sid  = _seed_sector(conn)
        cid  = _seed_company(conn, "NULLREV2", sid)
        for yr in range(2020, 2025):
            conn.execute(
                """INSERT INTO profitandloss(company_id, year, revenue_cr, pat_cr)
                   VALUES (?,?,?,?)""",
                (cid, yr, None if yr == 2023 else 1000, 200),
            )
        conn.commit()
        v = DataQualityValidator(conn)
        violations = v.dq_16_field_completeness()
        assert any(
            viol.year == 2023 and viol.field_name == "revenue_cr"
            for viol in violations
        )


# ===========================================================================
# Integration : run_all returns violations sorted by severity
# ===========================================================================

class TestRunAll:
    def test_run_all_returns_list(self, clean_db):
        v = DataQualityValidator(clean_db)
        result = v.run_all()
        assert isinstance(result, list)

    def test_run_all_sorted_by_severity(self, clean_db):
        """All CRITICAL violations must appear before WARNING before INFO."""
        conn = _make_db()
        sid  = _seed_sector(conn)
        cid  = _seed_company(conn, "MULTI", sid, bse_code="BADCODE")
        # DQ-06 CRITICAL: zero revenue
        conn.execute(
            "INSERT INTO profitandloss(company_id, year, revenue_cr) VALUES (?,2024,0)",
            (cid,),
        )
        conn.commit()
        v = DataQualityValidator(conn)
        result = v.run_all()

        sev_order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
        orders = [sev_order[viol.severity] for viol in result]
        assert orders == sorted(orders), "Violations not sorted by severity"

    def test_run_all_subset_rules(self, clean_db):
        """Passing a rule subset only runs those rules."""
        v = DataQualityValidator(clean_db)
        result = v.run_all(rules=["DQ-01", "DQ-06"])
        # Clean DB should produce no violations for these two rules
        assert result == []

    def test_write_csv_creates_file(self, clean_db, tmp_path):
        v = DataQualityValidator(clean_db)
        violations = v.run_all()
        out = tmp_path / "test_failures.csv"
        v.write_csv(violations, str(out))
        assert out.exists()
        lines = out.read_text().splitlines()
        # Header row always present
        assert "rule_id" in lines[0]
