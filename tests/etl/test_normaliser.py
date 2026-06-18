"""
tests/etl/test_normaliser.py
============================
Unit tests for src/etl/normaliser.py

Test counts
-----------
    normalize_year       : 20 tests  (parametrised)
    normalize_ticker     : 15 tests  (parametrised)
    normalize_currency   :  6 tests
    normalize_percentage :  4 tests
    ─────────────────────────────
    TOTAL                : 45 tests

Run with:
    pytest tests/etl/test_normaliser.py -v
"""

from datetime import datetime

import pytest

from src.etl.normaliser import (
    normalize_currency,
    normalize_date,
    normalize_percentage,
    normalize_ticker,
    normalize_year,
    CURRENT_YEAR,
    YEAR_MIN,
    YEAR_MAX,
)


# ===========================================================================
# normalize_year – 20 tests
# ===========================================================================

class TestNormalizeYear:
    """20 parametrised test cases covering every supported input format."""

    # ── Happy-path cases ───────────────────────────────────────────────────

    def test_ny_01_screener_march_space(self):
        """'Mar 2024' → Screener.in FY end month format."""
        assert normalize_year("Mar 2024") == 2024

    def test_ny_02_screener_march_hyphen(self):
        """'Mar-2024' → hyphenated month-year."""
        assert normalize_year("Mar-2024") == 2024

    def test_ny_03_fy_abbrev_short(self):
        """'FY24' → short Indian fiscal-year prefix."""
        assert normalize_year("FY24") == 2024

    def test_ny_04_fy_abbrev_full(self):
        """'FY2024' → full FY prefix."""
        assert normalize_year("FY2024") == 2024

    def test_ny_05_bare_string(self):
        """'2024' as a bare string."""
        assert normalize_year("2024") == 2024

    def test_ny_06_integer(self):
        """Python int 2024."""
        assert normalize_year(2024) == 2024

    def test_ny_07_float_from_excel(self):
        """2024.0 as Excel exports numbers as floats."""
        assert normalize_year(2024.0) == 2024

    def test_ny_08_indian_fy_short_range(self):
        """'2023-24' → Indian FY range; end year used."""
        assert normalize_year("2023-24") == 2024

    def test_ny_09_indian_fy_full_range(self):
        """'2023-2024' → full Indian FY range."""
        assert normalize_year("2023-2024") == 2024

    def test_ny_10_non_march_month(self):
        """'Jun 2023' → non-March month, year taken at face value."""
        assert normalize_year("Jun 2023") == 2023

    def test_ny_11_ttm(self):
        """'TTM' → Trailing Twelve Months maps to current year."""
        assert normalize_year("TTM") == CURRENT_YEAR

    def test_ny_12_ttm_lowercase(self):
        """'ttm' case-insensitive."""
        assert normalize_year("ttm") == CURRENT_YEAR

    def test_ny_13_iso_year_month(self):
        """'2024-03' → ISO year-month; year part extracted."""
        assert normalize_year("2024-03") == 2024

    def test_ny_14_fy_prefix_lowercase(self):
        """'fy2024' → case-insensitive FY prefix."""
        assert normalize_year("fy2024") == 2024

    def test_ny_15_early_year(self):
        """2001 → edge of realistic data range."""
        assert normalize_year(2001) == 2001

    def test_ny_16_fy_old_short(self):
        """'FY15' → resolves to 2015."""
        assert normalize_year("FY15") == 2015

    def test_ny_17_indian_fy_leading_decade(self):
        """'2015-16' → end year = 2016."""
        assert normalize_year("2015-16") == 2016

    def test_ny_18_december_month(self):
        """'Dec 2020' → December year end (some foreign companies)."""
        assert normalize_year("Dec 2020") == 2020

    def test_ny_19_whitespace_stripped(self):
        """' 2022 ' → surrounding whitespace stripped."""
        assert normalize_year(" 2022 ") == 2022

    def test_ny_20_fy_hyphen_variant(self):
        """'2019-20' → end year 2020."""
        assert normalize_year("2019-20") == 2020

    # ── Error cases ────────────────────────────────────────────────────────

    def test_ny_err_none_raises(self):
        """None must raise ValueError."""
        with pytest.raises(ValueError, match="None"):
            normalize_year(None)

    def test_ny_err_empty_string_raises(self):
        """Empty string must raise ValueError."""
        with pytest.raises(ValueError):
            normalize_year("")

    def test_ny_err_alphabetic_raises(self):
        """Purely alphabetic string raises ValueError."""
        with pytest.raises(ValueError):
            normalize_year("abc")

    def test_ny_err_too_old_raises(self):
        """Year below YEAR_MIN raises ValueError."""
        with pytest.raises(ValueError, match="range"):
            normalize_year(1985)

    def test_ny_err_future_raises(self):
        """Year above YEAR_MAX raises ValueError."""
        with pytest.raises(ValueError, match="range"):
            normalize_year(2050)

    def test_ny_err_nan_float_raises(self):
        """float('nan') raises ValueError."""
        with pytest.raises(ValueError):
            normalize_year(float("nan"))


