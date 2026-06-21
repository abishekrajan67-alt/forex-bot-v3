"""
SIGNAL ENGINE V3
========================
The rebuilt entry logic. Replaces the old "FVG present + indicators
aligned" trigger with real ICT confluence:

    1. HTF structure aligned (Daily/4H/1H trend matches side)
    2. Recent liquidity sweep on entry TF supports the side
    3. PD array present (FVG/IFVG OR Order Block) near price
    4. Entry TF structure shows MSS/BOS in trade direction
    5. DXY correlation check (confirms or at least doesn't contradict)
    6. Candle quality + volume confirmation (kept from v2)

A signal only fires if the HARD requirements are met (structure +
sweep + PD array). Everything else (correlation, candle quality,
volume) adds/subtracts confidence points but doesn't block the trade
outright - except a strong DXY contradiction on GBP/USD, which is
also a hard block (see pair_config, Stage 6).

This module is pair-agnostic: pass in pre-fetched candle data for
every timeframe + DXY, and it returns a signal dict or None.
"""

from market_structure import structure_snapshot
from liquidity_sweep import latest_relevant_sweep, sweep_supports_side
from order_blocks import active_order_blocks, nearest_order_block
from correlation_filter import correlation_check


# ======================================================
# HARD REQUIREMENT CHECKS
# ======================================================

def htf_structure_aligned(side, daily_struct, h4_struct, h1_struct, min_aligned=2):
    """
    Checks how many of Daily/4H/1H structures align with the trade side.
    Requires at least `min_aligned` of the 3 to agree - this replaces
    the old indicator-based daily_bias()/tf_context() alignment check
    with real structure trend state from Stage 1.

    Returns (aligned: bool, count: int, reasons: list[str])
    """
    needed = "BULLISH" if side == "BUY" else "BEARISH"
    reasons = []
    count = 0

    for label, struct in [("Daily", daily_struct), ("4H", h4_struct), ("1H", h1_struct)]:
        if struct["trend"] == needed:
            count += 1
            reasons.append(f"{label} structure is {needed} (last event: {struct['last_event_type']})")

    return count >= min_aligned, count, reasons


def find_pd_array(candles, swings, price, side, fvgs, ifvgs, atr_value, ob_impulse_pct):
    """
    Looks for a PD array near current price that supports the side -
    either an FVG/IFVG (reusing your existing detect_fvgs/detect_ifvgs
    from the original bot) OR an Order Block (Stage 3).

    Returns (pd_type: str, pd_array: dict) or (None, None) if nothing found.
    Order Blocks are checked first since they're tied to confirmed
    structural breaks (slightly higher conviction); FVG/IFVG as fallback.
    """
    obs = active_order_blocks(candles, swings, impulse_min_pct=ob_impulse_pct)
    ob = nearest_order_block(obs, price, side, max_distance=atr_value * 3 if atr_value else None)

    if ob:
        return "ORDER_BLOCK", ob

    # Fallback to FVG/IFVG (caller passes these in, already computed
    # the same way your original bot's detect_fvgs/detect_ifvgs did)
    for f in fvgs:
        if side == "BUY" and f["type"] == "BULLISH":
            if f["low"] - atr_value <= price <= f["high"] + atr_value:
                return "FVG", f
        if side == "SELL" and f["type"] == "BEARISH":
            if f["low"] - atr_value <= price <= f["high"] + atr_value:
                return "FVG", f

    for f in ifvgs:
        if side == "BUY" and f["type"] == "BULLISH_IFVG":
            if f["low"] - atr_value <= price <= f["high"] + atr_value:
                return "IFVG", f
        if side == "SELL" and f["type"] == "BEARISH_IFVG":
            if f["low"] - atr_value <= price <= f["high"] + atr_value:
                return "IFVG", f

    return None, None


# ======================================================
# MAIN SIGNAL BUILDER (V3)
# ======================================================

