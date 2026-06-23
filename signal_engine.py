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
    needed = "BULLISH" if side == "BUY" else "BEARISH"
    reasons = []
    count = 0
    for label, struct in [("Daily", daily_struct), ("4H", h4_struct), ("1H", h1_struct)]:
        if struct["trend"] == needed:
            count += 1
            reasons.append(f"{label} structure is {needed} (last event: {struct['last_event_type']})")
    return count >= min_aligned, count, reasons


def find_pd_array(candles, swings, price, side, fvgs, ifvgs, atr_value, ob_impulse_pct):
    obs = active_order_blocks(candles, swings, impulse_min_pct=ob_impulse_pct)
    ob = nearest_order_block(obs, price, side, max_distance=atr_value * 3 if atr_value else None)
    if ob:
        return "ORDER_BLOCK", ob

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
    fvgs, ifvgs,
    atr_value,
    candle_quality_buy,
    candle_quality_sell,
    volume_spike_result,
    pair_config,
):
    swing_left = pair_config.get("swing_left", 2)
    swing_right = pair_config.get("swing_right", 2)
    ob_impulse_pct = pair_config.get("ob_impulse_pct", 0.0015)
    min_confidence = pair_config.get("min_confidence", 75)
    min_htf_aligned = pair_config.get("min_htf_aligned", 2)

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
            continue
        reasons.extend(htf_reasons)
        confidence += aligned_count * 12

        # ---- HARD REQUIREMENT 2: Liquidity sweep ----
        sweep = latest_relevant_sweep(
            entry_candles, left=swing_left, right=swing_right,
            lookahead=15, max_age=pair_config.get("sweep_max_age", 20)
        )
        if not sweep_supports_side(sweep, side):
            continue
        reasons.append(
            f"Liquidity swept: {sweep['swing_type']} at {sweep['swing_price']} "
            f"(wick to {sweep['sweep_extreme']}) -> {sweep['direction']} reversal confirmed"
        )
        confidence += 20

        # ---- HARD REQUIREMENT 3: PD array ----
        entry_swings = entry_struct["swings"]
        pd_type, pd_array = find_pd_array(
            entry_candles, entry_swings, price, side, fvgs, ifvgs, atr_value, ob_impulse_pct
        )
        if not pd_array:
            continue
        reasons.append(f"{pd_type} entry zone active: {pd_array['low']} - {pd_array['high']}")
        confidence += 18

        # ---- Entry TF structure ----
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

        # ---- DXY Correlation ----
        corr = correlation_check(pair, side, dxy_struct)
        confidence += corr["weight"]
        if corr["supports"]:
            reasons.append(corr["reason"])
        else:
            warnings.append(corr["reason"])
            if pair == "GBP/USD" and corr["weight"] <= -15:
                continue

        # ---- Candle quality ----
        good_candle, candle_note = candle_quality_buy if side == "BUY" else candle_quality_sell
        if good_candle:
            confidence += 8
            reasons.append(candle_note)
        else:
            warnings.append(candle_note)

        # ---- Volume ----
        if spike:
            confidence += 6
            reasons.append(f"Volume confirmation: {vol_ratio}x average")
        else:
            warnings.append(f"No strong volume confirmation: {vol_ratio}x average")

        # ======================================================
        # PROFESSIONAL SLIPPAGE PROTECTION (UPDATED)
        # ======================================================
        base_atr = atr_value or 0.0010

        if pair == "XAU/USD":
            slippage_multiplier = 0.65
        else:
            slippage_multiplier = 0.45

        slippage_buffer = base_atr * slippage_multiplier
        min_buffer = pair_config.get("min_sl_distance", 0.0010) * 0.8
        slippage_buffer = max(slippage_buffer, min_buffer)

        if side == "BUY":
            stop_base = pd_array["low"] - slippage_buffer
            risk = max(abs(price - stop_base), pair_config.get("min_sl_distance", 0.0010))
            stop_loss = round(price - risk, 5)
            take_profit = round(price + risk * pair_config.get("rr_target", 2.0), 5)
        else:
            stop_base = pd_array["high"] + slippage_buffer
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
