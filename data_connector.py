"""
POLYGON.IO (MASSIVE) DATA CONNECTOR
========================
Replaces the old Twelve Data get_candles() function. Returns candles
in the EXACT same dict format your bot already uses:

    {"time": str, "open": float, "high": float, "low": float,
     "close": float, "volume": float}

so Stages 1-6 (market_structure, liquidity_sweep, order_blocks,
correlation_filter, signal_engine) need ZERO changes.

Note: Polygon.io rebranded to "Massive" (massive.com) - same API,
same key, just a new dashboard/brand. Endpoints below still use the
api.polygon.io host as of this writing; verify in your dashboard
docs if endpoints have moved by the time you deploy.

FREE TIER LIMIT: 5 requests/minute on the aggregates endpoint.
A single scan cycle (Daily+4H+1H+Entry+DXY) x 2 pairs = up to 10
calls. We throttle + cache to stay safe - see fetch_with_throttle().
"""

import os
import time
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

POLYGON_API_KEY = os.getenv("POLYGON_API_KEY")
BASE_URL = "https://api.polygon.io"

# Simple in-memory cache: {cache_key: (timestamp_fetched, data)}
_CACHE = {}
_CACHE_TTL_SECONDS = 55  # slightly under 1 min, matches typical scan cadence

# Throttling: track call timestamps to stay under 5/min
_CALL_TIMESTAMPS = []
_MAX_CALLS_PER_MINUTE = 5


# ======================================================
# SYMBOL MAPPING
# ======================================================

def to_polygon_symbol(pair, is_index=False):
    """
    Converts your bot's pair format to Polygon's symbol format.

    Forex pairs: "GBP/USD" -> "C:GBPUSD"
    Indices (DXY): pass is_index=True, expects pair like "DXY" -> "I:DXY"
    """
    if is_index:
        return f"I:{pair}"

    return "C:" + pair.replace("/", "")


# Maps your bot's interval names to Polygon's (multiplier, timespan)
INTERVAL_MAP = {
    "1day": (1, "day"),
    "4h": (4, "hour"),
    "1h": (1, "hour"),
    "15min": (15, "minute"),
    "5min": (5, "minute"),
}


# ======================================================
# THROTTLING
# ======================================================

def _wait_for_rate_limit():
    """
    Blocks if necessary to stay under _MAX_CALLS_PER_MINUTE.
    Simple sliding-window throttle.
    """
    global _CALL_TIMESTAMPS
    now = time.time()

    _CALL_TIMESTAMPS = [t for t in _CALL_TIMESTAMPS if now - t < 60]

    if len(_CALL_TIMESTAMPS) >= _MAX_CALLS_PER_MINUTE:
        oldest = _CALL_TIMESTAMPS[0]
        sleep_time = 60 - (now - oldest) + 0.5
        if sleep_time > 0:
            print(f"[throttle] Rate limit reached, sleeping {round(sleep_time, 1)}s")
            time.sleep(sleep_time)

    _CALL_TIMESTAMPS.append(time.time())


# ======================================================
# CORE FETCH
# ======================================================

