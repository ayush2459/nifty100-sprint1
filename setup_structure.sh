#!/usr/bin/env bash
# =============================================================================
# setup_structure.sh — Nifty 100 Sprint 1
# Reorganises flat files into the correct project layout and creates all
# missing files (__init__.py, .env.example, .gitignore, directories)
#
# Usage:
#   cd ~/Downloads/n100
#   bash setup_structure.sh
# =============================================================================

set -e  # Exit on any error

echo ""
echo "═══════════════════════════════════════════════"
echo "  Nifty 100 · Sprint 1 · Structure Setup"
echo "═══════════════════════════════════════════════"
echo ""

# ---------------------------------------------------------------------------
# 1. Create directory tree
# ---------------------------------------------------------------------------
echo "→  Creating directory tree …"

mkdir -p db
mkdir -p src/etl
mkdir -p tests/etl
mkdir -p notebooks
mkdir -p output
mkdir -p data/raw
mkdir -p data/processed

echo "✓  Directories created"

# ---------------------------------------------------------------------------
# 2. Move core source files into correct locations
# ---------------------------------------------------------------------------
echo "→  Moving source files …"

# db/
[ -f schema.sql ]              && mv schema.sql              db/schema.sql
[ -f exploratory_queries.sql ] && mv exploratory_queries.sql notebooks/exploratory_queries.sql

# src/etl/
[ -f loader.py ]               && mv loader.py               src/etl/loader.py
[ -f normaliser.py ]           && mv normaliser.py            src/etl/normaliser.py
[ -f validator.py ]            && mv validator.py             src/etl/validator.py

# tests/etl/
[ -f test_loader.py ]          && mv test_loader.py           tests/etl/test_loader.py
[ -f test_normaliser.py ]      && mv test_normaliser.py       tests/etl/test_normaliser.py
[ -f test_validator.py ]       && mv test_validator.py        tests/etl/test_validator.py

echo "✓  Files moved"

# ---------------------------------------------------------------------------
# 3. Create __init__.py files
# ---------------------------------------------------------------------------
echo "→  Creating __init__.py files …"

cat > src/__init__.py << 'EOF'
# Nifty 100 Financial Analytics Platform
EOF

cat > src/etl/__init__.py << 'EOF'
"""
src.etl
=======
ETL sub-package: normaliser, loader, validator.
"""
from .normaliser import (
    normalize_year,
    normalize_ticker,
    normalize_currency,
    normalize_percentage,
    normalize_date,
)
from .loader import DataLoader
from .validator import DataQualityValidator

__all__ = [
    "normalize_year",
    "normalize_ticker",
    "normalize_currency",
    "normalize_percentage",
    "normalize_date",
    "DataLoader",
    "DataQualityValidator",
]
EOF

cat > tests/__init__.py << 'EOF'
EOF

cat > tests/etl/__init__.py << 'EOF'
EOF

echo "✓  __init__.py files created"

# ---------------------------------------------------------------------------
# 4. Create .env.example
# ---------------------------------------------------------------------------
echo "→  Creating .env.example …"

cat > .env.example << 'EOF'
# =============================================================================
# .env.example — Nifty 100 Financial Analytics Platform
# Copy to .env and fill in your values:  cp .env.example .env
# =============================================================================

# ── Database ─────────────────────────────────────────────────────────────────
DB_PATH=nifty100.db
SCHEMA_PATH=db/schema.sql

# ── Output paths ─────────────────────────────────────────────────────────────
AUDIT_OUT=output/load_audit.csv
DQ_OUT=output/validation_failures.csv

# ── Source file paths (7 core) ───────────────────────────────────────────────
COMPANIES_FILE=data/raw/companies.xlsx
PROFIT_LOSS_FILE=data/raw/profit_loss.xlsx
BALANCE_SHEET_FILE=data/raw/balance_sheet.xlsx
CASH_FLOW_FILE=data/raw/cash_flow.xlsx
STOCK_PRICES_FILE=data/raw/stock_prices.xlsx
FINANCIAL_RATIOS_FILE=data/raw/financial_ratios.xlsx
SECTORS_FILE=data/raw/sectors.xlsx

