"""
loader.py
=========
ETL loader for the Nifty 100 financial analytics database.

Responsibilities
----------------
1. Read the 12 source Excel/CSV files (7 core + 5 supplementary).
2. Apply column-name aliases so the code handles slight header variations
   between different Screener.in export batches.
3. Normalise year, ticker, currency, and percentage values.
4. Insert records into SQLite in the correct FK-safe order.
5. Track per-table row counts and rejections in an in-memory audit log and
   write ``output/load_audit.csv`` on completion.

Usage
-----
    from src.etl.loader import DataLoader

    loader = DataLoader(db_path="nifty100.db", schema_path="db/schema.sql")
    loader.load_all(sources=SOURCE_MAP)   # SOURCE_MAP defined below
    loader.write_audit_csv("output/load_audit.csv")

Source file configuration is driven by SOURCE_MAP at module level so that
operators can swap file paths in the ``.env`` without touching this code.
"""

from __future__ import annotations

import csv
import logging
import os
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import pandas as pd

from src.etl.normaliser import (
    normalize_currency,
    normalize_date,
    normalize_percentage,
    normalize_ticker,
    normalize_year,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Source-file → table mapping
# Operators set actual paths in .env / Makefile; defaults shown here.
# ---------------------------------------------------------------------------
DEFAULT_SOURCE_MAP: Dict[str, str] = {
    # Core (7)
    "companies":        "data/raw/companies.xlsx",
    "profitandloss":    "data/raw/profit_loss.xlsx",
    "balancesheet":     "data/raw/balance_sheet.xlsx",
    "cashflow":         "data/raw/cash_flow.xlsx",
    "stock_prices":     "data/raw/stock_prices.xlsx",
    "financial_ratios": "data/raw/financial_ratios.xlsx",
    "sectors":          "data/raw/sectors.xlsx",
    # Supplementary (5)
    "analysis":         "data/raw/analysis.xlsx",
    "documents":        "data/raw/documents.xlsx",
    "prosandcons":      "data/raw/pros_cons.xlsx",
    "peer_groups":      "data/raw/peer_groups.xlsx",
    "quarterly":        "data/raw/quarterly_results.xlsx",   # optional / supplementary
}

# Canonical load order (FK-safe)
LOAD_ORDER = [
    "sectors",
    "companies",
    "profitandloss",
    "balancesheet",
    "cashflow",
    "stock_prices",
    "financial_ratios",
    "analysis",
    "documents",
    "prosandcons",
    "peer_groups",
]

# ---------------------------------------------------------------------------
# Column alias maps  (raw header → canonical name)
# ---------------------------------------------------------------------------

# -- companies --
_COMPANY_ALIASES: Dict[str, str] = {
    "ticker":        "ticker",
    "symbol":        "ticker",
    "nse symbol":    "ticker",
    "nse code":      "nse_code",
    "bse code":      "bse_code",
    "bse scrip":     "bse_code",
    "isin":          "isin",
    "name":          "company_name",
    "company name":  "company_name",
    "company":       "company_name",
    "sector":        "sector_name",
    "industry":      "industry",
    "face value":    "face_value",
    "market cap":    "market_cap_cr",
    "mcap":          "market_cap_cr",
    "nifty 50":      "is_nifty50",
    "in nifty 50":   "is_nifty50",
}

# -- profitandloss --
_PNL_ALIASES: Dict[str, str] = {
    "sales":                   "revenue_cr",
    "net sales":               "revenue_cr",
    "total revenue":           "revenue_cr",
    "revenue":                 "revenue_cr",
    "revenue from operations": "revenue_cr",
    "raw material consumed":   "raw_material_cr",
    "raw material cost":       "raw_material_cr",
    "material cost":           "raw_material_cr",
    "change in inventories":   "change_in_inventory_cr",
    "inventory change":        "change_in_inventory_cr",
    "employee cost":           "employee_cost_cr",
    "staff cost":              "employee_cost_cr",
    "employee benefit expense":"employee_cost_cr",
    "other expenses":          "other_expenses_cr",
    "other operating expense": "other_expenses_cr",
    "total expenses":          "total_expenses_cr",
    "operating profit":        "ebitda_cr",
    "ebitda":                  "ebitda_cr",
    "opm %":                   "opm_pct",
    "opm%":                    "opm_pct",
    "other income":            "other_income_cr",
    "depreciation":            "depreciation_cr",
    "d&a":                     "depreciation_cr",
    "ebit":                    "ebit_cr",
    "interest":                "interest_cr",
    "finance cost":            "interest_cr",
    "finance costs":           "interest_cr",
    "pbt":                     "pbt_cr",
    "profit before tax":       "pbt_cr",
    "tax %":                   "tax_pct",
    "tax%":                    "tax_pct",
    "effective tax rate":      "tax_pct",
    "net profit":              "pat_cr",
    "profit after tax":        "pat_cr",
    "pat":                     "pat_cr",
    "net income":              "pat_cr",
    "basic eps":               "basic_eps",
    "eps in rs":               "basic_eps",
    "eps":                     "basic_eps",
    "diluted eps":             "diluted_eps",
    "dividend payout %":       "dividend_payout_pct",
    "dividend payout":         "dividend_payout_pct",
    "dividend per share":      "dividend_per_share",
    "dps":                     "dividend_per_share",
    "net profit margin":       "npm_pct",
    "npm %":                   "npm_pct",
    "npm%":                    "npm_pct",
}

# -- balancesheet --
_BS_ALIASES: Dict[str, str] = {
    "share capital":            "share_capital_cr",
    "equity share capital":     "share_capital_cr",
    "reserves":                 "reserves_cr",
    "reserves and surplus":     "reserves_cr",
    "total equity":             "total_equity_cr",
    "shareholders equity":      "total_equity_cr",
    "net worth":                "total_equity_cr",
    "borrowings":               "total_borrowings_cr",
    "total borrowings":         "total_borrowings_cr",
    "long term borrowings":     "long_term_borrowings_cr",
    "lt borrowings":            "long_term_borrowings_cr",
    "short term borrowings":    "short_term_borrowings_cr",
    "st borrowings":            "short_term_borrowings_cr",
    "trade payables":           "trade_payables_cr",
    "other liabilities":        "other_liabilities_cr",
    "total liabilities":        "total_liabilities_cr",
    "fixed assets":             "fixed_assets_cr",
    "net block":                "fixed_assets_cr",
    "tangible assets":          "fixed_assets_cr",
    "cwip":                     "cwip_cr",
    "capital work in progress": "cwip_cr",
    "intangible assets":        "intangible_assets_cr",
    "investments":              "investments_cr",
    "inventory":                "inventory_cr",
    "inventories":              "inventory_cr",
    "debtors":                  "debtors_cr",
    "trade receivables":        "debtors_cr",
    "cash":                     "cash_equivalents_cr",
    "cash equivalents":         "cash_equivalents_cr",
    "cash and cash equivalents":"cash_equivalents_cr",
    "loans":                    "loans_advances_cr",
    "loans advances":           "loans_advances_cr",
    "loans and advances":       "loans_advances_cr",
    "other assets":             "other_assets_cr",
    "total assets":             "total_assets_cr",
}

# -- cashflow --
_CF_ALIASES: Dict[str, str] = {
    "cash from operating activity":  "cfo_cr",
    "cash from operations":          "cfo_cr",
    "operating cash flow":           "cfo_cr",
    "cfo":                           "cfo_cr",
    "cash from investing activity":  "cfi_cr",
    "cash from investing":           "cfi_cr",
    "investing cash flow":           "cfi_cr",
    "cfi":                           "cfi_cr",
    "cash from financing activity":  "cff_cr",
    "cash from financing":           "cff_cr",
    "financing cash flow":           "cff_cr",
    "cff":                           "cff_cr",
    "net cash flow":                 "net_cash_flow_cr",
    "net cash":                      "net_cash_flow_cr",
    "capex":                         "capex_cr",
    "capital expenditure":           "capex_cr",
    "free cash flow":                "free_cash_flow_cr",
    "fcf":                           "free_cash_flow_cr",
}

# -- stock_prices --
_PRICE_ALIASES: Dict[str, str] = {
    "date":        "price_date",
    "open":        "open_price",
    "high":        "high_price",
    "low":         "low_price",
    "close":       "close_price",
    "adj close":   "adj_close_price",
    "adjusted close": "adj_close_price",
    "volume":      "volume",
    "market cap":  "market_cap_cr",
    "pe":          "pe_ratio",
    "p/e":         "pe_ratio",
}

_ALL_ALIASES: Dict[str, Dict[str, str]] = {
    "profitandloss":    _PNL_ALIASES,
    "balancesheet":     _BS_ALIASES,
    "cashflow":         _CF_ALIASES,
    "stock_prices":     _PRICE_ALIASES,
}


# ===========================================================================
# Audit record
# ===========================================================================

@dataclass
class AuditRecord:
    table_name:    str
    source_file:   str
    rows_loaded:   int = 0
    rows_rejected: int = 0
    load_status:   str = "PENDING"     # PENDING | SUCCESS | PARTIAL | FAILED
    run_at:        str = field(default_factory=lambda: datetime.now().isoformat())
    notes:         str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "table_name":    self.table_name,
            "source_file":   self.source_file,
            "rows_loaded":   self.rows_loaded,
            "rows_rejected": self.rows_rejected,
            "load_status":   self.load_status,
            "run_at":        self.run_at,
            "notes":         self.notes,
        }