def get_candles(pair, interval, outputsize=120, is_index=False):
    """
    Drop-in replacement for the old Twelve Data get_candles().
    Same signature shape, same return format.

    pair: "GBP/USD", "XAU/USD", or "DXY" (with is_index=True)
    interval: one of INTERVAL_MAP keys ("1day", "4h", "1h", "15min", "5min")
    outputsize: approximate number of candles wanted (Polygon returns
        whatever's in the date range; we compute a date range that
        should comfortably cover outputsize bars, then trim)
    """
    if interval not in INTERVAL_MAP:
        print(f"Unsupported interval: {interval}")
        return []

    multiplier, timespan = INTERVAL_MAP[interval]
    symbol = to_polygon_symbol(pair, is_index=is_index)

    cache_key = f"{symbol}_{interval}_{outputsize}"
    cached = _CACHE.get(cache_key)
    if cached and (time.time() - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    # Compute a from/to date range generous enough to cover outputsize bars
    bars_to_days = {
        "1day": outputsize * 1.6,
        "4h": outputsize * 4 / 24 * 1.6,
        "1h": outputsize / 24 * 1.6,
        "15min": outputsize * 15 / (60 * 24) * 1.6,
        "5min": outputsize * 5 / (60 * 24) * 1.6,
    }
    days_back = max(int(bars_to_days.get(interval, 30)) + 5, 5)

    to_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    from_date = (datetime.now(timezone.utc) - __import__("datetime").timedelta(days=days_back)).strftime("%Y-%m-%d")

    url = f"{BASE_URL}/v2/aggs/ticker/{symbol}/range/{multiplier}/{timespan}/{from_date}/{to_date}"
    params = {
        "adjusted": "true",
        "sort": "asc",
        "limit": 50000,
        "apiKey": POLYGON_API_KEY,
    }

    try:
        _wait_for_rate_limit()
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()

        if data.get("status") not in ("OK", "DELAYED") or "results" not in data:
            print(f"{pair} {interval} Polygon error: {data}")
            return []

        candles = []
        for bar in data["results"]:
            dt = datetime.fromtimestamp(bar["t"] / 1000, tz=timezone.utc)
            candles.append({
                "time": dt.isoformat(),
                "open": float(bar["o"]),
                "high": float(bar["h"]),
                "low": float(bar["l"]),
                "close": float(bar["c"]),
                "volume": float(bar.get("v", 1) or 1),
            })

        # Trim to the most recent `outputsize` candles
        candles = candles[-outputsize:]

        _CACHE[cache_key] = (time.time(), candles)
        return candles

    except Exception as e:
        print(f"{pair} {interval} candle fetch error: {e}")
        return []


# ======================================================
# DXY-SPECIFIC HELPER (with EUR/USD fallback)
# ======================================================

def get_dxy_candles(interval, outputsize=120):
    """
    Tries to fetch DXY (I:DXY) from Polygon. If it returns empty
    (symbol not available on your plan), falls back to EUR/USD
    inverted as a rough proxy - EUR/USD is ~57% of DXY's basket
    weight, so an inverse move is a reasonable approximation when
    the real index isn't accessible.

    Returns (candles, used_fallback: bool) so the caller can log/warn
    appropriately if running on the proxy.
    """
    candles = get_candles("DXY", interval, outputsize, is_index=True)

    if candles:
        return candles, False

    print("[get_dxy_candles] DXY unavailable, falling back to inverted EUR/USD proxy")
    eurusd = get_candles("EUR/USD", interval, outputsize)

    if not eurusd:
        return [], True

    inverted = []
    for c in eurusd:
        inverted.append({
            "time": c["time"],
            "open": round(1 / c["open"], 5) if c["open"] else 0,
            "high": round(1 / c["low"], 5) if c["low"] else 0,   # inverted: low becomes high
            "low": round(1 / c["high"], 5) if c["high"] else 0,  # inverted: high becomes low
            "close": round(1 / c["close"], 5) if c["close"] else 0,
            "volume": c["volume"],
        })

    return inverted, True


if __name__ == "__main__":
    if not POLYGON_API_KEY:
        print("WARNING: POLYGON_API_KEY not set in .env - set it before running for real.")
        print("This test will likely fail/return empty without a valid key.\n")

    print("Testing GBP/USD 1h fetch...")
    c = get_candles("GBP/USD", "1h", outputsize=20)
    print(f"  Got {len(c)} candles")
    if c:
        print(f"  Latest: {c[-1]}")

    print("\nTesting DXY fetch (with fallback)...")
    dxy, used_fallback = get_dxy_candles("1h", outputsize=20)
    print(f"  Got {len(dxy)} candles, used_fallback={used_fallback}")
