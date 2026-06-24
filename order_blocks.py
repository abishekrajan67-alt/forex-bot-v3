"""
ORDER BLOCK ENGINE
========================
Detects ICT Order Blocks (OB) - a second PD array type alongside FVG/IFVG.

Definition used here (standard ICT):
- Bullish OB: the LAST down-close candle before a strong impulsive
  move UP that breaks structure (a swing high).
- Bearish OB: the LAST up-close candle before a strong impulsive
  move DOWN that breaks structure (a swing low).

The "strong impulsive move" requirement matters - without it, every
down-candle before any up-candle would qualify, producing noise.
We require the impulse leg to actually break a recent swing point
(i.e. cause a BOS/MSS), which ties OB detection directly into the
market_structure engine from Stage 1.

Mitigation-based invalidation:
- An OB is considered "fresh"/valid until price CLOSES fully through
  it (not just wicks into it - a wick into an OB is often the entry
  itself). Once mitigated, the OB is removed from the active list.
"""

from market_structure import find_swings


# ======================================================
# ORDER BLOCK DETECTION
# ======================================================

def detect_order_blocks(candles, swings, impulse_min_pct=0.0015, lookback=100):
    """
    Scans recent candles for order blocks tied to structural breaks.

    impulse_min_pct: minimum % move (as decimal, e.g. 0.0015 = 0.15%)
        required for the breakout leg to qualify as "impulsive".
        Tune this per instrument (forex majors vs gold need different
        thresholds since gold's price scale is totally different -
        pass a pair-specific value from config rather than relying
        on the default for XAUUSD).
    lookback: how many recent candles to scan for OB candidates.

    Returns a list of order blocks (most recent first), each:
    {
        "type": "BULLISH"/"BEARISH",
        "low": float, "high": float, "mid": float,
        "candle_index": int, "formed_time": str,
        "broke_level": float,   # the swing level this OB's impulse broke
        "mitigated": bool,
    }
    """
    recent = candles[-lookback:]
    offset = len(candles) - len(recent)  # to map recent-index back to global index

    swing_highs = sorted([s for s in swings if s["type"] == "HIGH"], key=lambda s: s["index"])
    swing_lows = sorted([s for s in swings if s["type"] == "LOW"], key=lambda s: s["index"])

    order_blocks = []

    for i in range(1, len(recent) - 1):
        global_i = i + offset
        candle = recent[i]
        prev = recent[i - 1]

        # --- Bullish OB candidate: prev candle closed DOWN, this candle is a strong up-move
        if prev["close"] < prev["open"]:
            move_pct = (candle["close"] - prev["close"]) / prev["close"] if prev["close"] else 0

            if move_pct >= impulse_min_pct:
                # Does this impulse break a recent swing high (confirms it's structurally significant)?
                broken = [s for s in swing_highs if s["index"] < global_i and candle["close"] > s["price"]]

                if broken:
                    broke_level = broken[-1]["price"]
                    order_blocks.append({
                        "type": "BULLISH",
                        "low": round(prev["low"], 5),
                        "high": round(prev["high"], 5),
                        "mid": round((prev["low"] + prev["high"]) / 2, 5),
                        "candle_index": global_i - 1,
                        "formed_time": prev["time"],
                        "broke_level": broke_level,
                        "mitigated": False,
                    })

        # --- Bearish OB candidate: prev candle closed UP, this candle is a strong down-move
        if prev["close"] > prev["open"]:
            move_pct = (prev["close"] - candle["close"]) / prev["close"] if prev["close"] else 0

            if move_pct >= impulse_min_pct:
                broken = [s for s in swing_lows if s["index"] < global_i and candle["close"] < s["price"]]

                if broken:
                    broke_level = broken[-1]["price"]
                    order_blocks.append({
                        "type": "BEARISH",
                        "low": round(prev["low"], 5),
                        "high": round(prev["high"], 5),
                        "mid": round((prev["low"] + prev["high"]) / 2, 5),
                        "candle_index": global_i - 1,
                        "formed_time": prev["time"],
                        "broke_level": broke_level,
                        "mitigated": False,
                    })

    return order_blocks


# ======================================================
# MITIGATION CHECK
# ======================================================

