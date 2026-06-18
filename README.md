# Nifty 100 Financial Analytics Platform
### Sprint 1 — Data Foundation

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![SQLite](https://img.shields.io/badge/SQLite-3.x-lightblue.svg)](https://www.sqlite.org/)
[![Tests](https://img.shields.io/badge/Tests-139%20passing-brightgreen.svg)]()
[![License](https://img.shields.io/badge/License-MIT-green.svg)]()

A production-grade ETL pipeline and SQLite data warehouse for financial analysis of the **Nifty 100 index** — 92 companies, 11 relational tables, 16 data-quality rules, and 139 automated tests. Built as Sprint 1 of a multi-sprint analytics platform covering profitability, balance sheet health, cash flows, stock prices, and peer benchmarking.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Database Schema](#database-schema)
- [Project Structure](#project-structure)
- [ETL Pipeline](#etl-pipeline)
- [Data Quality Framework](#data-quality-framework)
- [Quick Start](#quick-start)
- [Makefile Targets](#makefile-targets)
- [Testing](#testing)
- [Source Files](#source-files)
- [Sprint 1 Exit Criteria](#sprint-1-exit-criteria)
- [Roadmap](#roadmap)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     12 Source Excel/CSV Files                    │
│          (7 core + 5 supplementary · Screener.in / BSE / NSE)   │
└────────────────────────────┬────────────────────────────────────┘
                             │
                    ┌────────▼────────┐
                    │  normaliser.py  │  normalize_year · normalize_ticker
                    │                 │  normalize_currency · normalize_date
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │   loader.py     │  Wide + Long format auto-detection
                    │  DataLoader     │  FK-safe insert order · AuditRecord
                    └────────┬────────┘
                             │
              ┌──────────────▼──────────────┐
              │        nifty100.db          │
              │   SQLite · WAL mode · FK ON │
              │   11 tables · 7 000+ rows   │
              └──────────────┬──────────────┘
                             │
                    ┌────────▼────────┐
                    │  validator.py   │  16 DQ rules · CRITICAL / WARNING / INFO
                    │ DataQualityVal. │  → validation_failures.csv
                    └─────────────────┘
                             │
              ┌──────────────▼──────────────┐
              │        Outputs              │
              │  load_audit.csv             │
              │  validation_failures.csv    │
              └─────────────────────────────┘
```

**Engine:** SQLite 3 with `PRAGMA foreign_keys = ON` and `journal_mode = WAL` for concurrent read access.  
**Monetary unit:** All financial figures are in **₹ Indian Rupees Crores (Cr)**.  
**Fiscal year convention:** Year field holds the fiscal year-end (e.g., `2024` = FY2023-24).

---

## Database Schema

11 tables with full PK/FK integrity:

| # | Table | Rows (target) | Description |
|---|-------|--------------|-------------|
| 1 | `sectors` | ~20 | NSE sector classifications |
| 2 | `companies` | **92** | Master company registry with ISIN, BSE/NSE codes |
| 3 | `profitandloss` | ~1,276 | Revenue, EBITDA, PAT, EPS — annual |
| 4 | `balancesheet` | ~1,312 | Assets, liabilities, equity — annual |
| 5 | `cashflow` | ~1,187 | CFO, CFI, CFF, FCF, CapEx — annual |
| 6 | `stock_prices` | **5,520** | 60 months × 92 companies |
| 7 | `financial_ratios` | computed | PE, PB, ROE, ROCE, Debt/Equity (Sprint 2) |
| 8 | `analysis` | ~92 | Analyst ratings, target prices, recommendations |
| 9 | `documents` | varies | Annual report URLs, investor presentations |
| 10 | `prosandcons` | varies | Structured investment thesis points |
| 11 | `peer_groups` | varies | Peer comparison mappings |
| — | `_load_audit` | internal | Per-run ETL audit trail |

### Key constraints

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode  = WAL;
PRAGMA synchronous   = NORMAL;

-- Every transactional table has:
UNIQUE (company_id, year)         -- composite PK on time-series tables
FOREIGN KEY (company_id) REFERENCES companies(company_id)
    ON DELETE CASCADE ON UPDATE CASCADE
```

---

## Project Structure

```
nifty100-sprint1/
├── db/
│   └── schema.sql              # 11-table SQLite schema with indexes
├── src/
│   └── etl/
│       ├── __init__.py
│       ├── normaliser.py       # Stateless normalisation helpers
│       ├── loader.py           # DataLoader — reads 12 source files
│       └── validator.py        # 16 DQ rules → validation_failures.csv
├── tests/
│   └── etl/
│       ├── __init__.py
│       ├── test_normaliser.py  # 58 tests
│       ├── test_loader.py      # 41 tests
│       └── test_validator.py   # 40 tests
├── notebooks/
│   └── exploratory_queries.sql # 10 analytical SQL queries
├── data/
│   ├── raw/                    # Drop source .xlsx files here
│   └── processed/              # Intermediate outputs
├── output/
│   ├── load_audit.csv          # Per-table row counts & rejections
│   └── validation_failures.csv # DQ violations with severity
├── run_pipeline.py             # CLI orchestrator
├── Makefile                    # All workflow targets
├── requirements.txt            # 20 pinned dependencies
└── .env.example                # All config knobs
```

---

## ETL Pipeline

### normaliser.py — Stateless Normalisation

Pure functions with no I/O or global state. All raise `ValueError` with descriptive messages on bad input.

| Function | Input | Output | Notes |
|----------|-------|--------|-------|
| `normalize_year(val)` | `"Mar 2024"`, `2024`, `"FY24"` | `int` | Handles 20+ formats |
| `normalize_ticker(val)` | `" reliance "`, `"RELIANCE.NS"` | `str` | Strips exchange suffix |
| `normalize_currency(val)` | `"1,234.56"`, `"--"`, `None` | `float\|None` | Cr units |
| `normalize_percentage(val)` | `"23.5%"`, `0.235` | `float\|None` | Returns raw decimal |
| `normalize_date(val)` | `"01-Apr-2024"`, datetime | `str\|None` | ISO-8601 output |

### loader.py — DataLoader

```python
from src.etl.loader import DataLoader

loader = DataLoader(db_path="nifty100.db", schema_path="db/schema.sql")
loader.load_all(sources=SOURCE_MAP)
loader.write_audit_csv("output/load_audit.csv")
```

**Key capabilities:**
- Auto-detects **wide format** (years as columns) vs **long format** (year as a row field)
- Column-alias map handles header variations across Screener.in export batches
- FK-safe insert order: `sectors → companies → profitandloss / balancesheet / cashflow → ...`
- Per-table `AuditRecord` tracks rows loaded, rows rejected, and rejection reasons

### run_pipeline.py — CLI Orchestrator

```bash
python run_pipeline.py \
  --db       nifty100.db \
  --schema   db/schema.sql \
  --audit-out output/load_audit.csv \
  --dq-out    output/validation_failures.csv

# Validate only (no reload):
python run_pipeline.py --validate-only --db nifty100.db
```

Exit codes: `0` = success, `1` = CRITICAL DQ failures present.

---

## Data Quality Framework

16 rules across 4 severity tiers implemented in `validator.py`:

| Rule | Name | Severity | Tables |
|------|------|----------|--------|
| DQ-01 | PK uniqueness | **CRITICAL** | `companies` |
| DQ-02 | Composite PK | **CRITICAL** | `profitandloss`, `balancesheet`, `cashflow` |
| DQ-03 | FK integrity | **CRITICAL** | All transactional tables |
| DQ-04 | Balance sheet balance | WARNING | `balancesheet` (tol: 1%) |
| DQ-05 | OPM cross-check | WARNING | `profitandloss` (tol: 2pp) |
| DQ-06 | Positive sales | **CRITICAL** | `profitandloss` |
| DQ-07 | Net cash reconcile | WARNING | `cashflow` |
| DQ-08 | Tax-rate sanity | WARNING | `profitandloss` |
| DQ-09 | Dividend cap | WARNING | `profitandloss` |
| DQ-10 | URL format | INFO | `documents` |
| DQ-11 | EPS sign consistency | WARNING | `profitandloss` |
| DQ-12 | BSE code format | INFO | `companies` |
| DQ-13 | Year coverage | WARNING | `profitandloss`, `balancesheet`, `cashflow` |
| DQ-14 | Year-range sanity | **CRITICAL** | All time-series tables |
| DQ-15 | Non-negative debt | WARNING | `balancesheet` |
| DQ-16 | Field completeness | WARNING | `profitandloss`, `balancesheet` (last 5 yrs) |

**Severity definitions:**

- `CRITICAL` — blocks the Day 05 full load; must be resolved before proceeding
- `WARNING` — logged to CSV; pipeline continues
- `INFO` — advisory; no pipeline impact

---

## Quick Start

### Prerequisites

- Python 3.11+
- `make` (macOS/Linux) or run commands manually on Windows

### 1. Clone & install

```bash
git clone git@github.com:ayush2459/nifty100-sprint1.git
cd nifty100-sprint1

make install        # Creates .venv and installs all 20 dependencies
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env to set paths to your source Excel files
```

### 3. Add source data

Place the 12 source Excel files in `data/raw/`:

```bash
data/raw/
├── companies.xlsx
├── profit_loss.xlsx
├── balance_sheet.xlsx
├── cash_flow.xlsx
├── stock_prices.xlsx
├── financial_ratios.xlsx
├── sectors.xlsx
├── analysis.xlsx
├── documents.xlsx
├── pros_cons.xlsx
├── peer_groups.xlsx
└── quarterly_results.xlsx
```

### 4. Run the pipeline

```bash
make load           # Full ETL + 16 DQ rules
```

### 5. Verify

```bash
sqlite3 nifty100.db "SELECT COUNT(*) FROM companies;"
# Expected: 92

sqlite3 nifty100.db "PRAGMA foreign_key_check;"
# Expected: (empty — 0 violations)

cat output/load_audit.csv
cat output/validation_failures.csv
```

---

## Makefile Targets

| Target | Description |
|--------|-------------|
| `make install` | Create `.venv` and install all 20 dependencies |
| `make dirs` | Create `output/`, `data/raw/`, `data/processed/` |
| `make load` | Full ETL pipeline — load all 12 files + run DQ rules |
| `make validate` | Re-run 16 DQ rules on existing DB without reloading |
| `make test` | Run all 139 pytest tests |
| `make test-v` | Verbose test output |
| `make test-norm` | Test normaliser only |
| `make test-load` | Test loader only |
| `make test-dq` | Test validator only |
| `make explore` | Execute 10 exploratory SQL queries against the DB |
| `make ratios` | Compute financial ratios (Sprint 2 placeholder) |
| `make report` | Generate PDF/HTML report (Sprint 3 placeholder) |
| `make dashboard` | Launch Streamlit dashboard (Sprint 4 placeholder) |
| `make api` | Start FastAPI REST server (Sprint 4 placeholder) |
| `make clean` | Remove all generated artefacts (DB, CSVs, caches) |
| `make ci` | `install` + `test` — suitable for CI pipelines |

---

## Testing

**139 tests · 0 failures** across 3 test files:

| File | Tests | Coverage |
|------|-------|----------|
| `tests/etl/test_normaliser.py` | 58 | `normalize_year` (20), `normalize_ticker` (15), currency, percentage, date |
| `tests/etl/test_loader.py` | 41 | `AuditRecord`, column aliases, year-column detection, schema init, CSV output |
| `tests/etl/test_validator.py` | 40 | Clean + dirty fixture pair for every DQ rule DQ-01 → DQ-16 |

```bash
make test

# Output:
# ═══════════════════════════════════════
#   Running test suite …
# ═══════════════════════════════════════
# 139 passed in 2.14s
```

---

## Source Files

| # | File | Format | Target Table | Rows |
|---|------|--------|-------------|------|
| 1 | `companies.xlsx` | Wide | `companies` | 92 |
| 2 | `profit_loss.xlsx` | Wide (years as cols) | `profitandloss` | ~1,276 |
| 3 | `balance_sheet.xlsx` | Wide | `balancesheet` | ~1,312 |
| 4 | `cash_flow.xlsx` | Wide | `cashflow` | ~1,187 |
| 5 | `stock_prices.xlsx` | Long | `stock_prices` | 5,520 |
| 6 | `financial_ratios.xlsx` | Wide | `financial_ratios` | computed |
| 7 | `sectors.xlsx` | Lookup | `sectors` | ~20 |
| 8 | `analysis.xlsx` | Wide | `analysis` | ~92 |
| 9 | `documents.xlsx` | Long | `documents` | varies |
| 10 | `pros_cons.xlsx` | Long | `prosandcons` | varies |
| 11 | `peer_groups.xlsx` | Long | `peer_groups` | varies |
| 12 | `quarterly_results.xlsx` | Wide | supplementary | varies |

---

## Sprint 1 Exit Criteria

- [x] `SELECT COUNT(*) FROM companies` → **92**
- [x] `PRAGMA foreign_key_check` → **0 rows**
- [x] `load_audit.csv` → zero CRITICAL rejections
- [x] 139 ETL unit tests pass (35+ required)
- [x] 16 DQ rules implemented (DQ-01 → DQ-16)
- [x] Manual review: 5 random companies validated
- [x] `exploratory_queries.sql` — 10 queries covering key business questions
- [x] Sprint review signed off

---

## Dependencies

20 pinned libraries across 6 categories:

```
pandas==2.2.2          numpy==1.26.4          openpyxl==3.1.2
scipy==1.13.0          scikit-learn==1.4.2
plotly==5.22.0         matplotlib==3.8.4       seaborn==0.13.2
streamlit==1.35.0      fastapi==0.111.0        uvicorn==0.30.1
requests==2.32.2       python-dotenv==1.0.1
reportlab==4.2.0       python-pptx==0.6.23
pytest==8.2.2          pytest-cov==5.0.0
```

---

## Roadmap

| Sprint | Focus | Status |
|--------|-------|--------|
| **Sprint 1** | Data Foundation — ETL, Schema, DQ | ✅ Complete |
| Sprint 2 | Financial Ratios Engine — PE, PB, ROCE, ROE, FCF yield | 🔜 Planned |
| Sprint 3 | Analytics & Reporting — PDF reports, peer benchmarking | 🔜 Planned |
| Sprint 4 | Dashboard & API — Streamlit UI, FastAPI REST endpoints | 🔜 Planned |

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

*Built for systematic, data-driven analysis of India's Nifty 100 universe.*
