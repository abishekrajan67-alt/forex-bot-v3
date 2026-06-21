"""
LIQUIDITY SWEEP ENGINE
========================
Detects ICT-style liquidity sweeps (stop hunts):
- Price wicks BEYOND a swing high/low (taking resting liquidity / stops)
- Then CLOSES back inside the range (confirms rejection, not a real breakout)

This is the "close-back-inside" definition (stronger confirmation than
a simple wick-beyond check) - it filters out genuine breakouts from
liquidity grabs that are about to reverse.

A sweep is the ICT precondition for a high-probability reversal entry:
sweep liquidity -> reverse -> tap a PD array (FVG/OB) -> entry.
"""

from market_structure import find_swings


# ======================================================
# CORE SWEEP DETECTION
# ======================================================

def detect_sweep(candles, swings, lookahead=15, tolerance=0.0):
    """
    For each swing point, checks whether a LATER candle:
      1. Wicked beyond the swing level (high beyond swing high, or
         low beyond swing low)
      2. Closed back inside (i.e. did NOT close beyond the level)

    This marks the swing as "swept" - liquidity was taken, and the
    sweep candle becomes a key reference point for the reversal.

    lookahead: how many candles after the swing to search for a sweep
    tolerance: small buffer (in price units) to avoid flagging
               insignificant micro-wicks as sweeps. Default 0 = exact level.

    Returns a list of sweep events:
    [{"swing_type": "HIGH"/"LOW", "swing_price": float, "swing_index": int,
      "sweep_index": int, "sweep_time": str, "sweep_extreme": float,
      "close_back_inside": True, "direction": "BEARISH"/"BULLISH"}, ...]

    direction = the expected reversal direction AFTER the sweep
      - sweeping a HIGH (buy-side liquidity) -> expect BEARISH reversal
      - sweeping a LOW (sell-side liquidity)  -> expect BULLISH reversal
    """
    sweeps = []

    for s in swings:
        start = s["index"] + 1
        end = min(s["index"] + 1 + lookahead, len(candles))

        for i in range(start, end):
            c = candles[i]

            if s["type"] == "HIGH":
                wicked_beyond = c["high"] > s["price"] + tolerance
                closed_back_inside = c["close"] < s["price"]

                if wicked_beyond and closed_back_inside:
                    sweeps.append({
                        "swing_type": "HIGH",
                        "swing_price": s["price"],
                        "swing_index": s["index"],
                        "sweep_index": i,
                        "sweep_time": c["time"],
                        "sweep_extreme": round(c["high"], 5),
                        "close_back_inside": True,
                        "direction": "BEARISH",
                    })
                    break  # only count the first sweep of this swing

            elif s["type"] == "LOW":
                wicked_beyond = c["low"] < s["price"] - tolerance
                closed_back_inside = c["close"] > s["price"]

                if wicked_beyond and closed_back_inside:
                    sweeps.append({
                        "swing_type": "LOW",
                        "swing_price": s["price"],
                        "swing_index": s["index"],
                        "sweep_index": i,
                        "sweep_time": c["time"],
                        "sweep_extreme": round(c["low"], 5),
                        "close_back_inside": True,
                        "direction": "BULLISH",
                    })
                    break

    return sweeps


# ======================================================
# MOST RECENT / RELEVANT SWEEP (for live signal use)
# ======================================================

def latest_relevant_sweep(candles, left=2, right=2, lookahead=15, max_age=20):
    """
    Convenience wrapper for live trading: finds swings, detects sweeps,
    and returns only the most recent sweep IF it happened recently
    (within `max_age` candles of the current bar). An old sweep is
    stale and shouldn't be used to justify a fresh entry.

    Returns the sweep dict, or None if no recent sweep exists.
    """
    swings = find_swings(candles, left, right)
    sweeps = detect_sweep(candles, swings, lookahead=lookahead)

    if not sweeps:
        return None

    current_index = len(candles) - 1
    recent = [s for s in sweeps if current_index - s["sweep_index"] <= max_age]

    if not recent:
        return None

    # Most recent sweep by index
    return max(recent, key=lambda s: s["sweep_index"])


# ======================================================
# SWEEP + PD ARRAY CONFLUENCE CHECK
# ======================================================

def sweep_supports_side(sweep, side):
    """
    Checks whether a detected sweep supports the given trade side.

    side = "BUY"  -> needs a BULLISH sweep (sell-side liquidity taken,
                      i.e. a swing LOW was swept)
    side = "SELL" -> needs a BEARISH sweep (buy-side liquidity taken,
                      i.e. a swing HIGH was swept)
    """
    if not sweep:
        return False

    if side == "BUY":
        return sweep["direction"] == "BULLISH"

    if side == "SELL":
        return sweep["direction"] == "BEARISH"

    return False


if __name__ == "__main__":
    # Hand-built deterministic sequence so the test is verifiable:
    # 1. Price chops down to form a clean swing LOW around idx 3 (price 1.2650)
    # 2. Price ranges for a few candles (lets the fractal confirm)
    # 3. A later candle wicks BELOW 1.2650 but CLOSES back above it -> sweep
    # 4. Price then reverses upward

    def candle(t, o, h, l, c):
        return {"time": t, "open": o, "high": h, "low": l, "close": c}

    test_candles = [
        candle("0", 1.2700, 1.2705, 1.2690, 1.2695),
        candle("1", 1.2695, 1.2698, 1.2675, 1.2680),
        candle("2", 1.2680, 1.2685, 1.2660, 1.2665),
        candle("3", 1.2665, 1.2670, 1.2650, 1.2655),  # swing low candidate (1.2650)
        candle("4", 1.2655, 1.2680, 1.2652, 1.2675),
        candle("5", 1.2675, 1.2690, 1.2665, 1.2685),
        candle("6", 1.2685, 1.2695, 1.2675, 1.2690),
        candle("7", 1.2690, 1.2700, 1.2680, 1.2695),
        candle("8", 1.2695, 1.2705, 1.2685, 1.2700),
        # sweep candle: wicks below 1.2650 (the swing low) but closes back above
        candle("9", 1.2700, 1.2705, 1.2640, 1.2680),
        candle("10", 1.2680, 1.2720, 1.2675, 1.2715),
        candle("11", 1.2715, 1.2740, 1.2710, 1.2735),
    ]

    swings = find_swings(test_candles, left=2, right=2)
    sweeps = detect_sweep(test_candles, swings)

    print(f"Swings found: {len(swings)}")
    for s in swings:
        print(f"  {s['type']} at idx {s['index']} price {s['price']}")

    print(f"\nSweeps found: {len(sweeps)}")
    for sw in sweeps:
        print(f"  {sw['swing_type']} ({sw['swing_price']}) swept at idx {sw['sweep_index']} "
              f"(wick to {sw['sweep_extreme']}) -> expect {sw['direction']} reversal")

    recent = latest_relevant_sweep(test_candles)
    print("\nLatest relevant sweep:", recent)
    print("Supports BUY side?", sweep_supports_side(recent, "BUY"))
    print("Supports SELL side?", sweep_supports_side(recent, "SELL"))
