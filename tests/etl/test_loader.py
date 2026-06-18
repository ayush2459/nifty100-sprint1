"""
tests/etl/test_loader.py
========================
Unit tests for src/etl/loader.py

Covers:
    AuditRecord            – dataclass serialisation
    _alias()               – column-name aliasing
    _is_year_col()         – year-column detection
    DataLoader             – schema init, company / sector inserts,
                             audit CSV generation, cache helpers

All tests are fully offline (no Google Sheets, no real Excel files).
Fake DataFrames and in-memory SQLite are used throughout.

Run with:
    pytest tests/etl/test_loader.py -v
"""

import csv
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from src.etl.loader import (
    AuditRecord,
    DataLoader,
    _alias,
    _is_year_col,
    _norm_headers,
    LOAD_ORDER,
)

SCHEMA_PATH = Path(__file__).parents[2] / "db" / "schema.sql"


# ===========================================================================
# AuditRecord
# ===========================================================================

class TestAuditRecord:
    def test_defaults(self):
        ar = AuditRecord(table_name="companies", source_file="data/companies.xlsx")
        assert ar.rows_loaded   == 0
        assert ar.rows_rejected == 0
        assert ar.load_status   == "PENDING"
        assert ar.notes         == ""

    def test_to_dict_has_all_keys(self):
        ar = AuditRecord(table_name="profitandloss", source_file="pl.xlsx",
                         rows_loaded=100, rows_rejected=2, load_status="PARTIAL")
        d = ar.to_dict()
        for key in ("table_name", "source_file", "rows_loaded", "rows_rejected",
                    "load_status", "run_at", "notes"):
            assert key in d

    def test_to_dict_values(self):
        ar = AuditRecord(table_name="cashflow", source_file="cf.xlsx",
                         rows_loaded=50, load_status="SUCCESS")
        d = ar.to_dict()
        assert d["table_name"]  == "cashflow"
        assert d["rows_loaded"] == 50
        assert d["load_status"] == "SUCCESS"


# ===========================================================================
# _alias()
# ===========================================================================

class TestAlias:
    def test_known_alias_resolved(self):
        alias_map = {"sales": "revenue_cr", "net profit": "pat_cr"}
        assert _alias("Sales", alias_map) == "revenue_cr"

    def test_case_insensitive(self):
        alias_map = {"total revenue": "revenue_cr"}
        assert _alias("Total Revenue", alias_map) == "revenue_cr"

    def test_unknown_key_passthrough(self):
        alias_map = {"sales": "revenue_cr"}
        assert _alias("SomeUnknownCol", alias_map) == "someunknowncol"

    def test_whitespace_stripped(self):
        alias_map = {"sales": "revenue_cr"}
        assert _alias("  Sales  ", alias_map) == "revenue_cr"


# ===========================================================================
# _is_year_col()
# ===========================================================================

class TestIsYearCol:
    @pytest.mark.parametrize("col", [
        "Mar 2024", "Mar-2024", "Jun 2020", "Dec 2019",
        "FY24", "FY2024",
        "2024", "2020",
    ])
    def test_year_columns_detected(self, col):
        assert _is_year_col(col) is True

    @pytest.mark.parametrize("col", [
        "ticker", "company_name", "sector", "metric", "particulars",
        "description", "revenue", "",
    ])
    def test_non_year_columns_rejected(self, col):
        assert _is_year_col(col) is False


# ===========================================================================
# _norm_headers()
# ===========================================================================

class TestNormHeaders:
    def test_aliases_applied(self):
        df = pd.DataFrame(columns=["Sales", "Net Profit", "ticker"])
        alias_map = {"sales": "revenue_cr", "net profit": "pat_cr"}
        result = _norm_headers(df, alias_map)
        assert "revenue_cr" in result.columns
        assert "pat_cr"     in result.columns
        assert "ticker"     in result.columns  # unknown → lowercased

    def test_original_df_not_mutated(self):
        df = pd.DataFrame(columns=["Sales"])
        _norm_headers(df, {"sales": "revenue_cr"})
        assert list(df.columns) == ["Sales"]


# ===========================================================================
# LOAD_ORDER
# ===========================================================================

class TestLoadOrder:
    def test_sectors_before_companies(self):
        assert LOAD_ORDER.index("sectors") < LOAD_ORDER.index("companies")

    def test_companies_before_financials(self):
        for tbl in ("profitandloss", "balancesheet", "cashflow", "stock_prices"):
            assert LOAD_ORDER.index("companies") < LOAD_ORDER.index(tbl), \
                f"companies must come before {tbl}"

    def test_all_core_tables_present(self):
        required = {
            "sectors", "companies", "profitandloss",
            "balancesheet", "cashflow", "stock_prices",
            "financial_ratios", "analysis", "documents",
            "prosandcons", "peer_groups",
        }
        assert required.issubset(set(LOAD_ORDER))


# ===========================================================================
# DataLoader – schema init
# ===========================================================================