# ===========================================================================
# Helper utilities
# ===========================================================================

def _alias(raw_col: str, alias_map: Dict[str, str]) -> str:
    """Return canonical column name or original (lowercased, stripped)."""
    key = raw_col.strip().lower()
    return alias_map.get(key, key)


def _read_excel(path: str, sheet_name: int | str = 0) -> pd.DataFrame:
    """Read Excel or CSV, returning a DataFrame (empty on failure)."""
    p = Path(path)
    if not p.exists():
        log.warning("Source file not found: %s", path)
        return pd.DataFrame()
    try:
        if p.suffix.lower() in (".csv",):
            return pd.read_csv(path, dtype=str, keep_default_na=False)
        return pd.read_excel(path, sheet_name=sheet_name, dtype=str, keep_default_na=False)
    except Exception as exc:
        log.error("Cannot read %s: %s", path, exc)
        return pd.DataFrame()


def _norm_headers(df: pd.DataFrame, alias_map: Dict[str, str]) -> pd.DataFrame:
    """Rename columns using alias map; lower-strip raw headers first."""
    df = df.copy()
    df.columns = [_alias(c, alias_map) for c in df.columns]
    return df


def _is_year_col(col: str) -> bool:
    """True if col looks like a Screener-style year header ("Mar 2024", "FY24", etc.)."""
    col = col.strip()
    if re.fullmatch(r"\d{4}", col):
        return True
    if re.match(r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[- ]\d{4}", col, re.I):
        return True
    if re.match(r"FY\d{2,4}", col, re.I):
        return True
    return False


def _unpivot(df: pd.DataFrame, id_vars: List[str]) -> pd.DataFrame:
    """
    Detect pivot (wide) format and melt to long format.

    Wide format: rows = metrics, cols = years.
    Long format: rows = (ticker, year), cols = metrics.
    """
    year_cols = [c for c in df.columns if _is_year_col(c)]
    if not year_cols:
        return df                     # already long

    melted = df.melt(id_vars=id_vars, value_vars=year_cols,
                     var_name="year_raw", value_name="value")
    return melted


# ===========================================================================
# DataLoader
# ===========================================================================

class DataLoader:
    """Orchestrates the full ETL from source Excel files to SQLite."""

    def __init__(self, db_path: str = "nifty100.db", schema_path: str = "db/schema.sql"):
        self.db_path     = db_path
        self.schema_path = schema_path
        self.conn: Optional[sqlite3.Connection] = None
        self._audit: List[AuditRecord] = []
        self._company_id_cache: Dict[str, int] = {}   # ticker → company_id
        self._sector_id_cache:  Dict[str, int] = {}   # sector_name → sector_id

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self) -> None:
        log.info("Connecting to %s", self.db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.row_factory = sqlite3.Row

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            log.info("Database connection closed.")

    def init_schema(self) -> None:
        log.info("Initialising schema from %s", self.schema_path)
        with open(self.schema_path, "r") as fh:
            sql = fh.read()
        self.conn.executescript(sql)
        self.conn.commit()
        log.info("Schema initialised.")

    # ------------------------------------------------------------------
    # Orchestrator
    # ------------------------------------------------------------------

    def load_all(self, sources: Optional[Dict[str, str]] = None) -> None:
        sources = sources or DEFAULT_SOURCE_MAP
        self.connect()
        self.init_schema()

        for table in LOAD_ORDER:
            path = sources.get(table)
            if not path:
                log.warning("No source path configured for table '%s' – skipping.", table)
                continue
            loader_fn = getattr(self, f"_load_{table}", None)
            if loader_fn is None:
                log.warning("No loader implemented for '%s' – skipping.", table)
                continue
            log.info("▶  Loading %s  ←  %s", table, path)
            loader_fn(path)

        self._refresh_company_cache()
        self.conn.commit()
        log.info("✓  All tables loaded.")

    # ------------------------------------------------------------------
    # Table loaders
    # ------------------------------------------------------------------

    def _load_sectors(self, path: str) -> None:
        df = _read_excel(path)
        ar = AuditRecord(table_name="sectors", source_file=path)
        if df.empty:
            ar.load_status = "FAILED"; ar.notes = "File not found / empty"
            self._audit.append(ar); return

        df.columns = [c.strip().lower() for c in df.columns]
        for _, row in df.iterrows():
            sector = str(row.get("sector_name", row.get("sector", ""))).strip()
            if not sector:
                ar.rows_rejected += 1; continue
            try:
                self.conn.execute(
                    "INSERT OR IGNORE INTO sectors(sector_name, nifty_index, description) "
                    "VALUES (?,?,?)",
                    (sector,
                     str(row.get("nifty_index", "")).strip() or None,
                     str(row.get("description", "")).strip() or None),
                )
                ar.rows_loaded += 1
            except Exception as exc:
                log.debug("sectors insert error: %s", exc)
                ar.rows_rejected += 1

        self.conn.commit()
        ar.load_status = "SUCCESS" if ar.rows_rejected == 0 else "PARTIAL"
        self._audit.append(ar)
        self._refresh_sector_cache()
        log.info("   sectors: %d loaded, %d rejected", ar.rows_loaded, ar.rows_rejected)

    def _load_companies(self, path: str) -> None:
        df = _read_excel(path)
        ar = AuditRecord(table_name="companies", source_file=path)
        if df.empty:
            ar.load_status = "FAILED"; ar.notes = "File not found / empty"
            self._audit.append(ar); return

        df = _norm_headers(df, {c.strip().lower(): v for c, v in _COMPANY_ALIASES.items()})

        for _, row in df.iterrows():
            ticker_raw = row.get("ticker", row.get("nse_code", ""))
            if not str(ticker_raw).strip():
                ar.rows_rejected += 1; continue
            try:
                ticker = normalize_ticker(ticker_raw)
            except ValueError as exc:
                log.debug("ticker normalisation: %s", exc)
                ar.rows_rejected += 1; continue

            sector_name = str(row.get("sector_name", "")).strip() or None
            sector_id   = self._sector_id_cache.get(sector_name) if sector_name else None

            try:
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO companies
                        (ticker, company_name, bse_code, nse_code, isin,
                         sector_id, industry, face_value, market_cap_cr, is_nifty50)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        ticker,
                        str(row.get("company_name", ticker)).strip(),
                        str(row.get("bse_code", "")).strip() or None,
                        str(row.get("nse_code", ticker)).strip() or None,
                        str(row.get("isin", "")).strip() or None,
                        sector_id,
                        str(row.get("industry", "")).strip() or None,
                        normalize_currency(row.get("face_value")),
                        normalize_currency(row.get("market_cap_cr")),
                        1 if str(row.get("is_nifty50", "")).lower() in ("1", "yes", "y", "true", "x") else 0,
                    ),
                )
                ar.rows_loaded += 1
            except Exception as exc:
                log.debug("companies insert error [%s]: %s", ticker, exc)
                ar.rows_rejected += 1

        self.conn.commit()
        ar.load_status = "SUCCESS" if ar.rows_rejected == 0 else "PARTIAL"
        self._audit.append(ar)
        self._refresh_company_cache()
        log.info("   companies: %d loaded, %d rejected", ar.rows_loaded, ar.rows_rejected)

    def _load_financial_table(
        self,
        path: str,
        table: str,
        alias_map: Dict[str, str],
        insert_fn,
    ) -> None:
        """Generic wide-format loader for P&L / BS / CF."""
        df = _read_excel(path)
        ar = AuditRecord(table_name=table, source_file=path)
        if df.empty:
            ar.load_status = "FAILED"; ar.notes = "File not found / empty"
            self._audit.append(ar); return

        raw_cols = list(df.columns)
        # Detect whether ticker is a column or the first non-year column
        ticker_col = None
        for cname in raw_cols:
            if cname.strip().lower() in ("ticker", "symbol", "name", "company", "nse symbol"):
                ticker_col = cname
                break

        if ticker_col is None:
            # Try first column
            ticker_col = raw_cols[0]

        year_cols = [c for c in raw_cols if _is_year_col(c)]

        if year_cols:
            # --- Wide / pivot format ---
            id_vars = [ticker_col]
            metric_col = next(
                (c for c in raw_cols if c.strip().lower() in alias_map or c == raw_cols[1]),
                raw_cols[1] if len(raw_cols) > 1 else None,
            )
            # melt: (ticker, metric, year, value)
            id_cols = [c for c in raw_cols if not _is_year_col(c)]
            long_df = df.melt(id_vars=id_cols, value_vars=year_cols,
                              var_name="year_raw", value_name="raw_value")

            # Pivot so each metric is a column
            metric_key = next(
                (c for c in id_cols if c.strip().lower() in ("metric", "item", "particulars", "description")),
                None,
            )
            if metric_key:
                long_df["canonical_col"] = long_df[metric_key].str.strip().str.lower().map(
                    lambda k: alias_map.get(k, k)
                )
                try:
                    pivoted = long_df.pivot_table(
                        index=[ticker_col, "year_raw"],
                        columns="canonical_col",
                        values="raw_value",
                        aggfunc="first",
                    ).reset_index()
                except Exception:
                    pivoted = long_df   # fall back
            else:
                pivoted = long_df

            for _, row in pivoted.iterrows():
                ticker_raw = row.get(ticker_col, "")
                year_raw   = row.get("year_raw", "")
                try:
                    ticker  = normalize_ticker(ticker_raw)
                    year    = normalize_year(year_raw)
                    cid     = self._company_id_cache.get(ticker)
                    if cid is None:
                        ar.rows_rejected += 1; continue
                    insert_fn(row, cid, year, path, ar)
                except ValueError:
                    ar.rows_rejected += 1

        else:
            # --- Long / tidy format ---
            df = _norm_headers(df, alias_map)
            for _, row in df.iterrows():
                ticker_raw = row.get("ticker", row.get("symbol", ""))
                year_raw   = row.get("year", row.get("fiscal_year", ""))
                try:
                    ticker  = normalize_ticker(ticker_raw)
                    year    = normalize_year(year_raw)
                    cid     = self._company_id_cache.get(ticker)
                    if cid is None:
                        ar.rows_rejected += 1; continue
                    insert_fn(row, cid, year, path, ar)
                except ValueError:
                    ar.rows_rejected += 1

        self.conn.commit()
        ar.load_status = "SUCCESS" if ar.rows_rejected == 0 else "PARTIAL"
        self._audit.append(ar)
        log.info("   %s: %d loaded, %d rejected", table, ar.rows_loaded, ar.rows_rejected)

    # --- P&L ---
    def _load_profitandloss(self, path: str) -> None:
        def insert(row, cid, year, src, ar):
            g = lambda k: normalize_currency(row.get(k))
            p = lambda k: normalize_percentage(row.get(k))
            try:
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO profitandloss
                        (company_id, year, revenue_cr, raw_material_cr,
                         change_in_inventory_cr, employee_cost_cr, other_expenses_cr,
                         total_expenses_cr, ebitda_cr, opm_pct, other_income_cr,
                         depreciation_cr, ebit_cr, interest_cr, pbt_cr,
                         tax_pct, tax_cr, pat_cr, basic_eps, diluted_eps,
                         dividend_per_share, dividend_payout_pct, npm_pct, source_file)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (cid, year,
                     g("revenue_cr"), g("raw_material_cr"), g("change_in_inventory_cr"),
                     g("employee_cost_cr"), g("other_expenses_cr"), g("total_expenses_cr"),
                     g("ebitda_cr"), p("opm_pct"), g("other_income_cr"),
                     g("depreciation_cr"), g("ebit_cr"), g("interest_cr"), g("pbt_cr"),
                     p("tax_pct"), g("tax_cr"), g("pat_cr"),
                     normalize_percentage(row.get("basic_eps")),
                     normalize_percentage(row.get("diluted_eps")),
                     g("dividend_per_share"), p("dividend_payout_pct"),
                     p("npm_pct"), src),
                )
                ar.rows_loaded += 1
            except Exception as exc:
                log.debug("pnl insert error: %s", exc)
                ar.rows_rejected += 1

        self._load_financial_table(path, "profitandloss", _PNL_ALIASES, insert)

    # --- BS ---
    def _load_balancesheet(self, path: str) -> None:
        def insert(row, cid, year, src, ar):
            g = lambda k: normalize_currency(row.get(k))
            try:
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO balancesheet
                        (company_id, year, share_capital_cr, reserves_cr,
                         total_equity_cr, long_term_borrowings_cr, short_term_borrowings_cr,
                         total_borrowings_cr, trade_payables_cr, other_liabilities_cr,
                         total_liabilities_cr, fixed_assets_cr, cwip_cr,
                         intangible_assets_cr, investments_cr, inventory_cr,
                         debtors_cr, cash_equivalents_cr, loans_advances_cr,
                         other_assets_cr, total_assets_cr, source_file)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (cid, year,
                     g("share_capital_cr"), g("reserves_cr"), g("total_equity_cr"),
                     g("long_term_borrowings_cr"), g("short_term_borrowings_cr"),
                     g("total_borrowings_cr"), g("trade_payables_cr"), g("other_liabilities_cr"),
                     g("total_liabilities_cr"), g("fixed_assets_cr"), g("cwip_cr"),
                     g("intangible_assets_cr"), g("investments_cr"), g("inventory_cr"),
                     g("debtors_cr"), g("cash_equivalents_cr"), g("loans_advances_cr"),
                     g("other_assets_cr"), g("total_assets_cr"), src),
                )
                ar.rows_loaded += 1
            except Exception as exc:
                log.debug("bs insert error: %s", exc)
                ar.rows_rejected += 1

        self._load_financial_table(path, "balancesheet", _BS_ALIASES, insert)

    # --- CF ---
    def _load_cashflow(self, path: str) -> None:
        def insert(row, cid, year, src, ar):
            g = lambda k: normalize_currency(row.get(k))
            try:
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO cashflow
                        (company_id, year, cfo_cr, cfi_cr, cff_cr,
                         net_cash_flow_cr, capex_cr, free_cash_flow_cr, source_file)
                    VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    (cid, year, g("cfo_cr"), g("cfi_cr"), g("cff_cr"),
                     g("net_cash_flow_cr"), g("capex_cr"), g("free_cash_flow_cr"), src),
                )
                ar.rows_loaded += 1
            except Exception as exc:
                log.debug("cf insert error: %s", exc)
                ar.rows_rejected += 1

        self._load_financial_table(path, "cashflow", _CF_ALIASES, insert)

    # --- Stock Prices ---
    def _load_stock_prices(self, path: str) -> None:
        df = _read_excel(path)
        ar = AuditRecord(table_name="stock_prices", source_file=path)
        if df.empty:
            ar.load_status = "FAILED"; ar.notes = "File not found / empty"
            self._audit.append(ar); return

        df = _norm_headers(df, _PRICE_ALIASES)
        ticker_col = next((c for c in df.columns if c in ("ticker", "symbol", "company_id")), None)
        if ticker_col is None:
            df.columns = list(df.columns)

        for _, row in df.iterrows():
            ticker_raw = row.get("ticker", row.get("symbol", ""))
            try:
                ticker = normalize_ticker(ticker_raw)
                cid    = self._company_id_cache.get(ticker)
                if cid is None:
                    ar.rows_rejected += 1; continue
                date_str = normalize_date(row.get("price_date", row.get("date", "")))
                if not date_str:
                    ar.rows_rejected += 1; continue

                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO stock_prices
                        (company_id, price_date, open_price, high_price, low_price,
                         close_price, adj_close_price, volume, market_cap_cr, pe_ratio, source_file)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (cid, date_str,
                     normalize_currency(row.get("open_price")),
                     normalize_currency(row.get("high_price")),
                     normalize_currency(row.get("low_price")),
                     normalize_currency(row.get("close_price")),
                     normalize_currency(row.get("adj_close_price")),
                     int(float(row.get("volume", 0) or 0)),
                     normalize_currency(row.get("market_cap_cr")),
                     normalize_percentage(row.get("pe_ratio")),
                     path),
                )
                ar.rows_loaded += 1
            except Exception as exc:
                log.debug("prices insert error: %s", exc)
                ar.rows_rejected += 1

        self.conn.commit()
        ar.load_status = "SUCCESS" if ar.rows_rejected == 0 else "PARTIAL"
        self._audit.append(ar)
        log.info("   stock_prices: %d loaded, %d rejected", ar.rows_loaded, ar.rows_rejected)

    # --- Financial Ratios ---
    def _load_financial_ratios(self, path: str) -> None:
        df = _read_excel(path)
        ar = AuditRecord(table_name="financial_ratios", source_file=path)
        if df.empty:
            ar.load_status = "FAILED"; ar.notes = "File not found / empty"
            self._audit.append(ar); return

        df.columns = [c.strip().lower() for c in df.columns]
        for _, row in df.iterrows():
            ticker_raw = row.get("ticker", row.get("symbol", ""))
            year_raw   = row.get("year", row.get("fiscal_year", ""))
            try:
                ticker = normalize_ticker(ticker_raw)
                year   = normalize_year(year_raw)
                cid    = self._company_id_cache.get(ticker)
                if cid is None:
                    ar.rows_rejected += 1; continue

                p = lambda k: normalize_percentage(row.get(k))
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO financial_ratios
                        (company_id, year, pe_ratio, pb_ratio, ev_ebitda,
                         roce_pct, roe_pct, roa_pct, debt_to_equity,
                         current_ratio, quick_ratio, asset_turnover,
                         interest_coverage, dividend_yield_pct, source_file)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (cid, year,
                     p("pe_ratio"), p("pb_ratio"), p("ev_ebitda"),
                     p("roce_pct"), p("roe_pct"), p("roa_pct"),
                     p("debt_to_equity"), p("current_ratio"), p("quick_ratio"),
                     p("asset_turnover"), p("interest_coverage"), p("dividend_yield_pct"),
                     path),
                )
                ar.rows_loaded += 1
            except Exception as exc:
                log.debug("ratios insert error: %s", exc)
                ar.rows_rejected += 1

        self.conn.commit()
        ar.load_status = "SUCCESS" if ar.rows_rejected == 0 else "PARTIAL"
        self._audit.append(ar)
        log.info("   financial_ratios: %d loaded, %d rejected", ar.rows_loaded, ar.rows_rejected)

    # --- Analysis ---
    def _load_analysis(self, path: str) -> None:
        df = _read_excel(path)
        ar = AuditRecord(table_name="analysis", source_file=path)
        if df.empty:
            ar.load_status = "FAILED"; ar.notes = "File not found / empty"
            self._audit.append(ar); return

        df.columns = [c.strip().lower() for c in df.columns]
        for _, row in df.iterrows():
            ticker_raw = row.get("ticker", row.get("symbol", ""))
            try:
                ticker = normalize_ticker(ticker_raw)
                cid    = self._company_id_cache.get(ticker)
                if cid is None:
                    ar.rows_rejected += 1; continue
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO analysis
                        (company_id, analyst_rating, target_price, current_price,
                         upside_pct, recommendation, analysis_date, summary, source_file)
                    VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    (cid,
                     str(row.get("analyst_rating", "")).strip() or None,
                     normalize_currency(row.get("target_price")),
                     normalize_currency(row.get("current_price")),
                     normalize_percentage(row.get("upside_pct")),
                     str(row.get("recommendation", "")).strip() or None,
                     normalize_date(row.get("analysis_date", row.get("date", ""))),
                     str(row.get("summary", "")).strip() or None,
                     path),
                )
                ar.rows_loaded += 1
            except Exception as exc:
                log.debug("analysis insert error: %s", exc)
                ar.rows_rejected += 1

        self.conn.commit()
        ar.load_status = "SUCCESS" if ar.rows_rejected == 0 else "PARTIAL"
        self._audit.append(ar)
        log.info("   analysis: %d loaded, %d rejected", ar.rows_loaded, ar.rows_rejected)

    # --- Documents ---
    def _load_documents(self, path: str) -> None:
        df = _read_excel(path)
        ar = AuditRecord(table_name="documents", source_file=path)
        if df.empty:
            ar.load_status = "FAILED"; ar.notes = "File not found / empty"
            self._audit.append(ar); return

        df.columns = [c.strip().lower() for c in df.columns]
        for _, row in df.iterrows():
            ticker_raw = row.get("ticker", row.get("symbol", ""))
            try:
                ticker = normalize_ticker(ticker_raw)
                cid    = self._company_id_cache.get(ticker)
                if cid is None:
                    ar.rows_rejected += 1; continue
                doc_type = str(row.get("doc_type", row.get("type", "ANNUAL_REPORT"))).strip().upper()
                self.conn.execute(
                    "INSERT INTO documents (company_id, doc_type, doc_year, doc_url, description, source_file) "
                    "VALUES (?,?,?,?,?,?)",
                    (cid, doc_type,
                     normalize_year(row.get("doc_year", row.get("year", ""))) if row.get("doc_year") else None,
                     str(row.get("doc_url", row.get("url", ""))).strip() or None,
                     str(row.get("description", "")).strip() or None,
                     path),
                )
                ar.rows_loaded += 1
            except Exception as exc:
                log.debug("documents insert error: %s", exc)
                ar.rows_rejected += 1

        self.conn.commit()
        ar.load_status = "SUCCESS" if ar.rows_rejected == 0 else "PARTIAL"
        self._audit.append(ar)
        log.info("   documents: %d loaded, %d rejected", ar.rows_loaded, ar.rows_rejected)

    # --- Pros & Cons ---
    def _load_prosandcons(self, path: str) -> None:
        df = _read_excel(path)
        ar = AuditRecord(table_name="prosandcons", source_file=path)
        if df.empty:
            ar.load_status = "FAILED"; ar.notes = "File not found / empty"
            self._audit.append(ar); return

        df.columns = [c.strip().lower() for c in df.columns]
        for _, row in df.iterrows():
            ticker_raw = row.get("ticker", row.get("symbol", ""))
            try:
                ticker = normalize_ticker(ticker_raw)
                cid    = self._company_id_cache.get(ticker)
                if cid is None:
                    ar.rows_rejected += 1; continue
                pc_type = str(row.get("type", "PRO")).strip().upper()
                if pc_type not in ("PRO", "CON"):
                    ar.rows_rejected += 1; continue
                desc = str(row.get("description", row.get("text", ""))).strip()
                if not desc:
                    ar.rows_rejected += 1; continue
                self.conn.execute(
                    "INSERT INTO prosandcons (company_id, type, description, category, source_file) "
                    "VALUES (?,?,?,?,?)",
                    (cid, pc_type, desc,
                     str(row.get("category", "")).strip() or None, path),
                )
                ar.rows_loaded += 1
            except Exception as exc:
                log.debug("prosandcons insert error: %s", exc)
                ar.rows_rejected += 1

        self.conn.commit()
        ar.load_status = "SUCCESS" if ar.rows_rejected == 0 else "PARTIAL"
        self._audit.append(ar)
        log.info("   prosandcons: %d loaded, %d rejected", ar.rows_loaded, ar.rows_rejected)

    # --- Peer Groups ---
    def _load_peer_groups(self, path: str) -> None:
        df = _read_excel(path)
        ar = AuditRecord(table_name="peer_groups", source_file=path)
        if df.empty:
            ar.load_status = "FAILED"; ar.notes = "File not found / empty"
            self._audit.append(ar); return

        df.columns = [c.strip().lower() for c in df.columns]
        for _, row in df.iterrows():
            t1_raw = row.get("ticker", row.get("company", ""))
            t2_raw = row.get("peer_ticker", row.get("peer", row.get("peer_company", "")))
            try:
                t1 = normalize_ticker(t1_raw)
                t2 = normalize_ticker(t2_raw)
                c1 = self._company_id_cache.get(t1)
                c2 = self._company_id_cache.get(t2)
                if c1 is None or c2 is None or c1 == c2:
                    ar.rows_rejected += 1; continue
                self.conn.execute(
                    "INSERT OR IGNORE INTO peer_groups (company_id, peer_company_id, group_name, source_file) "
                    "VALUES (?,?,?,?)",
                    (c1, c2, str(row.get("group_name", "")).strip() or None, path),
                )
                ar.rows_loaded += 1
            except Exception as exc:
                log.debug("peers insert error: %s", exc)
                ar.rows_rejected += 1

        self.conn.commit()
        ar.load_status = "SUCCESS" if ar.rows_rejected == 0 else "PARTIAL"
        self._audit.append(ar)
        log.info("   peer_groups: %d loaded, %d rejected", ar.rows_loaded, ar.rows_rejected)

    # ------------------------------------------------------------------
    # Audit CSV
    # ------------------------------------------------------------------

    def write_audit_csv(self, out_path: str = "output/load_audit.csv") -> None:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        fieldnames = ["table_name", "source_file", "rows_loaded",
                      "rows_rejected", "load_status", "run_at", "notes"]
        with open(out_path, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(r.to_dict() for r in self._audit)
        log.info("Audit written → %s", out_path)

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _refresh_company_cache(self) -> None:
        cur = self.conn.execute("SELECT company_id, ticker FROM companies")
        self._company_id_cache = {row["ticker"]: row["company_id"] for row in cur.fetchall()}

    def _refresh_sector_cache(self) -> None:
        cur = self.conn.execute("SELECT sector_id, sector_name FROM sectors")
        self._sector_id_cache = {row["sector_name"]: row["sector_id"] for row in cur.fetchall()}


# ===========================================================================
# CLI entry point
# ===========================================================================

def main() -> None:
    import argparse
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(description="Nifty 100 ETL Loader – Sprint 1")
    parser.add_argument("--db",     default=os.getenv("DB_PATH", "nifty100.db"))
    parser.add_argument("--schema", default="db/schema.sql")
    parser.add_argument("--audit",  default="output/load_audit.csv")
    args = parser.parse_args()

    loader = DataLoader(db_path=args.db, schema_path=args.schema)
    try:
        loader.load_all()
        loader.write_audit_csv(args.audit)
        # Quick counts
        loader.conn.execute("PRAGMA foreign_key_check").fetchall()
        for tbl in ("companies", "profitandloss", "balancesheet", "cashflow", "stock_prices"):
            cnt = loader.conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            log.info("   %-25s %d rows", tbl, cnt)
    finally:
        loader.close()


if __name__ == "__main__":
    main()
