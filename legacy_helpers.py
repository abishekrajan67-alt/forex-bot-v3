"""
LEGACY HELPERS (kept from v2, unchanged)
========================
These functions worked well in your original bot and don't need
replacing - only the entry TRIGGER logic (FVG-only -> full confluence)
changed in v3. This module ports them over as-is:

- FVG/IFVG detection
- ATR, candle quality, volume spike
- Session range / NDOG / NWOG / True Day Open
- Time helpers

Source: your original forex-ai-bot main script.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

NY_TZ = ZoneInfo("America/New_York")
LITHUANIA_TZ = ZoneInfo("Europe/Vilnius")


# ======================================================
# TIME HELPERS
# ======================================================

def parse_time(c):
    return datetime.fromisoformat(c["time"]).astimezone(timezone.utc) if "T" in c["time"] or "+" in c["time"] else datetime.fromisoformat(c["time"]).replace(tzinfo=timezone.utc)


def to_ny(c):
    return parse_time(c).astimezone(NY_TZ)


def lithuania_time():
    return datetime.now(LITHUANIA_TZ).strftime("%Y-%m-%d %H:%M:%S")


def ny_time():
    return datetime.now(NY_TZ).strftime("%Y-%m-%d %H:%M:%S")


# ======================================================
# ATR / CANDLE QUALITY / VOLUME
# ======================================================

def atr(candles, period=14):
    if len(candles) < period + 1:
        return None

    trs = []
    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_close = candles[i - 1]["close"]
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))

    return round(sum(trs[-period:]) / period, 5)


def candle_quality(candle, side):
    body = abs(candle["close"] - candle["open"])
    full_range = candle["high"] - candle["low"]

    if full_range <= 0:
        return False, "Invalid candle"

    body_ratio = body / full_range
    upper_wick = candle["high"] - max(candle["open"], candle["close"])
    lower_wick = min(candle["open"], candle["close"]) - candle["low"]
    upper_ratio = upper_wick / full_range
    lower_ratio = lower_wick / full_range

    if body_ratio < 0.60:
        return False, f"Weak body {round(body_ratio * 100)}%"

    if side == "BUY" and upper_ratio > 0.30:
        return False, f"Upper wick too large {round(upper_ratio * 100)}%"

    if side == "SELL" and lower_ratio > 0.30:
        return False, f"Lower wick too large {round(lower_ratio * 100)}%"

    return True, f"Good displacement candle body {round(body_ratio * 100)}%"


def volume_spike(candles, lookback=30, multiplier=1.3):
    if len(candles) < lookback + 1:
        return False, 1.0

    previous = candles[-lookback - 1:-1]
    current = candles[-1]["volume"]
    avg = sum(c["volume"] for c in previous) / len(previous)

    if avg <= 0:
        return False, 1.0

    ratio = current / avg
    return ratio >= multiplier, round(ratio, 2)


# ======================================================
# FVG / IFVG (unchanged from v2)
# ======================================================

def detect_fvgs(candles, lookback=80):
    fvgs = []
    recent = candles[-lookback:]

    for i in range(2, len(recent)):
        c1 = recent[i - 2]
        c2 = recent[i - 1]
        c3 = recent[i]

        if c3["low"] > c1["high"]:
            fvgs.append({
                "type": "BULLISH",
                "low": round(c1["high"], 5),
                "high": round(c3["low"], 5),
                "mid": round((c1["high"] + c3["low"]) / 2, 5),
                "formed": c2["time"],
            })
        elif c3["high"] < c1["low"]:
            fvgs.append({
                "type": "BEARISH",
                "low": round(c3["high"], 5),
                "high": round(c1["low"], 5),
                "mid": round((c3["high"] + c1["low"]) / 2, 5),
                "formed": c2["time"],
            })

    return fvgs[-10:]


def detect_ifvgs(fvgs, current_close):
    ifvgs = []
    for f in fvgs:
        if f["type"] == "BULLISH" and current_close < f["low"]:
            ifvgs.append({"type": "BEARISH_IFVG", "low": f["low"], "high": f["high"], "mid": f["mid"]})
        if f["type"] == "BEARISH" and current_close > f["high"]:
            ifvgs.append({"type": "BULLISH_IFVG", "low": f["low"], "high": f["high"], "mid": f["mid"]})

    return ifvgs[-5:]


# ======================================================
# SESSIONS
# ======================================================

def current_session():
    h = datetime.now(NY_TZ).hour
    if 19 <= h or h < 2:
        return "ASIAN"
    if 2 <= h < 8:
        return "LONDON"
    if 8 <= h < 13:
        return "NEW_YORK"
    return "OFF-SESSION"


def execution_session_ok():
    return current_session() in ["LONDON", "NEW_YORK"]


def session_range(candles, name):
    windows = {"ASIAN": (19, 0), "LONDON": (2, 6), "NEW_YORK": (7, 11)}
    start_h, end_h = windows[name]
    selected = []

    for c in candles:
        t = to_ny(c)
        h = t.hour
        if name == "ASIAN":
            if h >= 19 or h < 1:
                selected.append(c)
        elif start_h <= h < end_h:
            selected.append(c)

    if not selected:
        return None

    return {
        "high": round(max(c["high"] for c in selected), 5),
        "low": round(min(c["low"] for c in selected), 5),
    }


def session_position(price, r):
    if not r:
        return "N/A"
    if price > r["high"]:
        return "ABOVE HIGH"
    if price < r["low"]:
        return "BELOW LOW"
    return "INSIDE RANGE"


# ======================================================
# NDOG / NWOG / TDO
# ======================================================

def ndog(candles, price, pip_radius):
    today = datetime.now(NY_TZ).date()
    today_c, previous = [], []

    for c in candles:
        t = to_ny(c)
        if t.date() == today:
            today_c.append(c)
        elif t.date() < today:
            previous.append(c)

    if not today_c or not previous:
        return None

    open_price = today_c[0]["open"]
    prev_close = previous[-1]["close"]
    low = round(min(open_price, prev_close), 5)
    high = round(max(open_price, prev_close), 5)
    gap = round(open_price - prev_close, 5)

    return {
        "direction": "UP" if gap > 0 else "DOWN",
        "low": low, "high": high, "gap": gap,
        "nearby": low - pip_radius <= price <= high + pip_radius,
    }


def nwog(candles, price, pip_radius):
    this_week = datetime.now(NY_TZ).isocalendar().week
    current, old = [], []

    for c in candles:
        t = to_ny(c)
        if t.isocalendar().week == this_week:
            current.append(c)
        else:
            old.append(c)

    if not current or not old:
        return None

    open_price = current[0]["open"]
    prev_close = old[-1]["close"]
    low = round(min(open_price, prev_close), 5)
    high = round(max(open_price, prev_close), 5)
    gap = round(open_price - prev_close, 5)

    return {
        "direction": "UP" if gap > 0 else "DOWN",
        "low": low, "high": high, "gap": gap,
        "nearby": low - pip_radius <= price <= high + pip_radius,
    }


def true_day_open_state(candles, price):
    ny_today = datetime.now(NY_TZ).date()
    today, previous = [], []

    for c in candles:
        t = to_ny(c)
        if t.date() == ny_today:
            today.append(c)
        elif t.date() < ny_today:
            previous.append(c)

    if not today:
        return None

    tdo_candle = today[0]
    tdo_open = round(tdo_candle["open"], 5)
    tdo_high = round(tdo_candle["high"], 5)
    tdo_low = round(tdo_candle["low"], 5)

    recent = today[-12:] if len(today) >= 12 else today
    swept_below = any(c["low"] < tdo_low for c in recent)
    swept_above = any(c["high"] > tdo_high for c in recent)

    last = today[-1]
    prev = today[-2] if len(today) >= 2 else today[-1]

    if prev["close"] < tdo_open and last["close"] > tdo_open:
        state = "BULLISH_RECLAIM"
    elif prev["close"] > tdo_open and last["close"] < tdo_open:
        state = "BEARISH_REJECTION"
    elif swept_below and price > tdo_open:
        state = "TDO_SWEEP_BULLISH"
    elif swept_above and price < tdo_open:
        state = "TDO_SWEEP_BEARISH"
    elif price > tdo_open:
        state = "ABOVE_TDO_BULLISH"
    elif price < tdo_open:
        state = "BELOW_TDO_BEARISH"
    else:
        state = "AT_TDO_NEUTRAL"

    return {"open": tdo_open, "high": tdo_high, "low": tdo_low, "state": state}