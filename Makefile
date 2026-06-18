# =============================================================================
# Makefile — Nifty 100 Financial Analytics Platform
# Sprint 1 · Data Foundation
#
# Usage:
#   make load        — Run full ETL pipeline (load + DQ)
#   make validate    — Re-run DQ rules on existing DB (no reload)
#   make ratios      — Compute financial ratios (Sprint 2)
#   make test        — Run pytest test suite
#   make report      — Generate PDF analysis report (Sprint 3)
#   make dashboard   — Launch Streamlit dashboard
#   make api         — Start FastAPI server
#   make clean       — Remove generated artefacts
# =============================================================================

.PHONY: all load validate ratios test report dashboard api clean \
        install check-env dirs help

# ---------------------------------------------------------------------------
# Paths / env
# ---------------------------------------------------------------------------
PYTHON     := python3
VENV       := .venv
VENV_BIN   := $(VENV)/bin
PIP        := $(VENV_BIN)/pip
PYTEST     := $(VENV_BIN)/pytest
PYTHON_V   := $(VENV_BIN)/python

DB_PATH       ?= nifty100.db
SCHEMA_PATH   ?= db/schema.sql
AUDIT_OUT     ?= output/load_audit.csv
DQ_OUT        ?= output/validation_failures.csv

# Include .env if it exists (override defaults)
-include .env
export DB_PATH SCHEMA_PATH AUDIT_OUT DQ_OUT

# ---------------------------------------------------------------------------
# Default target
# ---------------------------------------------------------------------------
all: help

# ---------------------------------------------------------------------------
# help
# ---------------------------------------------------------------------------
help:
	@echo ""
	@echo "  Nifty 100 — Sprint 1 Makefile"
	@echo "  ─────────────────────────────"
	@echo "  make install     Create venv and install dependencies"
	@echo "  make dirs        Create required output directories"
	@echo "  make load        ETL load + DQ validation (full pipeline)"
	@echo "  make validate    Re-run DQ rules on existing DB"
	@echo "  make ratios      Compute financial ratios (Sprint 2)"
	@echo "  make test        Run pytest (all 45+ unit tests)"
	@echo "  make test-v      Run pytest with verbose output"
	@echo "  make report      Generate PDF/HTML analysis report"
	@echo "  make dashboard   Launch Streamlit dashboard"
	@echo "  make api         Start FastAPI REST server"
	@echo "  make clean       Remove generated artefacts"
	@echo ""

# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------
install: $(VENV)

$(VENV):
	@echo "→  Creating virtual environment …"
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	@echo "✓  venv ready at $(VENV)"

# ---------------------------------------------------------------------------
# dirs — ensure output directories exist
# ---------------------------------------------------------------------------
dirs:
	mkdir -p output data/raw data/processed notebooks

# ---------------------------------------------------------------------------
# load — Step 1: ETL load + DQ  (Day 05)
# ---------------------------------------------------------------------------
load: dirs check-env
	@echo ""
	@echo "═══════════════════════════════════════"
	@echo "  Sprint 1 · Full ETL Pipeline"
	@echo "═══════════════════════════════════════"
	$(PYTHON_V) run_pipeline.py \
		--db       $(DB_PATH) \
		--schema   $(SCHEMA_PATH) \
		--audit-out $(AUDIT_OUT) \
		--dq-out   $(DQ_OUT)
	@echo ""
	@echo "✓  Load complete.  Check $(AUDIT_OUT) and $(DQ_OUT)"

# ---------------------------------------------------------------------------
# validate — re-run DQ without reloading
# ---------------------------------------------------------------------------
validate: dirs check-env
	$(PYTHON_V) run_pipeline.py \
		--validate-only \
		--db     $(DB_PATH) \
		--dq-out $(DQ_OUT)

# ---------------------------------------------------------------------------
# ratios — compute financial ratios (Sprint 2 placeholder)
# ---------------------------------------------------------------------------
ratios: check-env
	@echo "→  Computing financial ratios …"
	$(PYTHON_V) -c "
