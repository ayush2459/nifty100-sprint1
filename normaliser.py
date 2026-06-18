"""
normaliser.py
=============
Atomic, stateless normalisation helpers for raw Excel data ingested from
Screener.in / BSE / NSE source files.

Public API
----------
    normalize_year(val)          → int        raise ValueError on failure
    normalize_ticker(val)        → str        raise ValueError on failure
    normalize_currency(val)      → float|None  None on missing / '--'
    normalize_percentage(val)    → float|None  None on missing / '--'
    normalize_date(val)          → str|None   ISO-8601 "YYYY-MM-DD"
    normalize_boolean(val)       → bool|None

All functions are pure (no I/O, no global state) and raise ValueError with a
descriptive message rather than returning sentinel values.

Units: all monetary values are in Indian Rupees Crores (₹ Cr).
"""

import re
from datetime import datetime
from typing import Union, Optional

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------
CURRENT_YEAR: int = datetime.now().year
YEAR_MIN: int = 1990
YEAR_MAX: int = 2030

_MONTH_MAP: dict[str, int] = {
    "JAN": 1,  "FEB": 2,  "MAR": 3,  "APR": 4,
    "MAY": 5,  "JUN": 6,  "JUL": 7,  "AUG": 8,
    "SEP": 9,  "OCT": 10, "NOV": 11, "DEC": 12,
    "JANUARY": 1,   "FEBRUARY": 2,  "MARCH": 3,
    "APRIL": 4,     "JUNE": 6,      "JULY": 7,
    "AUGUST": 8,    "SEPTEMBER": 9, "OCTOBER": 10,
    "NOVEMBER": 11, "DECEMBER": 12,
}

_EXCHANGE_SUFFIXES   = re.compile(r"\.(NS|BO|NSE|BSE)$", re.IGNORECASE)
_EXCHANGE_PREFIXES   = re.compile(r"^(NSE|BSE):", re.IGNORECASE)
_EXCHANGE_TRAILING   = re.compile(r"\s+(NSE|BSE|NSE EQUITIES)$", re.IGNORECASE)
_CURRENCY_CLEANUP    = re.compile(r"[₹\$,\s]")
_LAKH_PATTERN        = re.compile(r"(lakh|lakhs|L)\b", re.IGNORECASE)
_CRORE_PATTERN       = re.compile(r"(crore|crores|cr)\b", re.IGNORECASE)
_MILLION_PATTERN     = re.compile(r"(million|mn|m)\b", re.IGNORECASE)
_BILLION_PATTERN     = re.compile(r"(billion|bn|b)\b", re.IGNORECASE)

_MISSING_VALUES = frozenset(
    {"", "--", "-", "n/a", "na", "n.a.", "nil", "null", "none", "nan", "#n/a", "#value!"}
)


# ===========================================================================
# 1.  normalize_year
# ===========================================================================

