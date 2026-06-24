"""
MARKET STRUCTURE ENGINE
========================
Real ICT market structure detection:
- Swing high/low (fractal) detection
- Trend state tracking (bullish/bearish structure)
- Break of Structure (BOS) - continuation signal
- Market Structure Shift (MSS) - reversal signal

This replaces indicator-based "structure" (EMA/VWAP alignment) with
actual price-action structure, which is what ICT structure really means.
"""

from datetime import datetime


# ======================================================
# SWING POINT DETECTION (Fractals)
# ======================================================

def find_swings(candles, left=2, right=2):
    """
    Detects swing highs and swing lows using fractal logic.

    A swing high = a candle whose high is higher than `left` candles
    before it AND `right` candles after it.
    A swing low = the inverse.

    left/right=2 -> tighter, more swings, good for entry timeframes (5m/15m)
    left/right=3-5 -> wider, cleaner swings, good for HTF (1H/4H)

    Returns a list of swing points in chronological order:
    [{"type": "HIGH"/"LOW", "price": float, "index": int, "time": str}, ...]
    """
    swings = []
    n = len(candles)

    for i in range(left, n - right):
        window_high = candles[i]["high"]
        window_low = candles[i]["low"]

        is_swing_high = all(
            window_high > candles[i - j]["high"] for j in range(1, left + 1)
        ) and all(
            window_high > candles[i + j]["high"] for j in range(1, right + 1)
        )

        is_swing_low = all(
            window_low < candles[i - j]["low"] for j in range(1, left + 1)
        ) and all(
            window_low < candles[i + j]["low"] for j in range(1, right + 1)
        )

        if is_swing_high:
            swings.append({
                "type": "HIGH",
                "price": round(window_high, 5),
                "index": i,
                "time": candles[i]["time"],
            })

        if is_swing_low:
            swings.append({
                "type": "LOW",
                "price": round(window_low, 5),
                "index": i,
                "time": candles[i]["time"],
            })

    return swings


# ======================================================
# STRUCTURE STATE (BOS / MSS)
# ======================================================

def analyze_structure(candles, left=2, right=2):
    """
    Walks through swing points in order and tracks structure state.

    Logic:
    - Maintain the last confirmed swing high (lastHigh) and swing low (lastLow)
    - Maintain current trend bias: BULLISH, BEARISH, or UNDEFINED
    - When price closes ABOVE lastHigh:
        - If trend was BEARISH or UNDEFINED -> this is an MSS (reversal)
        - If trend was BULLISH -> this is a BOS (continuation)
        - Trend becomes BULLISH, lastHigh updates
    - When price closes BELOW lastLow:
        - If trend was BULLISH or UNDEFINED -> this is an MSS (reversal)
        - If trend was BEARISH -> this is a BOS (continuation)
        - Trend becomes BEARISH, lastLow updates

    Returns the full structure state plus a log of all BOS/MSS events,
    so we know not just current trend but *how it got there*.
    """
    swings = find_swings(candles, left, right)

    if len(swings) < 2:
        return {
            "trend": "UNDEFINED",
            "last_high": None,
            "last_low": None,
            "last_event": None,
            "events": [],
            "swings": swings,
        }

    trend = "UNDEFINED"
    last_high = None
    last_low = None
    events = []

    # Seed initial reference points from the first two swings
    for s in swings:
        if s["type"] == "HIGH" and last_high is None:
            last_high = s
        if s["type"] == "LOW" and last_low is None:
            last_low = s
        if last_high and last_low:
            break

    # Walk forward candle by candle, checking closes against reference levels
    start_index = max(s["index"] for s in swings[:2]) if len(swings) >= 2 else 0

    for i in range(start_index + 1, len(candles)):
        close = candles[i]["close"]
        time = candles[i]["time"]

        # Bullish break: close above last_high
        if last_high and close > last_high["price"]:
            event_type = "MSS" if trend in ("BEARISH", "UNDEFINED") else "BOS"

            events.append({
                "type": event_type,
                "direction": "BULLISH",
                "level": last_high["price"],
                "close": round(close, 5),
                "time": time,
                "index": i,
            })

            trend = "BULLISH"

            # Update last_high to the most recent swing high formed before this break
            candidates = [s for s in swings if s["type"] == "HIGH" and s["index"] < i and s["price"] > last_high["price"]]
            if candidates:
                last_high = candidates[-1]
            else:
                last_high = {"type": "HIGH", "price": close, "index": i, "time": time}

        # Bearish break: close below last_low
        if last_low and close < last_low["price"]:
            event_type = "MSS" if trend in ("BULLISH", "UNDEFINED") else "BOS"

            events.append({
                "type": event_type,
                "direction": "BEARISH",
                "level": last_low["price"],
                "close": round(close, 5),
                "time": time,
                "index": i,
            })

            trend = "BEARISH"

            candidates = [s for s in swings if s["type"] == "LOW" and s["index"] < i and s["price"] < last_low["price"]]
            if candidates:
                last_low = candidates[-1]
            else:
                last_low = {"type": "LOW", "price": close, "index": i, "time": time}

        # Keep reference points up to date with newer untested swings too
        # (so last_high/last_low always reflect the most recent relevant swing)
        for s in swings:
            if s["index"] == i:
                if s["type"] == "HIGH":
                    if trend == "BULLISH" and (last_high is None or s["price"] > last_high["price"]):
                        last_high = s
                if s["type"] == "LOW":
                    if trend == "BEARISH" and (last_low is None or s["price"] < last_low["price"]):
                        last_low = s

    last_event = events[-1] if events else None

    return {
        "trend": trend,
        "last_high": last_high,
        "last_low": last_low,
        "last_event": last_event,
        "events": events[-10:],  # keep recent history only
        "swings": swings[-50:],
    }


# ======================================================
# RECENT STRUCTURE SUMMARY (for signal engine consumption)
# ======================================================

def structure_snapshot(candles, label, left=2, right=2):
    """
    Convenience wrapper: returns a clean snapshot of current structure
    for a given timeframe, ready to plug into the signal engine.
    """
    result = analyze_structure(candles, left, right)

    return {
        "label": label,
        "trend": result["trend"],
        "last_high": result["last_high"]["price"] if result["last_high"] else None,
        "last_low": result["last_low"]["price"] if result["last_low"] else None,
        "last_event_type": result["last_event"]["type"] if result["last_event"] else None,
        "last_event_direction": result["last_event"]["direction"] if result["last_event"] else None,
        "last_event_time": result["last_event"]["time"] if result["last_event"] else None,
        "recent_events": result["events"],
        "swings": result["swings"],
    }


if __name__ == "__main__":
    # Quick sanity test with synthetic data
    import random

    random.seed(42)
    test_candles = []
    price = 1.2700

    for i in range(200):
        o = price
        c = o + random.uniform(-0.0015, 0.0015)
        h = max(o, c) + random.uniform(0, 0.0008)
        l = min(o, c) - random.uniform(0, 0.0008)
        test_candles.append({
            "time": f"2026-06-{(i % 28) + 1:02d}T{(i % 24):02d}:00:00",
            "open": round(o, 5),
            "high": round(h, 5),
            "low": round(l, 5),
            "close": round(c, 5),
        })
        price = c

    snap = structure_snapshot(test_candles, "TEST")
    print("Trend:", snap["trend"])
    print("Last High:", snap["last_high"])
    print("Last Low:", snap["last_low"])
    print("Last Event:", snap["last_event_type"], snap["last_event_direction"])
    print("Recent events count:", len(snap["recent_events"]))