# ===========================================================================
# normalize_ticker – 15 tests
# ===========================================================================

class TestNormalizeTicker:
    """15 parametrised test cases covering suffix, prefix, and case handling."""

    # ── Suffix removal ─────────────────────────────────────────────────────

    def test_nt_01_yahoo_ns_suffix(self):
        """'RELIANCE.NS' → Yahoo Finance NSE suffix removed."""
        assert normalize_ticker("RELIANCE.NS") == "RELIANCE"

    def test_nt_02_yahoo_bo_suffix(self):
        """'TCS.BO' → Yahoo Finance BSE suffix removed."""
        assert normalize_ticker("TCS.BO") == "TCS"

    def test_nt_03_dot_nse_suffix(self):
        """'INFY.NSE' → alternate full-exchange suffix removed."""
        assert normalize_ticker("INFY.NSE") == "INFY"

    def test_nt_04_dot_bse_suffix(self):
        """'WIPRO.BSE' → BSE suffix removed."""
        assert normalize_ticker("WIPRO.BSE") == "WIPRO"

    # ── Prefix removal ─────────────────────────────────────────────────────

    def test_nt_05_nse_colon_prefix(self):
        """'NSE:HDFC' → TradingView NSE prefix removed."""
        assert normalize_ticker("NSE:HDFC") == "HDFC"

    def test_nt_06_bse_colon_prefix(self):
        """'BSE:RELIANCE' → TradingView BSE prefix removed."""
        assert normalize_ticker("BSE:RELIANCE") == "RELIANCE"

    # ── Case normalisation ─────────────────────────────────────────────────

    def test_nt_07_lowercase(self):
        """'reliance' → uppercased."""
        assert normalize_ticker("reliance") == "RELIANCE"

    def test_nt_08_mixed_case(self):
        """'Reliance' → uppercased."""
        assert normalize_ticker("Reliance") == "RELIANCE"

    # ── Whitespace ─────────────────────────────────────────────────────────

    def test_nt_09_leading_trailing_spaces(self):
        """' RELIANCE ' → stripped."""
        assert normalize_ticker("  RELIANCE  ") == "RELIANCE"

    # ── Trailing exchange name ─────────────────────────────────────────────

    def test_nt_10_trailing_nse_name(self):
        """'RELIANCE NSE' → trailing exchange name removed."""
        assert normalize_ticker("RELIANCE NSE") == "RELIANCE"

    def test_nt_11_trailing_bse_name(self):
        """'TCS BSE' → trailing exchange name removed."""
        assert normalize_ticker("TCS BSE") == "TCS"

    # ── Special tickers ────────────────────────────────────────────────────

    def test_nt_12_bse_numeric_code(self):
        """'500325' → BSE scrip code treated as ticker, returned as-is."""
        assert normalize_ticker("500325") == "500325"

    def test_nt_13_multi_word_preserved(self):
        """'HDFC BANK' → multi-word ticker preserved (not a trailing exchange name)."""
        result = normalize_ticker("HDFC BANK")
        assert result == "HDFC BANK"

    def test_nt_14_combined_prefix_and_suffix(self):
        """'NSE:BHARTIARTL.NS' → both prefix and suffix stripped."""
        assert normalize_ticker("NSE:BHARTIARTL.NS") == "BHARTIARTL"

    def test_nt_15_already_clean(self):
        """'BAJFINANCE' → already clean, returned unchanged."""
        assert normalize_ticker("BAJFINANCE") == "BAJFINANCE"

    # ── Error cases ────────────────────────────────────────────────────────

    def test_nt_err_none_raises(self):
        """None raises ValueError."""
        with pytest.raises(ValueError):
            normalize_ticker(None)

    def test_nt_err_empty_string_raises(self):
        """Empty string raises ValueError."""
        with pytest.raises(ValueError):
            normalize_ticker("")

    def test_nt_err_whitespace_only_raises(self):
        """String with only spaces raises ValueError."""
        with pytest.raises(ValueError):
            normalize_ticker("   ")