def normalize_year(val: Union[str, int, float, None]) -> int:
    """
    Return a 4-digit integer fiscal-year from *val*.

    In India's April-to-March fiscal calendar the year label is the one in
    which the fiscal year **ends**.  "Mar 2024" therefore means FY2024
    (April 2023 → March 2024) and returns ``2024``.

    Supported input formats
    -----------------------
    | Input           | Output | Notes                              |
    |-----------------|--------|------------------------------------|
    | "Mar 2024"      | 2024   | Screener month-year (FY end month) |
    | "Mar-2024"      | 2024   | hyphen variant                     |
    | "FY24"          | 2024   | Indian FY abbreviation             |
    | "FY2024"        | 2024   | full FY prefix                     |
    | "2024"          | 2024   | bare string                        |
    | 2024            | 2024   | integer                            |
    | 2024.0          | 2024   | Excel float                        |
    | "2023-24"       | 2024   | Indian FY range (end year used)    |
    | "2023-2024"     | 2024   | full-year range                    |
    | "TTM"           | <now>  | Trailing Twelve Months             |
    | "Jun 2023"      | 2023   | non-March month (taken at face val)|
    | "2024-03"       | 2024   | ISO year-month                     |

    Raises
    ------
    ValueError
        When *val* is None, empty, unparseable, or outside [YEAR_MIN, YEAR_MAX].
    """
    if val is None:
        raise ValueError("normalize_year: received None")

    # Float coercion (Excel exports numbers as floats)
    if isinstance(val, float):
        if val != val:   # NaN
            raise ValueError("normalize_year: received NaN")
        val = int(val)

    raw = str(val).strip()
    if not raw:
        raise ValueError("normalize_year: received empty string")

    upper = raw.upper()

    # --- TTM ---
    if upper == "TTM":
        return CURRENT_YEAR

    # --- Pure 4-digit integer ---
    if re.fullmatch(r"\d{4}", raw):
        yr = int(raw)
        return _check_range(yr, raw)

    # --- Pure 2-digit integer (rare) ---
    if re.fullmatch(r"\d{2}", raw):
        yr = int(raw) + 2000
        return _check_range(yr, raw)

    # --- FY24 / FY2024 ---
    m = re.fullmatch(r"FY(\d{2,4})", upper)
    if m:
        yr = int(m.group(1))
        if yr < 100:
            yr += 2000
        return _check_range(yr, raw)

    # --- "2023-24" or "2023-2024" (Indian FY, use END year)
    #     Special case: "2024-03" where end_resolved < start → ISO year-month
    m = re.fullmatch(r"(\d{4})[- ](\d{2,4})", raw)
    if m:
        start        = int(m.group(1))
        end          = int(m.group(2))
        end_resolved = end + 2000 if end < 100 else end
        # If resolved end < start the second part is a month code, not a year suffix
        if end_resolved < start:
            return _check_range(start, raw)   # ISO year-month: take the 4-digit year
        return _check_range(end_resolved, raw)

    # --- "Mar 2024" or "Mar-2024" or "March 2024" ---
    m = re.fullmatch(r"([A-Za-z]{3,9})[- ](\d{4})", raw)
    if m:
        yr = int(m.group(2))
        return _check_range(yr, raw)

    raise ValueError(f"normalize_year: cannot parse {raw!r}")


def _check_range(yr: int, raw: str) -> int:
    if YEAR_MIN <= yr <= YEAR_MAX:
        return yr
    raise ValueError(
        f"normalize_year: {yr} (from {raw!r}) is out of range [{YEAR_MIN}, {YEAR_MAX}]"
    )


# ===========================================================================
# 2.  normalize_ticker
# ===========================================================================

def normalize_ticker(val: Union[str, None]) -> str:
    """
    Return a clean, uppercase NSE/BSE ticker symbol.

    Transformations applied (in order):
        1. Strip surrounding whitespace.
        2. Uppercase.
        3. Remove exchange prefix  ``NSE:`` / ``BSE:``.
        4. Remove exchange suffix  ``.NS`` / ``.BO`` / ``.NSE`` / ``.BSE``.
        5. Remove trailing exchange name  `` NSE`` / `` BSE``.
        6. Final strip.

    Raises
    ------
    ValueError
        When *val* is None or the result is empty after transformation.

    Examples
    --------
    >>> normalize_ticker("RELIANCE.NS")
    'RELIANCE'
    >>> normalize_ticker("NSE:INFY")
    'INFY'
    >>> normalize_ticker("hdfc bank")
    'HDFC BANK'
    >>> normalize_ticker("TCS.BO")
    'TCS'
    """
    if val is None:
        raise ValueError("normalize_ticker: received None")

    s = str(val).strip().upper()
    if not s:
        raise ValueError("normalize_ticker: received empty string")

    s = _EXCHANGE_PREFIXES.sub("", s)      # remove NSE: / BSE:
    s = _EXCHANGE_SUFFIXES.sub("", s)      # remove .NS / .BO / .NSE / .BSE
    s = _EXCHANGE_TRAILING.sub("", s)      # remove trailing ' NSE' / ' BSE'
    s = s.strip()

    if not s:
        raise ValueError(f"normalize_ticker: empty after normalisation (original={val!r})")

    return s


# ===========================================================================
# 3.  normalize_currency
# ===========================================================================

