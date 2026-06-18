"""
validator.py
============
16 Data-Quality rules for the Nifty 100 financial analytics database.

Rule catalogue
--------------
| ID    | Name                  | Severity | Table(s)                  |
|-------|-----------------------|----------|---------------------------|
| DQ-01 | PK uniqueness         | CRITICAL | companies                 |
| DQ-02 | Composite PK          | CRITICAL | pnl / bs / cf             |
| DQ-03 | FK integrity          | CRITICAL | all transactional tables  |
| DQ-04 | BS balance            | WARNING  | balancesheet              |
| DQ-05 | OPM cross-check       | WARNING  | profitandloss             |
| DQ-06 | Positive sales        | CRITICAL | profitandloss             |
| DQ-07 | Net-cash reconcile    | WARNING  | cashflow                  |
| DQ-08 | Tax-rate sanity       | WARNING  | profitandloss             |
| DQ-09 | Dividend cap          | WARNING  | profitandloss             |
| DQ-10 | URL format            | INFO     | documents                 |
| DQ-11 | EPS sign consistency  | WARNING  | profitandloss             |
| DQ-12 | BSE code format       | INFO     | companies                 |
| DQ-13 | Year coverage         | WARNING  | pnl / bs / cf             |
| DQ-14 | Year-range sanity     | CRITICAL | pnl / bs / cf / prices    |
| DQ-15 | Non-negative debt     | WARNING  | balancesheet              |
| DQ-16 | Field completeness    | WARNING  | pnl / bs (last 5 yrs)     |

Severity definitions
--------------------
CRITICAL  – must be resolved before pipeline can proceed (blocks Day 05 load).
WARNING   – logged and written to CSV; pipeline continues.
INFO      – cosmetic / advisory; does not block.

Usage
-----
    from src.etl.validator import DataQualityValidator

    validator = DataQualityValidator(conn)
    violations = validator.run_all()
    validator.write_csv(violations, "output/validation_failures.csv")
    critical_count = sum(1 for v in violations if v.severity == "CRITICAL")
"""

from __future__ import annotations

import csv
import logging
import re
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Tuple

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tolerance constants
# ---------------------------------------------------------------------------
BS_BALANCE_TOL     = 0.01    # DQ-04 : |assets - liabilities| / assets < 1 %
OPM_TOLERANCE      = 0.02    # DQ-05 : |calc_opm - stored_opm| < 2 pp
NETCASH_TOL        = 0.01    # DQ-07 : |sum - reported| / |reported| < 1 %
TAX_RATE_MIN       = 0.0     # DQ-08
TAX_RATE_MAX       = 50.0    # DQ-08  (%)
DIVIDEND_SLACK     = 1.10    # DQ-09  dividends ≤ PAT × 110 %
YEAR_MIN           = 2000    # DQ-14
YEAR_MAX           = 2026    # DQ-14
COVERAGE_MIN_YEARS = 3       # DQ-13
COMPLETENESS_YEARS = 5       # DQ-16  last N fiscal years must have key fields

_URL_RE = re.compile(r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE)
_BSE_RE = re.compile(r"^\d{6}$")


# ===========================================================================
# Violation dataclass
# ===========================================================================

@dataclass
class Violation:
    rule_id:      str
    rule_name:    str
    severity:     str           # CRITICAL | WARNING | INFO
    table_name:   str
    record_id:    Optional[int]
    ticker:       Optional[str]
    year:         Optional[int]
    field_name:   Optional[str]
    actual_value: Optional[str]
    message:      str
    detected_at:  str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


# ===========================================================================
# DataQualityValidator
# ===========================================================================