# ── Source file paths (5 supplementary) ──────────────────────────────────────
ANALYSIS_FILE=data/raw/analysis.xlsx
DOCUMENTS_FILE=data/raw/documents.xlsx
PROS_CONS_FILE=data/raw/pros_cons.xlsx
PEER_GROUPS_FILE=data/raw/peer_groups.xlsx
QUARTERLY_FILE=data/raw/quarterly_results.xlsx

# ── Google Sheets export URLs (optional — for direct GSheet ingestion) ────────
GSHEET_COMPANIES=
GSHEET_PROFIT_LOSS=
GSHEET_BALANCE_SHEET=
GSHEET_CASH_FLOW=
GSHEET_STOCK_PRICES=
GSHEET_FINANCIAL_RATIOS=
GSHEET_SECTORS=
GSHEET_ANALYSIS=
GSHEET_DOCUMENTS=
GSHEET_PROS_CONS=
GSHEET_PEER_GROUPS=
GSHEET_QUARTERLY=

# ── Dashboard & API ───────────────────────────────────────────────────────────
STREAMLIT_PORT=8501
API_HOST=0.0.0.0
API_PORT=8000

# ── Logging ──────────────────────────────────────────────────────────────────
LOG_LEVEL=INFO
EOF

echo "✓  .env.example created"

# ---------------------------------------------------------------------------
# 5. Create .gitignore
# ---------------------------------------------------------------------------
echo "→  Creating .gitignore …"

cat > .gitignore << 'EOF'
# =============================================================================
# .gitignore — Nifty 100 Financial Analytics Platform
# =============================================================================

# ── Python ───────────────────────────────────────────────────────────────────
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
.venv/
venv/
env/
*.egg-info/
dist/
build/
.eggs/

# ── Testing ──────────────────────────────────────────────────────────────────
.pytest_cache/
.coverage
htmlcov/
coverage.xml

# ── Database ──────────────────────────────────────────────────────────────────
*.db
*.sqlite
*.sqlite3

# ── Raw data (large Excel files — do not commit) ──────────────────────────────
data/raw/*.xlsx
data/raw/*.xls
data/raw/*.csv
data/processed/

# ── Generated outputs ─────────────────────────────────────────────────────────
output/
*.pdf
*.pptx

# ── Environment ───────────────────────────────────────────────────────────────
.env
*.env

# ── OS ────────────────────────────────────────────────────────────────────────
.DS_Store
Thumbs.db

# ── IDE ───────────────────────────────────────────────────────────────────────
.vscode/
.idea/
*.swp
*.swo

# ── Notebooks checkpoints ─────────────────────────────────────────────────────
.ipynb_checkpoints/

# ── Zip artefacts ─────────────────────────────────────────────────────────────
*.zip
EOF

echo "✓  .gitignore created"

# ---------------------------------------------------------------------------
# 6. Create output/.gitkeep and data/raw/.gitkeep so dirs are tracked by git
# ---------------------------------------------------------------------------
touch output/.gitkeep
touch data/raw/.gitkeep
touch data/processed/.gitkeep

echo "✓  .gitkeep placeholders added"

# ---------------------------------------------------------------------------
# 7. Remove stale zip if present
# ---------------------------------------------------------------------------
[ -f nifty100_sprint1.zip ] && rm nifty100_sprint1.zip && echo "✓  Removed stale zip"

# ---------------------------------------------------------------------------
# 8. Print final tree
# ---------------------------------------------------------------------------
echo ""
echo "═══════════════════════════════════════════════"
echo "  Final project structure"
echo "═══════════════════════════════════════════════"
find . -not -path './.venv/*' -not -path './.git/*' \
       -not -path './__pycache__/*' \
  | sort \
  | sed 's|[^/]*/|  |g'

echo ""
echo "═══════════════════════════════════════════════"
echo "  Next steps"
echo "═══════════════════════════════════════════════"
echo ""
echo "  1. make install          # create .venv + install 20 deps"
echo "  2. cp .env.example .env  # configure your paths"
echo "  3. # drop .xlsx files into data/raw/"
echo "  4. make load             # ETL + 16 DQ rules"
echo "  5. make test             # 139 tests"
echo "  6. git add ."
echo "     git commit -m 'chore: reorganise into correct project layout'"
echo "     git push"
echo ""
echo "✅  Setup complete!"
echo ""
EOF