def normalize_currency(
    val: Union[str, int, float, None],
    allow_negative: bool = True,
) -> Optional[float]:
    """
    Parse *val* to a float representing Indian Rupees **Crores**.

    Handles:
    - ₹ symbol, $ symbol, commas
    - Unit labels: Cr / Crore / Crores / Lakh / Lakhs / L / Mn / Bn
    - Accounting negatives ``(1,234.56)``
    - Missing markers: ``--``, ``N/A``, ``nil``, empty string → ``None``

    Parameters
    ----------
    allow_negative : bool
        If False, returns None for values < 0 (used for revenue / sales checks).
    """
    if val is None:
        return None

    if isinstance(val, (int, float)):
        if isinstance(val, float) and val != val:   # NaN
            return None
        result = float(val)
        if not allow_negative and result < 0:
            return None
        return result

    s = str(val).strip()
    if s.lower() in _MISSING_VALUES:
        return None

    # Accounting-style negative: (1,234.56)
    negative = s.startswith("(") and s.endswith(")")
    if negative:
        s = s[1:-1].strip()

    # Detect unit multipliers BEFORE stripping them
    is_lakh    = bool(_LAKH_PATTERN.search(s))
    is_million = bool(_MILLION_PATTERN.search(s))
    is_billion = bool(_BILLION_PATTERN.search(s))

    # Strip all unit labels and currency symbols
    s = _CURRENCY_CLEANUP.sub("", s)
    s = _LAKH_PATTERN.sub("", s)
    s = _CRORE_PATTERN.sub("", s)
    s = _MILLION_PATTERN.sub("", s)
    s = _BILLION_PATTERN.sub("", s)
    s = s.strip()

    if not s or s.lower() in _MISSING_VALUES:
        return None

    try:
        value = float(s)
    except ValueError:
        return None

    # Unit conversion → Crores
    if is_lakh:
        value /= 100.0          # 1 Lakh = 0.01 Cr
    elif is_million:
        value /= 10.0           # 1 Mn  ≈ 0.1  Cr  (1 Cr = 10 Mn)
    elif is_billion:
        value *= 100.0          # 1 Bn  ≈ 100  Cr  (1 Cr = 0.01 Bn)

    if negative:
        value = -value

    if not allow_negative and value < 0:
        return None

    return value


# ===========================================================================
# 4.  normalize_percentage
# ===========================================================================

def normalize_percentage(val: Union[str, int, float, None]) -> Optional[float]:
    """
    Parse *val* to a float percentage (e.g. 25.5, not 0.255).

    "25.5%" → 25.5 | "25.5" → 25.5 | "--" → None
    """
    if val is None:
        return None

    if isinstance(val, (int, float)):
        if isinstance(val, float) and val != val:
            return None
        return float(val)

    s = str(val).strip()
    if s.lower() in _MISSING_VALUES:
        return None

    s = s.replace("%", "").strip()
    if not s:
        return None

    try:
        return float(s)
    except ValueError:
        return None


# ===========================================================================
# 5.  normalize_date
# ===========================================================================

def normalize_date(val: Union[str, int, float, None]) -> Optional[str]:
    """
    Return an ISO-8601 date string ``"YYYY-MM-DD"`` or ``None``.

    Supports several common date formats found in Indian financial data:
        "31-Mar-2024", "31/03/2024", "2024-03-31", "Mar 31, 2024", etc.
    """
    if val is None:
        return None

    if isinstance(val, float) and val != val:
        return None

    s = str(val).strip()
    if s.lower() in _MISSING_VALUES:
        return None

    FORMATS = [
        "%d-%b-%Y",   # 31-Mar-2024
        "%d/%m/%Y",   # 31/03/2024
        "%Y-%m-%d",   # 2024-03-31
        "%b %d, %Y",  # Mar 31, 2024
        "%d-%m-%Y",   # 31-03-2024
        "%b-%Y",      # Mar-2024  → treat as last day of that month
        "%B %Y",      # March 2024
        "%Y/%m/%d",   # 2024/03/31
    ]

    for fmt in FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    return None


# ===========================================================================
# 6.  normalize_boolean
# ===========================================================================

def normalize_boolean(val: Union[str, int, float, bool, None]) -> Optional[bool]:
    """
    Return True / False / None for common boolean representations.

    True  ← "yes", "y", "true", "1", "x", 1, True
    False ← "no",  "n", "false", "0", 0, False
    None  ← None, "", "--", "N/A"
    """
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        if val != val:
            return None
        return bool(val)

    s = str(val).strip().lower()
    if s in _MISSING_VALUES:
        return None
    if s in {"yes", "y", "true", "1", "x", "✓", "tick"}:
        return True
    if s in {"no", "n", "false", "0", ""}:
        return False
    return None