class DataQualityValidator:
    """Runs all 16 DQ rules against a live SQLite connection."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self._rules: List[Tuple[str, Callable]] = [
            ("DQ-01", self.dq_01_pk_uniqueness),
            ("DQ-02", self.dq_02_composite_pk),
            ("DQ-03", self.dq_03_fk_integrity),
            ("DQ-04", self.dq_04_bs_balance),
            ("DQ-05", self.dq_05_opm_crosscheck),
            ("DQ-06", self.dq_06_positive_sales),
            ("DQ-07", self.dq_07_netcash_reconcile),
            ("DQ-08", self.dq_08_tax_rate_sanity),
            ("DQ-09", self.dq_09_dividend_cap),
            ("DQ-10", self.dq_10_url_format),
            ("DQ-11", self.dq_11_eps_sign),
            ("DQ-12", self.dq_12_bse_code_format),
            ("DQ-13", self.dq_13_year_coverage),
            ("DQ-14", self.dq_14_year_range),
            ("DQ-15", self.dq_15_nonnegative_debt),
            ("DQ-16", self.dq_16_field_completeness),
        ]

    # ------------------------------------------------------------------
    # Orchestrator
    # ------------------------------------------------------------------

    def run_all(self, rules: Optional[List[str]] = None) -> List[Violation]:
        """
        Run all (or selected) DQ rules.

        Parameters
        ----------
        rules : list of rule IDs, e.g. ["DQ-01", "DQ-04"].
                Pass None to run all 16.

        Returns
        -------
        List of Violation instances, sorted by severity then rule_id.
        """
        violations: List[Violation] = []
        target = set(rules) if rules else None

        for rid, fn in self._rules:
            if target and rid not in target:
                continue
            log.info("  Running %s …", rid)
            try:
                new_vs = fn()
                violations.extend(new_vs)
                log.info("    %s → %d violation(s)", rid, len(new_vs))
            except Exception as exc:
                log.error("  %s crashed: %s", rid, exc, exc_info=True)
                violations.append(Violation(
                    rule_id=rid, rule_name="RULE EXECUTION ERROR",
                    severity="CRITICAL", table_name="",
                    record_id=None, ticker=None, year=None,
                    field_name=None, actual_value=None,
                    message=f"Rule execution error: {exc}",
                ))

        _SEV_ORDER = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
        violations.sort(key=lambda v: (_SEV_ORDER.get(v.severity, 9), v.rule_id))
        return violations

    def write_csv(self, violations: List[Violation], out_path: str) -> None:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "rule_id", "rule_name", "severity", "table_name",
            "record_id", "ticker", "year", "field_name",
            "actual_value", "message", "detected_at",
        ]
        with open(out_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(v.to_dict() for v in violations)
        log.info("Validation failures written → %s  (%d total)", out_path, len(violations))

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def _ticker(self, company_id: int) -> str:
        row = self.conn.execute(
            "SELECT ticker FROM companies WHERE company_id = ?", (company_id,)
        ).fetchone()
        return row["ticker"] if row else f"cid={company_id}"

    def _v(self, rule_id, rule_name, severity, table, record_id=None,
           ticker=None, year=None, field_name=None, actual_value=None, message="") -> Violation:
        return Violation(
            rule_id=rule_id, rule_name=rule_name, severity=severity,
            table_name=table, record_id=record_id, ticker=ticker,
            year=year, field_name=field_name,
            actual_value=str(actual_value) if actual_value is not None else None,
            message=message,
        )

    # ==================================================================
    # DQ-01 : PK uniqueness in companies
    # ==================================================================

    def dq_01_pk_uniqueness(self) -> List[Violation]:
        """
        Every company_id in the companies table must be unique.
        Also check that ticker is unique (business key).
        """
        vs: List[Violation] = []
        NAME = "PK Uniqueness"

        # Duplicate company_id (should never happen with AUTOINCREMENT, but check)
        rows = self.conn.execute(
            "SELECT company_id, COUNT(*) AS cnt FROM companies "
            "GROUP BY company_id HAVING cnt > 1"
        ).fetchall()
        for row in rows:
            vs.append(self._v(
                "DQ-01", NAME, "CRITICAL", "companies",
                record_id=row["company_id"],
                message=f"company_id {row['company_id']} appears {row['cnt']} times",
            ))

        # Duplicate ticker
        rows = self.conn.execute(
            "SELECT ticker, COUNT(*) AS cnt FROM companies "
            "GROUP BY ticker HAVING cnt > 1"
        ).fetchall()
        for row in rows:
            vs.append(self._v(
                "DQ-01", NAME, "CRITICAL", "companies",
                ticker=row["ticker"], field_name="ticker",
                actual_value=row["ticker"],
                message=f"ticker '{row['ticker']}' is duplicated ({row['cnt']} rows)",
            ))

        return vs

    # ==================================================================
    # DQ-02 : Composite PK uniqueness  (company_id, year)
    # ==================================================================

    def dq_02_composite_pk(self) -> List[Violation]:
        """(company_id, year) must be unique in P&L, BS, and CF."""
        vs: List[Violation] = []
        NAME = "Composite PK"
        tables = {
            "profitandloss": "pl_id",
            "balancesheet":  "bs_id",
            "cashflow":      "cf_id",
        }
        for tbl, pk_col in tables.items():
            rows = self.conn.execute(
                f"SELECT company_id, year, COUNT(*) AS cnt FROM {tbl} "
                f"GROUP BY company_id, year HAVING cnt > 1"
            ).fetchall()
            for row in rows:
                vs.append(self._v(
                    "DQ-02", NAME, "CRITICAL", tbl,
                    ticker=self._ticker(row["company_id"]),
                    year=row["year"],
                    message=(f"(company_id={row['company_id']}, year={row['year']}) "
                             f"has {row['cnt']} duplicate rows"),
                ))
        return vs

    # ==================================================================
    # DQ-03 : FK integrity
    # ==================================================================

    def dq_03_fk_integrity(self) -> List[Violation]:
        """
        PRAGMA foreign_key_check returns rows where a FK references a
        non-existent PK.  Any such row is a CRITICAL violation.
        """
        vs: List[Violation] = []
        NAME = "FK Integrity"
        rows = self.conn.execute("PRAGMA foreign_key_check").fetchall()
        for row in rows:
            vs.append(self._v(
                "DQ-03", NAME, "CRITICAL", row[0],
                record_id=row[1],
                message=(f"FK violation in table='{row[0]}' rowid={row[1]} "
                         f"parent='{row[2]}' fkid={row[3]}"),
            ))
        return vs

    # ==================================================================
    # DQ-04 : Balance Sheet balance  |assets - L&E| / assets < 1 %
    # ==================================================================

    def dq_04_bs_balance(self) -> List[Violation]:
        """
        For every (company, year) row in balancesheet, verify:
            total_assets ≈ total_liabilities + total_equity  (within 1 %)

        Falls back to components if total columns are NULL.
        """
        vs: List[Violation] = []
        NAME = "BS Balance"
        rows = self.conn.execute(
            """
            SELECT bs_id, company_id, year,
                   total_assets_cr, total_liabilities_cr, total_equity_cr,
                   share_capital_cr, reserves_cr,
                   total_borrowings_cr, trade_payables_cr, other_liabilities_cr
            FROM balancesheet
            WHERE total_assets_cr IS NOT NULL
            """
        ).fetchall()

        for row in rows:
            assets = row["total_assets_cr"]
            if not assets or assets == 0:
                continue

            liab  = row["total_liabilities_cr"]
            eq    = row["total_equity_cr"]

            # Fallback: reconstruct equity and liabilities from components
            if liab is None:
                liab = ((row["total_borrowings_cr"] or 0)
                        + (row["trade_payables_cr"] or 0)
                        + (row["other_liabilities_cr"] or 0))
            if eq is None:
                eq = ((row["share_capital_cr"] or 0)
                      + (row["reserves_cr"] or 0))

            computed_total = liab + eq
            diff_pct = abs(assets - computed_total) / abs(assets)

            if diff_pct > BS_BALANCE_TOL:
                vs.append(self._v(
                    "DQ-04", NAME, "WARNING", "balancesheet",
                    record_id=row["bs_id"],
                    ticker=self._ticker(row["company_id"]),
                    year=row["year"],
                    field_name="total_assets_cr",
                    actual_value=f"{diff_pct:.2%}",
                    message=(f"BS imbalance {diff_pct:.2%}: "
                             f"assets={assets:.2f} Cr, "
                             f"L+E={computed_total:.2f} Cr"),
                ))
        return vs

    # ==================================================================
    # DQ-05 : OPM cross-check
    # ==================================================================

    def dq_05_opm_crosscheck(self) -> List[Violation]:
        """
        Verify stored opm_pct ≈ (ebitda_cr / revenue_cr) × 100
        within OPM_TOLERANCE (2 percentage points).
        """
        vs: List[Violation] = []
        NAME = "OPM Cross-check"
        rows = self.conn.execute(
            """
            SELECT pl_id, company_id, year,
                   revenue_cr, ebitda_cr, opm_pct
            FROM profitandloss
            WHERE revenue_cr IS NOT NULL AND revenue_cr > 0
              AND ebitda_cr  IS NOT NULL
              AND opm_pct    IS NOT NULL
            """
        ).fetchall()

        for row in rows:
            calc_opm = (row["ebitda_cr"] / row["revenue_cr"]) * 100
            diff     = abs(calc_opm - row["opm_pct"])
            if diff > OPM_TOLERANCE * 100:          # compare in % points
                vs.append(self._v(
                    "DQ-05", NAME, "WARNING", "profitandloss",
                    record_id=row["pl_id"],
                    ticker=self._ticker(row["company_id"]),
                    year=row["year"],
                    field_name="opm_pct",
                    actual_value=str(row["opm_pct"]),
                    message=(f"Stored OPM={row['opm_pct']:.2f}% but "
                             f"EBITDA/Rev={calc_opm:.2f}%  "
                             f"(diff={diff:.2f} pp)"),
                ))
        return vs

    # ==================================================================
    # DQ-06 : Positive sales (revenue > 0)
    # ==================================================================

    def dq_06_positive_sales(self) -> List[Violation]:
        """Revenue must be positive for every row in profitandloss."""
        vs: List[Violation] = []
        NAME = "Positive Sales"
        rows = self.conn.execute(
            "SELECT pl_id, company_id, year, revenue_cr "
            "FROM profitandloss "
            "WHERE revenue_cr IS NULL OR revenue_cr <= 0"
        ).fetchall()
        for row in rows:
            vs.append(self._v(
                "DQ-06", NAME, "CRITICAL", "profitandloss",
                record_id=row["pl_id"],
                ticker=self._ticker(row["company_id"]),
                year=row["year"],
                field_name="revenue_cr",
                actual_value=str(row["revenue_cr"]),
                message=f"Revenue is NULL or non-positive: {row['revenue_cr']}",
            ))
        return vs

    # ==================================================================
    # DQ-07 : Net-cash reconciliation  CFO + CFI + CFF ≈ net_cash_flow
    # ==================================================================

    def dq_07_netcash_reconcile(self) -> List[Violation]:
        """
        |  (CFO + CFI + CFF) - net_cash_flow  |
        ----------------------------------------  <  NETCASH_TOL  (1 %)
              |  net_cash_flow  |
        """
        vs: List[Violation] = []
        NAME = "Net-Cash Reconciliation"
        rows = self.conn.execute(
            """
            SELECT cf_id, company_id, year,
                   cfo_cr, cfi_cr, cff_cr, net_cash_flow_cr
            FROM cashflow
            WHERE cfo_cr IS NOT NULL AND cfi_cr IS NOT NULL
              AND cff_cr IS NOT NULL AND net_cash_flow_cr IS NOT NULL
              AND net_cash_flow_cr != 0
            """
        ).fetchall()

        for row in rows:
            computed = (row["cfo_cr"] or 0) + (row["cfi_cr"] or 0) + (row["cff_cr"] or 0)
            reported = row["net_cash_flow_cr"]
            diff_pct = abs(computed - reported) / abs(reported)

            if diff_pct > NETCASH_TOL:
                vs.append(self._v(
                    "DQ-07", NAME, "WARNING", "cashflow",
                    record_id=row["cf_id"],
                    ticker=self._ticker(row["company_id"]),
                    year=row["year"],
                    field_name="net_cash_flow_cr",
                    actual_value=str(reported),
                    message=(f"CFO+CFI+CFF={computed:.2f} Cr but "
                             f"stored net_cash={reported:.2f} Cr "
                             f"(diff={diff_pct:.2%})"),
                ))
        return vs

    # ==================================================================
    # DQ-08 : Tax-rate sanity  0 % ≤ effective_tax_rate ≤ 50 %
    # ==================================================================

    def dq_08_tax_rate_sanity(self) -> List[Violation]:
        """
        Effective tax rate (tax_pct) must be within [0 %, 50 %].
        Excludes rows where PBT ≤ 0 (loss-making → tax credits possible).
        """
        vs: List[Violation] = []
        NAME = "Tax-Rate Sanity"
        rows = self.conn.execute(
            """
            SELECT pl_id, company_id, year, tax_pct, pbt_cr
            FROM profitandloss
            WHERE tax_pct IS NOT NULL
              AND pbt_cr IS NOT NULL AND pbt_cr > 0
              AND (tax_pct < ? OR tax_pct > ?)
            """, (TAX_RATE_MIN, TAX_RATE_MAX)
        ).fetchall()

        for row in rows:
            vs.append(self._v(
                "DQ-08", NAME, "WARNING", "profitandloss",
                record_id=row["pl_id"],
                ticker=self._ticker(row["company_id"]),
                year=row["year"],
                field_name="tax_pct",
                actual_value=str(row["tax_pct"]),
                message=(f"Tax rate {row['tax_pct']:.1f}% is outside "
                         f"[{TAX_RATE_MIN}%, {TAX_RATE_MAX}%]"),
            ))
        return vs

    # ==================================================================
    # DQ-09 : Dividend cap  dividends paid ≤ PAT × 110 %
    # ==================================================================

    def dq_09_dividend_cap(self) -> List[Violation]:
        """
        Total dividend outflow ≤ PAT × DIVIDEND_SLACK.
        We use: dividend_payout_pct ≤ 110 %
        (companies occasionally pay dividends from reserves, but >110 % is suspicious).
        """
        vs: List[Violation] = []
        NAME = "Dividend Cap"
        rows = self.conn.execute(
            """
            SELECT pl_id, company_id, year, dividend_payout_pct, pat_cr
            FROM profitandloss
            WHERE dividend_payout_pct IS NOT NULL
              AND dividend_payout_pct > ?
              AND pat_cr IS NOT NULL AND pat_cr > 0
            """, (DIVIDEND_SLACK * 100,)
        ).fetchall()

        for row in rows:
            vs.append(self._v(
                "DQ-09", NAME, "WARNING", "profitandloss",
                record_id=row["pl_id"],
                ticker=self._ticker(row["company_id"]),
                year=row["year"],
                field_name="dividend_payout_pct",
                actual_value=str(row["dividend_payout_pct"]),
                message=(f"Dividend payout {row['dividend_payout_pct']:.1f}% "
                         f"exceeds {DIVIDEND_SLACK*100:.0f}% of PAT={row['pat_cr']:.2f} Cr"),
            ))
        return vs

    # ==================================================================
    # DQ-10 : URL format in documents table
    # ==================================================================

    def dq_10_url_format(self) -> List[Violation]:
        """All doc_url values must match https?://... pattern."""
        vs: List[Violation] = []
        NAME = "URL Format"
        rows = self.conn.execute(
            "SELECT doc_id, company_id, doc_type, doc_url "
            "FROM documents WHERE doc_url IS NOT NULL AND doc_url != ''"
        ).fetchall()

        for row in rows:
            if not _URL_RE.match(row["doc_url"]):
                vs.append(self._v(
                    "DQ-10", NAME, "INFO", "documents",
                    record_id=row["doc_id"],
                    ticker=self._ticker(row["company_id"]),
                    field_name="doc_url",
                    actual_value=row["doc_url"][:80],
                    message=f"doc_url does not match https?:// pattern",
                ))
        return vs

    # ==================================================================
    # DQ-11 : EPS sign consistency  sign(PAT) == sign(EPS)
    # ==================================================================

    def dq_11_eps_sign(self) -> List[Violation]:
        """
        When PAT > 0, basic_eps must be > 0.
        When PAT < 0, basic_eps must be ≤ 0.
        Rows with PAT = 0 or EPS = NULL are skipped.
        """
        vs: List[Violation] = []
        NAME = "EPS Sign Consistency"
        rows = self.conn.execute(
            """
            SELECT pl_id, company_id, year, pat_cr, basic_eps
            FROM profitandloss
            WHERE pat_cr IS NOT NULL AND pat_cr != 0
              AND basic_eps IS NOT NULL
            """
        ).fetchall()

        for row in rows:
            pat = row["pat_cr"]
            eps = row["basic_eps"]
            sign_mismatch = (pat > 0 and eps < 0) or (pat < 0 and eps > 0)
            if sign_mismatch:
                vs.append(self._v(
                    "DQ-11", NAME, "WARNING", "profitandloss",
                    record_id=row["pl_id"],
                    ticker=self._ticker(row["company_id"]),
                    year=row["year"],
                    field_name="basic_eps",
                    actual_value=str(eps),
                    message=f"PAT={pat:.2f} Cr but EPS={eps} — sign mismatch",
                ))
        return vs

    # ==================================================================
    # DQ-12 : BSE code must be a 6-digit number
    # ==================================================================

    def dq_12_bse_code_format(self) -> List[Violation]:
        """BSE scrip codes are always exactly 6 numeric digits (e.g. 500325)."""
        vs: List[Violation] = []
        NAME = "BSE Code Format"
        rows = self.conn.execute(
            "SELECT company_id, ticker, bse_code FROM companies "
            "WHERE bse_code IS NOT NULL AND bse_code != ''"
        ).fetchall()

        for row in rows:
            if not _BSE_RE.match(str(row["bse_code"]).strip()):
                vs.append(self._v(
                    "DQ-12", NAME, "INFO", "companies",
                    record_id=row["company_id"],
                    ticker=row["ticker"],
                    field_name="bse_code",
                    actual_value=str(row["bse_code"]),
                    message=f"BSE code '{row['bse_code']}' is not a 6-digit number",
                ))
        return vs

    # ==================================================================
    # DQ-13 : Year coverage  ≥ COVERAGE_MIN_YEARS per company
    # ==================================================================

    def dq_13_year_coverage(self) -> List[Violation]:
        """
        Each company must have at least COVERAGE_MIN_YEARS (3) rows in
        profitandloss, balancesheet, and cashflow.
        """
        vs: List[Violation] = []
        NAME = "Year Coverage"
        tables = ["profitandloss", "balancesheet", "cashflow"]

        for tbl in tables:
            rows = self.conn.execute(
                f"""
                SELECT c.company_id, c.ticker, COUNT(t.year) AS yr_count
                FROM companies c
                LEFT JOIN {tbl} t USING (company_id)
                GROUP BY c.company_id
                HAVING yr_count < ?
                """, (COVERAGE_MIN_YEARS,)
            ).fetchall()

            for row in rows:
                vs.append(self._v(
                    "DQ-13", NAME, "WARNING", tbl,
                    ticker=row["ticker"],
                    message=(f"Only {row['yr_count']} year(s) of data in {tbl} "
                             f"(minimum required: {COVERAGE_MIN_YEARS})"),
                ))
        return vs

    # ==================================================================
    # DQ-14 : Year range sanity  YEAR_MIN ≤ year ≤ YEAR_MAX
    # ==================================================================

    def dq_14_year_range(self) -> List[Violation]:
        """All fiscal years must be within [YEAR_MIN, YEAR_MAX]."""
        vs: List[Violation] = []
        NAME = "Year Range"
        checks = [
            ("profitandloss", "pl_id",  "company_id"),
            ("balancesheet",  "bs_id",  "company_id"),
            ("cashflow",      "cf_id",  "company_id"),
            ("stock_prices",  "price_id", "company_id"),
        ]
        for tbl, pk, cid_col in checks:
            yr_col = "year" if tbl != "stock_prices" else "CAST(SUBSTR(price_date,1,4) AS INT)"
            label  = "year" if tbl != "stock_prices" else "price_date[year]"
            rows = self.conn.execute(
                f"""
                SELECT {pk} AS rec_id, {cid_col} AS company_id, {yr_col} AS yr
                FROM {tbl}
                WHERE {yr_col} < ? OR {yr_col} > ?
                """, (YEAR_MIN, YEAR_MAX)
            ).fetchall()
            for row in rows:
                vs.append(self._v(
                    "DQ-14", NAME, "CRITICAL", tbl,
                    record_id=row["rec_id"],
                    ticker=self._ticker(row["company_id"]),
                    year=row["yr"],
                    field_name=label,
                    actual_value=str(row["yr"]),
                    message=f"Year {row['yr']} is outside [{YEAR_MIN}, {YEAR_MAX}]",
                ))
        return vs

    # ==================================================================
    # DQ-15 : Non-negative debt  total_borrowings ≥ 0
    # ==================================================================

    def dq_15_nonnegative_debt(self) -> List[Violation]:
        """
        Total borrowings and their LT/ST components cannot be negative.
        Negative borrowings indicate a data error (sign flip).
        """
        vs: List[Violation] = []
        NAME = "Non-Negative Debt"
        fields = [
            ("total_borrowings_cr",      "total_borrowings_cr"),
            ("long_term_borrowings_cr",  "long_term_borrowings_cr"),
            ("short_term_borrowings_cr", "short_term_borrowings_cr"),
        ]
        for col, label in fields:
            rows = self.conn.execute(
                f"""
                SELECT bs_id, company_id, year, {col}
                FROM balancesheet
                WHERE {col} IS NOT NULL AND {col} < 0
                """
            ).fetchall()
            for row in rows:
                vs.append(self._v(
                    "DQ-15", NAME, "WARNING", "balancesheet",
                    record_id=row["bs_id"],
                    ticker=self._ticker(row["company_id"]),
                    year=row["year"],
                    field_name=label,
                    actual_value=str(row[col]),
                    message=f"{label} is negative: {row[col]:.2f} Cr",
                ))
        return vs

    # ==================================================================
    # DQ-16 : Field completeness for last COMPLETENESS_YEARS years
    # ==================================================================

    def dq_16_field_completeness(self) -> List[Violation]:
        """
        For each company, the last COMPLETENESS_YEARS (5) fiscal years must
        have non-NULL values for the following key fields:
          P&L : revenue_cr, pat_cr
          BS  : total_assets_cr, total_equity_cr
        """
        vs: List[Violation] = []
        NAME = "Field Completeness"

        max_year_row = self.conn.execute(
            "SELECT MAX(year) AS mx FROM profitandloss"
        ).fetchone()
        if not max_year_row or max_year_row["mx"] is None:
            return vs
        cutoff_year = max_year_row["mx"] - COMPLETENESS_YEARS + 1

        # P&L checks
        for field_col in ("revenue_cr", "pat_cr"):
            rows = self.conn.execute(
                f"""
                SELECT pl_id, company_id, year, {field_col}
                FROM profitandloss
                WHERE year >= ? AND {field_col} IS NULL
                """, (cutoff_year,)
            ).fetchall()
            for row in rows:
                vs.append(self._v(
                    "DQ-16", NAME, "WARNING", "profitandloss",
                    record_id=row["pl_id"],
                    ticker=self._ticker(row["company_id"]),
                    year=row["year"],
                    field_name=field_col,
                    actual_value="NULL",
                    message=f"{field_col} is NULL for year {row['year']} (last {COMPLETENESS_YEARS} yrs)",
                ))

        # BS checks
        for field_col in ("total_assets_cr", "total_equity_cr"):
            rows = self.conn.execute(
                f"""
                SELECT bs_id, company_id, year, {field_col}
                FROM balancesheet
                WHERE year >= ? AND {field_col} IS NULL
                """, (cutoff_year,)
            ).fetchall()
            for row in rows:
                vs.append(self._v(
                    "DQ-16", NAME, "WARNING", "balancesheet",
                    record_id=row["bs_id"],
                    ticker=self._ticker(row["company_id"]),
                    year=row["year"],
                    field_name=field_col,
                    actual_value="NULL",
                    message=f"{field_col} is NULL for year {row['year']} (last {COMPLETENESS_YEARS} yrs)",
                ))

        return vs


