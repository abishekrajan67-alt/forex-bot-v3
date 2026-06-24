"""
POLYGON.IO (MASSIVE) DATA CONNECTOR - UPDATED WITH SLIPPAGE / PRICE RECONCILIATION
========================
Enhanced version with:
- get_current_price() helper for real-time price + logging
- Better support for price validation vs broker
"""

import os
import time
import requests
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

POLYGON_API_KEY = os.getenv("POLYGON_API_KEY")
BASE_URL = "https://api.polygon.io"

# Simple in-memory cache
_CACHE = {}
_CACHE_TTL_SECONDS = 55

_CALL_TIMESTAMPS = []
_MAX_CALLS_PER_MINUTE = 5


def to_polygon_symbol(pair, is_index=False):
    if is_index:
        return f"I:{pair}"
    return "C:" + pair.replace("/", "")


INTERVAL_MAP = {
    "1day": (1, "day"),
    "4h": (4, "hour"),
    "1h": (1, "hour"),
    "15min": (15, "minute"),
    "5min": (5, "minute"),
}


def _wait_for_rate_limit():
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


def get_candles(pair, interval, outputsize=120, is_index=False):
    """Original function - unchanged behavior"""
    if interval not in INTERVAL_MAP:
        print(f"Unsupported interval: {interval}")
        return []

    multiplier, timespan = INTERVAL_MAP[interval]
    symbol = to_polygon_symbol(pair, is_index=is_index)

    cache_key = f"{symbol}_{interval}_{outputsize}"
    cached = _CACHE.get(cache_key)
    if cached and (time.time() - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    bars_to_days = {
        "1day": outputsize * 1.6,
        "4h": outputsize * 4 / 24 * 1.6,
        "1h": outputsize / 24 * 1.6,
        "15min": outputsize * 15 / (60 * 24) * 1.6,
        "5min": outputsize * 5 / (60 * 24) * 1.6,
    }
    days_back = max(int(bars_to_days.get(interval, 30)) + 5, 5)

    to_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    from_date = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")

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

        candles = candles[-outputsize:]
        _CACHE[cache_key] = (time.time(), candles)
        return candles

    except Exception as e:
        print(f"{pair} {interval} candle fetch error: {e}")
        return []


def get_dxy_candles(interval, outputsize=120):
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
            "high": round(1 / c["low"], 5) if c["low"] else 0,
            "low": round(1 / c["high"], 5) if c["high"] else 0,
            "close": round(1 / c["close"], 5) if c["close"] else 0,
            "volume": c["volume"],
        })
    return inverted, True


# ======================================================
# NEW: PRICE RECONCILIATION + SLIPPAGE HELPER
# ======================================================

def get_current_price(pair, interval="5min"):
    """
    Returns latest price from Polygon with rich logging.
    Use this for broker price comparison / slippage checks.
    """
    candles = get_candles(pair, interval, outputsize=5)
    if not candles:
        print(f"[PRICE CHECK] Failed to get current price for {pair}")
        return None

    latest = candles[-1]
    price = latest["close"]

    # Simple recent volatility estimate (for dynamic slippage buffer)
    if len(candles) >= 3:
        recent_range = max(c["high"] for c in candles[-3:]) - min(c["low"] for c in candles[-3:])
        atr_approx = recent_range / 3
    else:
        atr_approx = 0.0

    print(f"[PRICE CHECK] Polygon {pair} latest close: {price} | Approx recent range: {atr_approx:.4f} | {latest['time']}")

    return {
        "price": price,
        "timestamp": latest["time"],
        "atr_approx": atr_approx,
        "source": "Polygon"
    }


if __name__ == "__main__":
    if not POLYGON_API_KEY:
        print("WARNING: POLYGON_API_KEY not set in .env")

    print("Testing get_current_price for XAU/USD...")
    result = get_current_price("XAU/USD")
    if result:
        print(f"  Current price: {result['price']}")
