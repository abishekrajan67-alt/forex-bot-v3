"""
CORRELATION FILTER ENGINE
========================
Cross-instrument confirmation before firing a signal.

GBP/USD <-> DXY (Dollar Index):
    Largely INVERSE relationship (USD is the quote currency... wait,
    GBP/USD = GBP is base, USD is quote. DXY measures USD strength.
    When DXY rises (USD strengthens), GBP/USD tends to FALL, and
    vice versa. So GBP/USD and DXY are typically INVERSELY correlated.

    For a GBP/USD BUY signal -> we want DXY showing BEARISH structure
    (USD weakening) as confirmation.
    For a GBP/USD SELL signal -> we want DXY showing BULLISH structure
    (USD strengthening) as confirmation.

XAU/USD (Gold) <-> DXY:
    Also typically INVERSE (gold priced in USD - weaker dollar makes
    gold cheaper for other currencies, demand rises, price rises).
    But gold has a second major driver: risk sentiment / yields.
    Gold often rallies on risk-off moves (flight to safety) even when
    DXY is flat or mixed. So gold's correlation to DXY is real but
    looser than GBP/USD's - we treat it as a supporting filter, not
    a hard requirement, and weight it lower in the signal engine.

This module doesn't fetch data itself (keeps it decoupled / testable);
it takes a DXY structure snapshot (from market_structure.py, already
computed by the caller) and tells you whether it supports a given
trade idea on a given instrument.
"""


# ======================================================
# CORRELATION RULES
# ======================================================

def gbpusd_correlation_check(side, dxy_structure):
    """
    side: "BUY" or "SELL" on GBP/USD
    dxy_structure: output of structure_snapshot() run on DXY candles

    Returns: {"supports": bool, "reason": str, "weight": int}

    This is treated as a meaningful confirmation (not optional) for
    GBP/USD since the inverse relationship is historically strong and
    consistent - so it carries real weight in the scoring system.
    """
    trend = dxy_structure.get("trend", "UNDEFINED")

    if side == "BUY":
        if trend == "BEARISH":
            return {"supports": True, "reason": "DXY structure BEARISH (USD weak) confirms GBP/USD BUY", "weight": 12}
        if trend == "BULLISH":
            return {"supports": False, "reason": "DXY structure BULLISH (USD strong) contradicts GBP/USD BUY", "weight": -15}
        return {"supports": False, "reason": "DXY structure UNDEFINED, no confirmation", "weight": 0}

    if side == "SELL":
        if trend == "BULLISH":
            return {"supports": True, "reason": "DXY structure BULLISH (USD strong) confirms GBP/USD SELL", "weight": 12}
        if trend == "BEARISH":
            return {"supports": False, "reason": "DXY structure BEARISH (USD weak) contradicts GBP/USD SELL", "weight": -15}
        return {"supports": False, "reason": "DXY structure UNDEFINED, no confirmation", "weight": 0}

    return {"supports": False, "reason": "Invalid side", "weight": 0}


def xauusd_correlation_check(side, dxy_structure):
    """
    side: "BUY" or "SELL" on XAU/USD
    dxy_structure: output of structure_snapshot() run on DXY candles

    Gold's DXY relationship is real but looser than GBP/USD's (risk
    sentiment and yields also drive gold independently of the dollar).
    This is scored as a SUPPORTING filter - smaller weight, and it
    never hard-blocks a signal the way a strong GBP/USD contradiction
    can, since gold can rally on risk-off even with a flat/mixed DXY.
    """
    trend = dxy_structure.get("trend", "UNDEFINED")

    if side == "BUY":
        if trend == "BEARISH":
            return {"supports": True, "reason": "DXY structure BEARISH supports XAUUSD BUY (inverse)", "weight": 6}
        if trend == "BULLISH":
            return {"supports": False, "reason": "DXY structure BULLISH is a headwind for XAUUSD BUY", "weight": -6}
        return {"supports": False, "reason": "DXY structure UNDEFINED, no confirmation", "weight": 0}

    if side == "SELL":
        if trend == "BULLISH":
            return {"supports": True, "reason": "DXY structure BULLISH supports XAUUSD SELL (inverse)", "weight": 6}
        if trend == "BEARISH":
            return {"supports": False, "reason": "DXY structure BEARISH is a headwind for XAUUSD SELL", "weight": -6}
        return {"supports": False, "reason": "DXY structure UNDEFINED, no confirmation", "weight": 0}

    return {"supports": False, "reason": "Invalid side", "weight": 0}


# ======================================================
# DISPATCHER
# ======================================================

def correlation_check(pair, side, dxy_structure):
    """
    Routes to the correct correlation logic based on pair.
    Add new pairs here as the bot expands (Stage 6).
    """
    if pair == "GBP/USD":
        return gbpusd_correlation_check(side, dxy_structure)

    if pair == "XAU/USD":
        return xauusd_correlation_check(side, dxy_structure)

    # Default: no correlation rule defined for this pair yet
    return {"supports": False, "reason": f"No correlation rule defined for {pair}", "weight": 0}


if __name__ == "__main__":
    # Simulate a few DXY states and check both pairs against them
    dxy_bearish = {"trend": "BEARISH"}
    dxy_bullish = {"trend": "BULLISH"}
    dxy_undefined = {"trend": "UNDEFINED"}

    print("--- GBP/USD BUY ---")
    print(" DXY Bearish:", correlation_check("GBP/USD", "BUY", dxy_bearish))
    print(" DXY Bullish:", correlation_check("GBP/USD", "BUY", dxy_bullish))
    print(" DXY Undefined:", correlation_check("GBP/USD", "BUY", dxy_undefined))

    print("\n--- XAU/USD SELL ---")
    print(" DXY Bullish:", correlation_check("XAU/USD", "SELL", dxy_bullish))
    print(" DXY Bearish:", correlation_check("XAU/USD", "SELL", dxy_bearish))

    print("\n--- Unknown pair ---")
    print(correlation_check("EUR/USD", "BUY", dxy_bearish))