# ===========================================================================
# CLI entry point
# ===========================================================================

def main() -> None:
    import argparse
    import os
    parser = argparse.ArgumentParser(description="Nifty 100 DQ Validator – Sprint 1")
    parser.add_argument("--db",     default=os.getenv("DB_PATH", "nifty100.db"))
    parser.add_argument("--out",    default="output/validation_failures.csv")
    parser.add_argument("--rules",  nargs="*", help="Run specific rules, e.g. DQ-01 DQ-04")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row

    validator = DataQualityValidator(conn)
    violations = validator.run_all(rules=args.rules)
    validator.write_csv(violations, args.out)

    critical = [v for v in violations if v.severity == "CRITICAL"]
    warning  = [v for v in violations if v.severity == "WARNING"]
    info     = [v for v in violations if v.severity == "INFO"]

    print(f"\n{'─'*50}")
    print(f"  DQ Summary: {len(violations)} total violation(s)")
    print(f"  CRITICAL : {len(critical)}")
    print(f"  WARNING  : {len(warning)}")
    print(f"  INFO     : {len(info)}")
    print(f"{'─'*50}\n")

    if critical:
        print("  ❌ CRITICAL failures must be resolved before Day 05 data load.\n")
        raise SystemExit(1)
    else:
        print("  ✓ No CRITICAL violations. Pipeline may proceed.\n")


if __name__ == "__main__":
    main()