from src.analysis.ratios import RatioEngine
import sqlite3, os
conn = sqlite3.connect(os.getenv('DB_PATH', 'nifty100.db'))
RatioEngine(conn).compute_all()
conn.close()
print('✓  Ratios written to financial_ratios table.')
" 2>/dev/null || echo "⚠  Ratio engine not yet implemented (Sprint 2)."

# ---------------------------------------------------------------------------
# test — run full pytest suite
# ---------------------------------------------------------------------------
test: check-env
	@echo ""
	@echo "═══════════════════════════════════════"
	@echo "  Running test suite …"
	@echo "═══════════════════════════════════════"
	$(PYTEST) tests/ \
		--tb=short \
		-q \
		--color=yes \
		2>&1
	@echo ""

test-v: check-env
	$(PYTEST) tests/ -v --tb=long --color=yes

test-norm: check-env
	$(PYTEST) tests/etl/test_normaliser.py -v

test-load: check-env
	$(PYTEST) tests/etl/test_loader.py -v

test-dq: check-env
	$(PYTEST) tests/etl/test_validator.py -v

# ---------------------------------------------------------------------------
# report — generate PDF/HTML analytical report (Sprint 3 placeholder)
# ---------------------------------------------------------------------------
report: check-env
	@echo "→  Generating analysis report …"
	$(PYTHON_V) -c "
from src.reports.report_engine import ReportEngine
ReportEngine().generate()
" 2>/dev/null || echo "⚠  Report engine not yet implemented (Sprint 3)."

# ---------------------------------------------------------------------------
# dashboard — launch Streamlit dashboard (Sprint 4 placeholder)
# ---------------------------------------------------------------------------
dashboard: check-env
	@echo "→  Starting Streamlit dashboard …"
	$(VENV_BIN)/streamlit run src/dashboard/app.py \
		--server.port 8501 \
		2>/dev/null || echo "⚠  Dashboard not yet implemented (Sprint 4)."

# ---------------------------------------------------------------------------
# api — start FastAPI server (Sprint 4 placeholder)
# ---------------------------------------------------------------------------
api: check-env
	@echo "→  Starting FastAPI server …"
	$(VENV_BIN)/uvicorn src.api.main:app \
		--host 0.0.0.0 --port 8000 --reload \
		2>/dev/null || echo "⚠  API not yet implemented (Sprint 4)."

# ---------------------------------------------------------------------------
# explore — run the 10 exploratory SQL queries
# ---------------------------------------------------------------------------
explore: $(DB_PATH)
	sqlite3 $(DB_PATH) < notebooks/exploratory_queries.sql

# ---------------------------------------------------------------------------
# clean
# ---------------------------------------------------------------------------
clean:
	@echo "→  Removing generated artefacts …"
	rm -f  $(DB_PATH)
	rm -f  $(AUDIT_OUT)
	rm -f  $(DQ_OUT)
	rm -f  output/*.csv output/*.json output/*.html output/*.pdf
	find . -name "__pycache__"     -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc"           -delete 2>/dev/null || true
	find . -name ".pytest_cache"   -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.egg-info"      -type d -exec rm -rf {} + 2>/dev/null || true
	@echo "✓  Clean complete."

clean-db:
	rm -f $(DB_PATH)
	@echo "✓  $(DB_PATH) removed."

# ---------------------------------------------------------------------------
# check-env — ensure venv and key files exist
# ---------------------------------------------------------------------------
check-env:
	@test -f $(VENV_BIN)/python || \
		(echo "❌  Run 'make install' first." && exit 1)
	@test -f $(SCHEMA_PATH) || \
		(echo "❌  Missing schema: $(SCHEMA_PATH)" && exit 1)

# ---------------------------------------------------------------------------
# Convenience alias
# ---------------------------------------------------------------------------
ci: install test

.DEFAULT_GOAL := help
