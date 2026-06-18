#!/usr/bin/env python3
"""
run_pipeline.py
===============
Sprint 1 – Day 05 pipeline orchestrator.

Runs the full ETL sequence in one command:
    Step 1  Load all 12 source files → nifty100.db
    Step 2  Run all 16 DQ rules
    Step 3  Write output/load_audit.csv
    Step 4  Write output/validation_failures.csv
    Step 5  Print summary; exit 1 on CRITICAL DQ failures

Usage
-----
    python run_pipeline.py                   # use .env defaults
    python run_pipeline.py --db custom.db    # custom DB path
    python run_pipeline.py --validate-only   # skip reload, re-run DQ
    python run_pipeline.py --dq-only DQ-04 DQ-06   # run specific rules

Environment (.env)
------------------
    DB_PATH       = nifty100.db
    SCHEMA_PATH   = db/schema.sql
    DATA_DIR      = data/raw
    OUTPUT_DIR    = output

    # Source file overrides (optional)
    SRC_COMPANIES        = data/raw/companies.xlsx
    SRC_PROFITANDLOSS    = data/raw/profit_loss.xlsx
    SRC_BALANCESHEET     = data/raw/balance_sheet.xlsx
    SRC_CASHFLOW         = data/raw/cash_flow.xlsx
    SRC_STOCK_PRICES     = data/raw/stock_prices.xlsx
    SRC_FINANCIAL_RATIOS = data/raw/financial_ratios.xlsx
    SRC_SECTORS          = data/raw/sectors.xlsx
    SRC_ANALYSIS         = data/raw/analysis.xlsx
    SRC_DOCUMENTS        = data/raw/documents.xlsx
    SRC_PROSANDCONS      = data/raw/pros_cons.xlsx
    SRC_PEER_GROUPS      = data/raw/peer_groups.xlsx
"""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from src.etl.loader    import DataLoader, DEFAULT_SOURCE_MAP
from src.etl.validator import DataQualityValidator

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
BANNER = r"""
╔══════════════════════════════════════════════════════════╗
║  Nifty 100 Financial Analytics – Sprint 1 Pipeline      ║
║  Data Ingestion · Schema · DQ Validation                ║
╚══════════════════════════════════════════════════════════╝
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _source_map_from_env() -> dict[str, str]:
    """Override DEFAULT_SOURCE_MAP with any SRC_* env vars."""
    mapping = dict(DEFAULT_SOURCE_MAP)
    env_keys = {
        "SRC_COMPANIES":        "companies",
        "SRC_PROFITANDLOSS":    "profitandloss",
        "SRC_BALANCESHEET":     "balancesheet",
        "SRC_CASHFLOW":         "cashflow",
        "SRC_STOCK_PRICES":     "stock_prices",
        "SRC_FINANCIAL_RATIOS": "financial_ratios",
        "SRC_SECTORS":          "sectors",
        "SRC_ANALYSIS":         "analysis",
        "SRC_DOCUMENTS":        "documents",
        "SRC_PROSANDCONS":      "prosandcons",
        "SRC_PEER_GROUPS":      "peer_groups",
    }
    for env_var, table_key in env_keys.items():
        val = os.getenv(env_var)
        if val:
            mapping[table_key] = val
    return mapping


def _print_table_counts(conn: sqlite3.Connection) -> None:
    tables = [
        "companies", "profitandloss", "balancesheet", "cashflow",
        "stock_prices", "financial_ratios", "analysis",
        "documents", "prosandcons", "peer_groups", "sectors",
    ]
    print(f"\n  {'Table':<25} {'Rows':>8}")
    print(f"  {'─'*25} {'─'*8}")
    for tbl in tables:
        try:
            cnt = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        except Exception:
            cnt = "N/A"
        print(f"  {tbl:<25} {cnt:>8}")
    print()


def _print_dq_summary(violations) -> None:
    from collections import Counter
    sev_counts = Counter(v.severity for v in violations)
    print(f"\n  {'─'*40}")
    print(f"  DQ Summary: {len(violations)} total violation(s)")
    print(f"  {'CRITICAL':<12}: {sev_counts.get('CRITICAL', 0)}")
    print(f"  {'WARNING':<12}: {sev_counts.get('WARNING', 0)}")
    print(f"  {'INFO':<12}: {sev_counts.get('INFO', 0)}")
    print(f"  {'─'*40}\n")

    critical = [v for v in violations if v.severity == "CRITICAL"]
    if critical:
        print("  ❌ CRITICAL violations:\n")
        for v in critical[:10]:
            print(f"     [{v.rule_id}] {v.ticker or '—'} yr={v.year or '—'}")
            print(f"           {v.message}\n")
    else:
        print("  ✓ No CRITICAL violations – pipeline exit criteria met.\n")


# ===========================================================================
# Main
# ===========================================================================

def main() -> int:
    print(BANNER)

    # ── CLI args ────────────────────────────────────────────────────────────
    parser = argparse.ArgumentParser(
        description="Nifty 100 Sprint 1 – ETL + DQ Pipeline"
    )
    parser.add_argument(
        "--db", default=os.getenv("DB_PATH", "nifty100.db"),
        help="SQLite database path (default: nifty100.db)",
    )
    parser.add_argument(
        "--schema", default=os.getenv("SCHEMA_PATH", "db/schema.sql"),
    )
    parser.add_argument(
        "--audit-out", default=os.getenv("AUDIT_OUT", "output/load_audit.csv"),
    )
    parser.add_argument(
        "--dq-out", default=os.getenv("DQ_OUT", "output/validation_failures.csv"),
    )
    parser.add_argument(
        "--validate-only", action="store_true",
        help="Skip ETL load; re-run DQ rules on existing DB",
    )
    parser.add_argument(
        "--dq-only", nargs="*", metavar="RULE",
        help="Run only specific DQ rules, e.g. --dq-only DQ-01 DQ-04",
    )
    parser.add_argument(
        "--no-validate", action="store_true",
        help="Skip DQ validation after load",
    )
    args = parser.parse_args()

    # Ensure output directory exists
    Path(args.audit_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.dq_out).parent.mkdir(parents=True, exist_ok=True)

    t0 = time.time()

    # ── Step 1 : ETL Load ───────────────────────────────────────────────────
    if not args.validate_only:
        log.info("STEP 1 — Loading source files into %s", args.db)
        sources = _source_map_from_env()

        loader = DataLoader(db_path=args.db, schema_path=args.schema)
        try:
            loader.load_all(sources=sources)
            loader.write_audit_csv(args.audit_out)
            log.info("✓  ETL complete  (%.1fs)", time.time() - t0)
        except Exception as exc:
            log.error("❌  ETL failed: %s", exc, exc_info=True)
            return 1
        finally:
            loader.close()
    else:
        log.info("STEP 1 — Skipped (--validate-only)")

    # ── Step 2 : Table counts ───────────────────────────────────────────────
    log.info("STEP 2 — Verifying table counts")
    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row

    companies_count = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    fk_issues       = len(conn.execute("PRAGMA foreign_key_check").fetchall())

    print(f"  companies = {companies_count}  (expected 92)")
    print(f"  FK check  = {fk_issues} issues  (expected 0)")
    _print_table_counts(conn)

    exit_code = 0

    if companies_count == 0:
        log.warning("⚠  companies table is empty – source files may be missing.")

    # ── Step 3 : DQ Validation ──────────────────────────────────────────────
    if not args.no_validate:
        log.info("STEP 3 — Running DQ rules …")
        t1 = time.time()
        validator = DataQualityValidator(conn)
        violations = validator.run_all(rules=args.dq_only)
        validator.write_csv(violations, args.dq_out)
        log.info("✓  DQ complete  (%.1fs)", time.time() - t1)

        _print_dq_summary(violations)

        critical_count = sum(1 for v in violations if v.severity == "CRITICAL")
        if critical_count:
            log.error("❌  %d CRITICAL DQ violation(s) — resolve before Day 05 load.", critical_count)
            exit_code = 1
    else:
        log.info("STEP 3 — Skipped (--no-validate)")

    conn.close()

    # ── Final banner ─────────────────────────────────────────────────────────
    elapsed = time.time() - t0
    status  = "✓  PASSED" if exit_code == 0 else "❌  FAILED"
    print(f"  Pipeline {status}  |  Total time: {elapsed:.1f}s")
    print(f"  Audit    → {args.audit_out}")
    print(f"  DQ log   → {args.dq_out}\n")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