class TestDataLoaderSchema:
    def test_schema_creates_companies_table(self):
        loader = DataLoader(db_path=":memory:", schema_path=str(SCHEMA_PATH))
        loader.connect()
        loader.init_schema()
        tables = {
            r[0] for r in loader.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "companies" in tables

    def test_schema_creates_all_core_tables(self):
        loader = DataLoader(db_path=":memory:", schema_path=str(SCHEMA_PATH))
        loader.connect()
        loader.init_schema()
        tables = {
            r[0] for r in loader.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for tbl in ("companies", "sectors", "profitandloss", "balancesheet",
                    "cashflow", "stock_prices", "financial_ratios",
                    "analysis", "documents", "prosandcons", "peer_groups"):
            assert tbl in tables, f"Missing table: {tbl}"

    def test_foreign_keys_enabled(self):
        loader = DataLoader(db_path=":memory:", schema_path=str(SCHEMA_PATH))
        loader.connect()
        loader.init_schema()
        fk = loader.conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1


# ===========================================================================
# DataLoader – company and sector caches
# ===========================================================================

class TestDataLoaderCaches:
    @pytest.fixture
    def loader_with_data(self):
        loader = DataLoader(db_path=":memory:", schema_path=str(SCHEMA_PATH))
        loader.connect()
        loader.init_schema()
        loader.conn.execute(
            "INSERT INTO sectors(sector_name) VALUES ('IT')"
        )
        loader.conn.execute(
            "INSERT INTO companies(ticker, company_name, sector_id) VALUES ('TCS','TCS Ltd',1)"
        )
        loader.conn.commit()
        return loader

    def test_company_cache_populated(self, loader_with_data):
        loader_with_data._refresh_company_cache()
        assert "TCS" in loader_with_data._company_id_cache

    def test_sector_cache_populated(self, loader_with_data):
        loader_with_data._refresh_sector_cache()
        assert "IT" in loader_with_data._sector_id_cache

    def test_company_id_is_integer(self, loader_with_data):
        loader_with_data._refresh_company_cache()
        cid = loader_with_data._company_id_cache["TCS"]
        assert isinstance(cid, int)


# ===========================================================================
# DataLoader – audit CSV
# ===========================================================================

class TestDataLoaderAuditCSV:
    def test_audit_csv_written(self, tmp_path):
        loader = DataLoader(db_path=":memory:", schema_path=str(SCHEMA_PATH))
        loader._audit = [
            AuditRecord("companies", "companies.xlsx", 92, 0, "SUCCESS"),
            AuditRecord("profitandloss", "pl.xlsx", 1276, 3, "PARTIAL"),
        ]
        out = tmp_path / "audit.csv"
        loader.write_audit_csv(str(out))
        assert out.exists()

    def test_audit_csv_has_correct_headers(self, tmp_path):
        loader = DataLoader(db_path=":memory:", schema_path=str(SCHEMA_PATH))
        loader._audit = [AuditRecord("companies", "f.xlsx", 10, 0, "SUCCESS")]
        out = tmp_path / "audit.csv"
        loader.write_audit_csv(str(out))
        with open(out) as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
        assert "table_name"    in headers
        assert "rows_loaded"   in headers
        assert "rows_rejected" in headers
        assert "load_status"   in headers

    def test_audit_csv_row_count(self, tmp_path):
        loader = DataLoader(db_path=":memory:", schema_path=str(SCHEMA_PATH))
        loader._audit = [
            AuditRecord("companies",     "c.xlsx",  92,   0, "SUCCESS"),
            AuditRecord("profitandloss", "pl.xlsx", 1276, 0, "SUCCESS"),
            AuditRecord("balancesheet",  "bs.xlsx", 1312, 0, "SUCCESS"),
        ]
        out = tmp_path / "audit3.csv"
        loader.write_audit_csv(str(out))
        with open(out) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 3

    def test_audit_csv_values_correct(self, tmp_path):
        loader = DataLoader(db_path=":memory:", schema_path=str(SCHEMA_PATH))
        loader._audit = [AuditRecord("cashflow", "cf.xlsx", 1187, 5, "PARTIAL")]
        out = tmp_path / "audit_cf.csv"
        loader.write_audit_csv(str(out))
        with open(out) as f:
            row = next(csv.DictReader(f))
        assert row["table_name"]    == "cashflow"
        assert row["rows_loaded"]   == "1187"
        assert row["rows_rejected"] == "5"
        assert row["load_status"]   == "PARTIAL"


# ===========================================================================
# DataLoader – close / connect lifecycle
# ===========================================================================

class TestDataLoaderLifecycle:
    def test_connect_sets_connection(self):
        loader = DataLoader(db_path=":memory:", schema_path=str(SCHEMA_PATH))
        loader.connect()
        assert loader.conn is not None

    def test_close_after_connect(self):
        loader = DataLoader(db_path=":memory:", schema_path=str(SCHEMA_PATH))
        loader.connect()
        loader.close()   # should not raise

    def test_double_close_safe(self):
        loader = DataLoader(db_path=":memory:", schema_path=str(SCHEMA_PATH))
        loader.connect()
        loader.close()
        loader.close()   # second close should not raise