def build_signal_v3(
    pair,
    price,
    daily_candles, h4_candles, h1_candles, entry_candles,
    dxy_candles,
    fvgs, ifvgs,             # pass pre-computed from your existing detect_fvgs/detect_ifvgs
    atr_value,
    candle_quality_buy,      # tuple (good: bool, note: str) from candle_quality(last_candle, "BUY")
    candle_quality_sell,     # tuple (good: bool, note: str) from candle_quality(last_candle, "SELL")
    volume_spike_result,     # tuple (spike: bool, ratio: float) from your existing volume_spike()
    pair_config,             # dict from Stage 6 config: min_confidence, ob_impulse_pct, swing_left/right, etc.
):
    """
    Builds a V3 signal for one pair, checking BUY and SELL sides.
    Returns the best valid signal dict, or None if nothing qualifies.

    This function assumes candle fetching, FVG/IFVG detection, ATR,
    candle quality, and volume spike have ALREADY been computed by
    the caller (reusing your existing v2 helper functions) - this
    function focuses purely on the NEW confluence logic.
    """
    swing_left = pair_config.get("swing_left", 2)
    swing_right = pair_config.get("swing_right", 2)
    ob_impulse_pct = pair_config.get("ob_impulse_pct", 0.0015)
    min_confidence = pair_config.get("min_confidence", 75)
    min_htf_aligned = pair_config.get("min_htf_aligned", 2)

    # --- Structure snapshots (Stage 1) ---
    daily_struct = structure_snapshot(daily_candles, "Daily", left=3, right=3)
    h4_struct = structure_snapshot(h4_candles, "4H", left=3, right=3)
    h1_struct = structure_snapshot(h1_candles, "1H", left=2, right=2)
    entry_struct = structure_snapshot(entry_candles, "Entry", left=swing_left, right=swing_right)
    dxy_struct = structure_snapshot(dxy_candles, "DXY", left=3, right=3) if dxy_candles else {"trend": "UNDEFINED"}

    spike, vol_ratio = volume_spike_result

    signals = []

    for side in ["BUY", "SELL"]:
        reasons = []
        warnings = []
        confidence = 0

        # ---- HARD REQUIREMENT 1: HTF structure alignment ----
        aligned, aligned_count, htf_reasons = htf_structure_aligned(
            side, daily_struct, h4_struct, h1_struct, min_aligned=min_htf_aligned
        )
        if not aligned:
            continue  # hard block - not enough HTF agreement
        reasons.extend(htf_reasons)
        confidence += aligned_count * 12

        # ---- HARD REQUIREMENT 2: Liquidity sweep on entry TF ----
        sweep = latest_relevant_sweep(
            entry_candles, left=swing_left, right=swing_right,
            lookahead=15, max_age=pair_config.get("sweep_max_age", 20)
        )
        if not sweep_supports_side(sweep, side):
            continue  # hard block - no recent supporting sweep
        reasons.append(
            f"Liquidity swept: {sweep['swing_type']} at {sweep['swing_price']} "
            f"(wick to {sweep['sweep_extreme']}) -> {sweep['direction']} reversal confirmed"
        )
        confidence += 20

        # ---- HARD REQUIREMENT 3: PD array near price ----
        entry_swings = entry_struct["swings"]
        pd_type, pd_array = find_pd_array(
            entry_candles, entry_swings, price, side, fvgs, ifvgs, atr_value, ob_impulse_pct
        )
        if not pd_array:
            continue  # hard block - no PD array to anchor entry
        reasons.append(f"{pd_type} entry zone active: {pd_array['low']} - {pd_array['high']}")
        confidence += 18

        # ---- Entry TF structure check (MSS weighted higher than BOS) ----
        needed = "BULLISH" if side == "BUY" else "BEARISH"
        if entry_struct["trend"] == needed:
            if entry_struct["last_event_type"] == "MSS":
                confidence += 15
                reasons.append(f"Entry TF shows fresh MSS confirming {needed} reversal")
            elif entry_struct["last_event_type"] == "BOS":
                confidence += 8
                reasons.append(f"Entry TF shows BOS continuing {needed} trend")
        else:
            warnings.append(f"Entry TF structure ({entry_struct['trend']}) not yet confirming {needed}")

        # ---- Correlation check (DXY) ----
        corr = correlation_check(pair, side, dxy_struct)
        confidence += corr["weight"]
        if corr["supports"]:
            reasons.append(corr["reason"])
        else:
            warnings.append(corr["reason"])
            # Hard block only for strong GBP/USD contradiction
            if pair == "GBP/USD" and corr["weight"] <= -15:
                continue

        # ---- Candle quality (use the check matching this side) ----
        good_candle, candle_note = candle_quality_buy if side == "BUY" else candle_quality_sell
        if good_candle:
            confidence += 8
            reasons.append(candle_note)
        else:
            warnings.append(candle_note)

        # ---- Volume confirmation ----
        if spike:
            confidence += 6
            reasons.append(f"Volume confirmation: {vol_ratio}x average")
        else:
            warnings.append(f"No strong volume confirmation: {vol_ratio}x average")

        # ---- Risk calculation (SL anchored to PD array, same approach as v2) ----
        if side == "BUY":
            stop_base = pd_array["low"]
            risk = max(abs(price - stop_base), pair_config.get("min_sl_distance", 0.0010))
            stop_loss = round(price - risk, 5)
            take_profit = round(price + risk * pair_config.get("rr_target", 2.0), 5)
        else:
            stop_base = pd_array["high"]
            risk = max(abs(stop_base - price), pair_config.get("min_sl_distance", 0.0010))
            stop_loss = round(price + risk, 5)
            take_profit = round(price - risk * pair_config.get("rr_target", 2.0), 5)

        rr = round(abs(take_profit - price) / abs(price - stop_loss), 2)

        if confidence >= min_confidence and rr >= pair_config.get("min_rr", 1.8):
            signals.append({
                "pair": pair,
                "side": side,
                "entry": price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "rr": rr,
                "confidence": confidence,
                "htf_aligned_count": aligned_count,
                "daily_structure": daily_struct,
                "h4_structure": h4_struct,
                "h1_structure": h1_struct,
                "entry_structure": entry_struct,
                "dxy_structure": dxy_struct,
                "sweep": sweep,
                "pd_type": pd_type,
                "pd_array": pd_array,
                "volume_ratio": vol_ratio,
                "reasons": reasons,
                "warnings": warnings,
            })

    if not signals:
        return None

    return max(signals, key=lambda s: s["confidence"])


if __name__ == "__main__":
    print("signal_engine_v3 loaded OK - run via main.py with real/replay data, not standalone.")