# ===========================================================================
# normalize_currency – 6 tests
# ===========================================================================

class TestNormalizeCurrency:
    """6 tests for the currency normaliser (output in ₹ Crores)."""

    def test_nc_01_plain_float(self):
        """Plain float returned unchanged."""
        assert normalize_currency(1234.56) == pytest.approx(1234.56)

    def test_nc_02_string_with_commas(self):
        """'1,234.56' → 1234.56."""
        assert normalize_currency("1,234.56") == pytest.approx(1234.56)

    def test_nc_03_rupee_symbol_and_cr(self):
        """'₹1,234.56 Cr' → 1234.56."""
        assert normalize_currency("₹1,234.56 Cr") == pytest.approx(1234.56)

    def test_nc_04_accounting_negative(self):
        """'(500.00)' → -500.0."""
        assert normalize_currency("(500.00)") == pytest.approx(-500.0)

    def test_nc_05_lakh_conversion(self):
        """'100 Lakh' → 1.0 Crore."""
        assert normalize_currency("100 Lakh") == pytest.approx(1.0)

    def test_nc_06_missing_returns_none(self):
        """'--' and None return None."""
        assert normalize_currency("--") is None
        assert normalize_currency(None) is None


# ===========================================================================
# normalize_percentage – 4 tests
# ===========================================================================

class TestNormalizePercentage:
    """4 tests for the percentage normaliser."""

    def test_np_01_string_with_percent_sign(self):
        """'25.5%' → 25.5."""
        assert normalize_percentage("25.5%") == pytest.approx(25.5)

    def test_np_02_bare_float_string(self):
        """'25.5' → 25.5."""
        assert normalize_percentage("25.5") == pytest.approx(25.5)

    def test_np_03_missing_returns_none(self):
        """'--' returns None."""
        assert normalize_percentage("--") is None

    def test_np_04_numeric_passthrough(self):
        """Float 12.3 returned as 12.3."""
        assert normalize_percentage(12.3) == pytest.approx(12.3)


# ===========================================================================
# normalize_date – 4 tests
# ===========================================================================

class TestNormalizeDate:
    """4 tests for the date normaliser (ISO output)."""

    def test_nd_01_indian_date_format(self):
        """'31-Mar-2024' → '2024-03-31'."""
        assert normalize_date("31-Mar-2024") == "2024-03-31"

    def test_nd_02_iso_passthrough(self):
        """'2024-03-31' → '2024-03-31'."""
        assert normalize_date("2024-03-31") == "2024-03-31"

    def test_nd_03_slash_format(self):
        """'31/03/2024' → '2024-03-31'."""
        assert normalize_date("31/03/2024") == "2024-03-31"

    def test_nd_04_none_returns_none(self):
        """None returns None."""
        assert normalize_date(None) is None
