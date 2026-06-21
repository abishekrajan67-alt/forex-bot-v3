"""
CONFIG V3
========================
Centralized, pair-specific configuration.

Why pair-specific config matters here:
- GBP/USD trades around 1.27000 with pip-scale moves (0.0001)
- XAU/USD trades around 2600-3600+ with dollar-scale moves (0.10-1.00+)
A single global "impulse_min_pct" or "min_sl_distance" CANNOT fit both -
percentage-based thresholds (impulse_min_pct) scale naturally across
price levels, but absolute distances (min_sl_distance) must be set
per-instrument explicitly.

Swing sensitivity also differs: gold is noisier intracandle, so a
slightly wider fractal window avoids flagging every micro-wick as a
swing point.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ======================================================
# CREDENTIALS
# ======================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TWELVE_API_KEY = os.getenv("TWELVE_API_KEY")


# ======================================================
# GLOBAL SETTINGS
# ======================================================

PAIRS = ["GBP/USD", "XAU/USD"]

DXY_SYMBOL = "DXY"          # Twelve Data symbol for Dollar Index (verify availability)
DXY_FALLBACK_SYMBOL = "EUR/USD"  # if DXY isn't available on your data plan, see note below

SCAN_SECONDS = 300
PAIR_DELAY_SECONDS = 10
COOLDOWN_SECONDS = 1800


# ======================================================
# PAIR-SPECIFIC CONFIG
# ======================================================
# These values are starting points based on standard ICT practice and
# each instrument's typical volatility profile. They are NOT
# backtested yet - treat them as a reasonable baseline to paper-trade
# and refine, not as final, proven settings.

PAIR_CONFIG = {
    "GBP/USD": {
        # Swing/fractal sensitivity on entry timeframe (5m)
        "swing_left": 2,
        "swing_right": 2,

        # Order Block impulse requirement (0.15% move to qualify)
        "ob_impulse_pct": 0.0015,

        # Minimum stop-loss distance in price units (≈10 pips)
        "min_sl_distance": 0.0010,

        # How many candles old a sweep can be and still count
        "sweep_max_age": 20,

        # How many of Daily/4H/1H must agree on direction
        "min_htf_aligned": 2,

        # Confidence + RR thresholds to fire a signal
        "min_confidence": 75,
        "min_rr": 1.8,
        "rr_target": 2.0,
    },

    "XAU/USD": {
        # Gold is noisier - slightly wider fractal window
        "swing_left": 3,
        "swing_right": 3,

        # Gold's typical intraday range is much larger in absolute
        # terms but percentage-wise this stays comparable; slightly
        # higher threshold to filter normal gold noise from real impulses
        "ob_impulse_pct": 0.0020,

        # Minimum stop-loss distance in price units (≈100 cents / $1.00)
        # Gold's pip-equivalent is much larger - this MUST be set
        # explicitly per-instrument, a GBP/USD-scale value here would
        # make every stop loss meaninglessly tight
        "min_sl_distance": 1.00,

        "sweep_max_age": 20,
        "min_htf_aligned": 2,

        # Slightly higher confidence bar for gold since the DXY
        # correlation is looser (lower weight in scoring) - we ask
        # for more confluence elsewhere to compensate
        "min_confidence": 78,
        "min_rr": 1.8,
        "rr_target": 2.0,
    },
}


# ======================================================
# SESSION TIMEZONES (unchanged from v2)
# ======================================================

from zoneinfo import ZoneInfo

LITHUANIA_TZ = ZoneInfo("Europe/Vilnius")
NY_TZ = ZoneInfo("America/New_York")


def get_pair_config(pair):
    """Safe accessor with a sane default fallback if a new pair is added later."""
    return PAIR_CONFIG.get(pair, PAIR_CONFIG["GBP/USD"])


if __name__ == "__main__":
    for p in PAIRS:
        print(p, "->", get_pair_config(p))