def apply_mitigation(order_blocks, candles):
    """
    Marks each OB as mitigated if any candle AFTER it formed closed
    fully through it:
      - Bullish OB mitigated if a later candle CLOSES below ob["low"]
      - Bearish OB mitigated if a later candle CLOSES above ob["high"]

    A wick into the OB does NOT mitigate it - that's expected (it's
    often the entry trigger itself). Only a full close-through kills it.
    """
    for ob in order_blocks:
        for c in candles[ob["candle_index"] + 1:]:
            if ob["type"] == "BULLISH" and c["close"] < ob["low"]:
                ob["mitigated"] = True
                break
            if ob["type"] == "BEARISH" and c["close"] > ob["high"]:
                ob["mitigated"] = True
                break

    return order_blocks


def active_order_blocks(candles, swings, impulse_min_pct=0.0015, lookback=100):
    """
    Full pipeline: detect OBs, apply mitigation, return only the
    still-valid (unmitigated) ones, most recent first.
    """
    obs = detect_order_blocks(candles, swings, impulse_min_pct, lookback)
    obs = apply_mitigation(obs, candles)
    active = [ob for ob in obs if not ob["mitigated"]]
    active.sort(key=lambda ob: ob["candle_index"], reverse=True)
    return active


# ======================================================
# NEAREST OB TO CURRENT PRICE (for signal engine use)
# ======================================================

def nearest_order_block(order_blocks, price, side, max_distance=None):
    """
    Finds the nearest active order block that matches the trade side
    and is reasonably close to current price.

    side = "BUY"  -> looks for BULLISH OBs at/below price
    side = "SELL" -> looks for BEARISH OBs at/above price

    max_distance: optional cap (price units) on how far the OB can be
    from current price to still count as "in play".
    """
    wanted_type = "BULLISH" if side == "BUY" else "BEARISH"
    candidates = [ob for ob in order_blocks if ob["type"] == wanted_type]

    if side == "BUY":
        candidates = [ob for ob in candidates if ob["low"] <= price]
    else:
        candidates = [ob for ob in candidates if ob["high"] >= price]

    if max_distance is not None:
        candidates = [
            ob for ob in candidates
            if abs(price - (ob["high"] if side == "BUY" else ob["low"])) <= max_distance
        ]

    if not candidates:
        return None

    # Nearest = smallest distance to price
    candidates.sort(key=lambda ob: abs(price - ob["mid"]))
    return candidates[0]


if __name__ == "__main__":
    def candle(t, o, h, l, c):
        return {"time": t, "open": o, "high": h, "low": l, "close": c}

    # Build a sequence with enough lead-in candles so the fractal detector
    # has room on the left side too. Sequence: chop -> swing high forms ->
    # pullback forms a down-close candle -> strong impulsive break above
    # the swing high -> should register as a bullish OB.
    test_candles = [
        candle("0", 1.2680, 1.2685, 1.2670, 1.2675),
        candle("1", 1.2675, 1.2690, 1.2665, 1.2680),
        candle("2", 1.2680, 1.2700, 1.2675, 1.2695),
        candle("3", 1.2695, 1.2715, 1.2690, 1.2710),  # swing high candidate (~1.2715)
        candle("4", 1.2710, 1.2712, 1.2680, 1.2685),
        candle("5", 1.2685, 1.2688, 1.2660, 1.2665),  # swing low candidate
        candle("6", 1.2665, 1.2670, 1.2640, 1.2645),  # <- down-close OB candle
        candle("7", 1.2645, 1.2760, 1.2645, 1.2750),  # strong impulsive break above 1.2715
        candle("8", 1.2750, 1.2770, 1.2740, 1.2765),
        candle("9", 1.2765, 1.2780, 1.2755, 1.2775),
    ]

    swings = find_swings(test_candles, left=2, right=2)
    print("Swings:")
    for s in swings:
        print(f"  {s['type']} idx {s['index']} price {s['price']}")

    obs = active_order_blocks(test_candles, swings, impulse_min_pct=0.001)
    print(f"\nActive Order Blocks: {len(obs)}")
    for ob in obs:
        print(f"  {ob['type']} zone {ob['low']}-{ob['high']} formed idx {ob['candle_index']} "
              f"broke level {ob['broke_level']} mitigated={ob['mitigated']}")

    nearest = nearest_order_block(obs, price=1.2775, side="BUY")
    print("\nNearest BUY-side OB to price 1.2775:", nearest)
