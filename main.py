"""
MAIN.PY - FOREX BOT V3 (Clean Final Version) + MCP
"""

import os
import time
import threading
from datetime import datetime, timezone
from flask import Flask

# Optional MT5
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None
    MT5_AVAILABLE = False

from config import PAIRS, SCAN_SECONDS, PAIR_DELAY_SECONDS, COOLDOWN_SECONDS, get_pair_config
from data_connector import get_candles, get_dxy_candles, get_current_price
from legacy_helpers import (
    detect_fvgs, detect_ifvgs, atr, candle_quality, volume_spike,
    execution_session_ok, current_session,
)
from signal_engine import build_signal_v3
from telegram_alerts import send_telegram, send_signal_v3

# ========== MCP ==========
from mcp.server.fastmcp import FastMCP
import httpx

mcp = FastMCP("Forex Bot", stateless_http=True, json_response=True)

@mcp.tool()
async def get_gold_price() -> dict:
    """Get current XAU/USD spot price"""
    async with httpx.AsyncClient() as client:
        r = await client.get("https://forex-bot-v3-gold.onrender.com/goldprice")
        return r.json()

@mcp.tool()
async def get_gold_data() -> dict:
    """Get full gold data (price + EMA + candles)"""
    async with httpx.AsyncClient() as client:
        r = await client.get("https://forex-bot-v3-gold.onrender.com/gold")
        return r.json()
# ========================

ENTRY_INTERVAL = "5min"
HTF_DAILY = "1day"
HTF_4H = "4h"
HTF_1H = "1h"

app = Flask(__name__)

_bot_status = {
    "started_at": datetime.now(timezone.utc).isoformat(),
    "last_scan_at": None,
    "last_scan_pair": None,
    "last_scan_result": None,
}

@app.route("/")
def health():
    return {
        "status": "alive",
        "bot": "forex-bot-v3",
        "started_at": _bot_status["started_at"],
        "last_scan_at": _bot_status["last_scan_at"],
        "last_scan_pair": _bot_status["last_scan_pair"],
        "last_scan_result": _bot_status["last_scan_result"],
    }

@app.route("/gold", methods=["GET"])
def gold_data():
    """Live XAU/USD data endpoint for Claude trading analysis"""
    import requests as req
    API_KEY = os.environ.get("TWELVE_DATA_API_KEY", "e5cd38de963a425bafe8d1af56dea121")
    try:
        price_resp = req.get(
            "https://api.twelvedata.com/price",
            params={"symbol": "XAU/USD", "apikey": API_KEY},
            timeout=10
        ).json()
        m5_resp = req.get(
            "https://api.twelvedata.com/time_series",
            params={"symbol": "XAU/USD", "interval": "5min", "outputsize": 20, "apikey": API_KEY},
            timeout=10
        ).json()
        m1_resp = req.get(
            "https://api.twelvedata.com/time_series",
            params={"symbol": "XAU/USD", "interval": "1min", "outputsize": 15, "apikey": API_KEY},
            timeout=10
        ).json()

        def calc_ema(values, period):
            if len(values) < period:
                return None
            k = 2 / (period + 1)
            ema = sum(values[:period]) / period
            for v in values[period:]:
                ema = v * k + ema * (1 - k)
            return round(ema, 2)

        m5_closes = [float(c["close"]) for c in m5_resp.get("values", [])]
        m5_closes_asc = list(reversed(m5_closes))
        ema9 = calc_ema(m5_closes_asc, 9)
        ema21 = calc_ema(m5_closes_asc, 21)
        current = float(price_resp.get("price", 0))
        trend = "BULLISH" if current > ema9 else "BEARISH" if ema9 else "UNKNOWN"

        candle_summary = []
        for c in m5_resp.get("values", [])[:5]:
            o, cl = float(c["open"]), float(c["close"])
            candle_summary.append({
                "time": c["datetime"],
                "open": o,
                "high": float(c["high"]),
                "low": float(c["low"]),
                "close": cl,
                "color": "GREEN" if cl > o else "RED",
                "body": round(abs(cl - o), 2)
            })

        return {
            "status": "ok",
            "symbol": "XAU/USD",
            "current_price": current,
            "ema9_m5": ema9,
            "ema21_m5": ema21,
            "trend": trend,
            "price_vs_ema9": "ABOVE" if current > (ema9 or 0) else "BELOW",
            "price_vs_ema21": "ABOVE" if current > (ema21 or 0) else "BELOW",
            "last_5_m5_candles": candle_summary,
            "m1_candles": m1_resp.get("values", [])[:10],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        import traceback
        return {"status": "error", "message": str(e), "trace": traceback.format_exc()}, 500

@app.route("/gbpusd", methods=["GET"])
def gbpusd_data():
    import requests as req
    API_KEY = os.environ.get("TWELVE_DATA_API_KEY", "e5cd38de963a425bafe8d1af56dea121")
    try:
        price_resp = req.get("https://api.twelvedata.com/price", params={"symbol": "GBP/USD", "apikey": API_KEY}, timeout=10).json()
        m5_resp = req.get("https://api.twelvedata.com/time_series", params={"symbol": "GBP/USD", "interval": "5min", "outputsize": 20, "apikey": API_KEY}, timeout=10).json()

        def calc_ema(values, period):
            if len(values) < period:
                return None
            k = 2 / (period + 1)
            ema = sum(values[:period]) / period
            for v in values[period:]:
                ema = v * k + ema * (1 - k)
            return round(ema, 6)

        m5_closes = [float(c["close"]) for c in m5_resp.get("values", [])]
        m5_closes_asc = list(reversed(m5_closes))
        ema9 = calc_ema(m5_closes_asc, 9)
        ema21 = calc_ema(m5_closes_asc, 21)
        current = float(price_resp.get("price", 0))

        candle_summary = []
        for c in m5_resp.get("values", [])[:5]:
            o, cl = float(c["open"]), float(c["close"])
            candle_summary.append({
                "time": c["datetime"], "open": o, "high": float(c["high"]),
                "low": float(c["low"]), "close": cl,
                "color": "GREEN" if cl > o else "RED", "body": round(abs(cl - o), 5)
            })

        return {
            "status": "ok", "symbol": "GBP/USD", "current_price": current,
            "ema9_m5": ema9, "ema21_m5": ema21,
            "trend": "BULLISH" if current > (ema9 or 0) else "BEARISH",
            "price_vs_ema9": "ABOVE" if current > (ema9 or 0) else "BELOW",
            "price_vs_ema21": "ABOVE" if current > (ema21 or 0) else "BELOW",
            "last_5_m5_candles": candle_summary,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500

@app.route("/btcusd", methods=["GET"])
def btcusd_data():
    import requests as req
    API_KEY = os.environ.get("TWELVE_DATA_API_KEY", "e5cd38de963a425bafe8d1af56dea121")
    try:
        price_resp = req.get("https://api.twelvedata.com/price", params={"symbol": "BTC/USD", "apikey": API_KEY}, timeout=10).json()
        m5_resp = req.get("https://api.twelvedata.com/time_series", params={"symbol": "BTC/USD", "interval": "5min", "outputsize": 20, "apikey": API_KEY}, timeout=10).json()
        m1_resp = req.get("https://api.twelvedata.com/time_series", params={"symbol": "BTC/USD", "interval": "1min", "outputsize": 15, "apikey": API_KEY}, timeout=10).json()

        def calc_ema(values, period):
            if len(values) < period:
                return None
            k = 2 / (period + 1)
            ema = sum(values[:period]) / period
            for v in values[period:]:
                ema = v * k + ema * (1 - k)
            return round(ema, 2)

        m5_closes = [float(c["close"]) for c in m5_resp.get("values", [])]
        m5_closes_asc = list(reversed(m5_closes))
        ema9 = calc_ema(m5_closes_asc, 9)
        ema21 = calc_ema(m5_closes_asc, 21)
        current = float(price_resp.get("price", 0))

        candle_summary = []
        for c in m5_resp.get("values", [])[:5]:
            o, cl = float(c["open"]), float(c["close"])
            candle_summary.append({
                "time": c["datetime"], "open": o, "high": float(c["high"]),
                "low": float(c["low"]), "close": cl,
                "color": "GREEN" if cl > o else "RED", "body": round(abs(cl - o), 2)
            })

        return {
            "status": "ok", "symbol": "BTC/USD", "current_price": current,
            "ema9_m5": ema9, "ema21_m5": ema21,
            "trend": "BULLISH" if current > (ema9 or 0) else "BEARISH",
            "price_vs_ema9": "ABOVE" if current > (ema9 or 0) else "BELOW",
            "price_vs_ema21": "ABOVE" if current > (ema21 or 0) else "BELOW",
            "last_5_m5_candles": candle_summary,
            "m1_candles": m1_resp.get("values", [])[:10],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500

@app.route("/ethusd", methods=["GET"])
def ethusd_data():
    import requests as req
    API_KEY = os.environ.get("TWELVE_DATA_API_KEY", "e5cd38de963a425bafe8d1af56dea121")
    try:
        price_resp = req.get("https://api.twelvedata.com/price", params={"symbol": "ETH/USD", "apikey": API_KEY}, timeout=10).json()
        m5_resp = req.get("https://api.twelvedata.com/time_series", params={"symbol": "ETH/USD", "interval": "5min", "outputsize": 20, "apikey": API_KEY}, timeout=10).json()
        m1_resp = req.get("https://api.twelvedata.com/time_series", params={"symbol": "ETH/USD", "interval": "1min", "outputsize": 15, "apikey": API_KEY}, timeout=10).json()

        def calc_ema(values, period):
            if len(values) < period:
                return None
            k = 2 / (period + 1)
            ema = sum(values[:period]) / period
            for v in values[period:]:
                ema = v * k + ema * (1 - k)
            return round(ema, 4)

        m5_closes = [float(c["close"]) for c in m5_resp.get("values", [])]
        m5_closes_asc = list(reversed(m5_closes))
        ema9 = calc_ema(m5_closes_asc, 9)
        ema21 = calc_ema(m5_closes_asc, 21)
        current = float(price_resp.get("price", 0))

        candle_summary = []
        for c in m5_resp.get("values", [])[:5]:
            o, cl = float(c["open"]), float(c["close"])
            candle_summary.append({
                "time": c["datetime"], "open": o, "high": float(c["high"]),
                "low": float(c["low"]), "close": cl,
                "color": "GREEN" if cl > o else "RED", "body": round(abs(cl - o), 4)
            })

        return {
            "status": "ok", "symbol": "ETH/USD", "current_price": current,
            "ema9_m5": ema9, "ema21_m5": ema21,
            "trend": "BULLISH" if current > (ema9 or 0) else "BEARISH",
            "price_vs_ema9": "ABOVE" if current > (ema9 or 0) else "BELOW",
            "price_vs_ema21": "ABOVE" if current > (ema21 or 0) else "BELOW",
            "last_5_m5_candles": candle_summary,
            "m1_candles": m1_resp.get("values", [])[:10],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500

_goldprice_cache = {"data": None, "fetched_at": 0}
GOLDPRICE_CACHE_TTL = 300

@app.route("/goldprice", methods=["GET"])
def goldprice():
    import requests as req
    import time
    now = time.time()
    cached = _goldprice_cache["data"]
    age = now - _goldprice_cache["fetched_at"]
    if cached and age < GOLDPRICE_CACHE_TTL:
        cached["cached"] = True
        cached["cache_age_seconds"] = int(age)
        return cached
    try:
        resp = req.get(
            "https://www.goldapi.io/api/XAU/USD",
            headers={
                "x-access-token": "goldapi-2b3ee317d47f336fa5b15d006845d474-io",
                "Content-Type": "application/json"
            },
            timeout=10
        ).json()
        result = {
            "status": "ok",
            "price": resp.get("price"),
            "open": resp.get("open_price"),
            "high": resp.get("high_price"),
            "low": resp.get("low_price"),
            "change": resp.get("ch"),
            "change_pct": resp.get("chp"),
            "timestamp": resp.get("timestamp"),
            "cached": False,
            "cache_age_seconds": 0,
            "source": "GoldAPI.io — real XAU/USD spot"
        }
        _goldprice_cache["data"] = result
        _goldprice_cache["fetched_at"] = now
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def run_pair_scan(pair):
    cfg = get_pair_config(pair)
    _bot_status["last_scan_at"] = datetime.now(timezone.utc).isoformat()
    _bot_status["last_scan_pair"] = pair
    try:
        if not execution_session_ok():
            msg = f"Outside London/New York execution window (session={current_session()})"
            print(f"{pair}: {msg}")
            _bot_status["last_scan_result"] = msg
            return None
        daily_c = get_candles(pair, HTF_DAILY, 60)
        h4_c = get_candles(pair, HTF_4H, 120)
        h1_c = get_candles(pair, HTF_1H, 160)
        entry_c = get_candles(pair, ENTRY_INTERVAL, 200)
        dxy_c, dxy_fallback = get_dxy_candles(HTF_1H, 120)
        if min(len(daily_c), len(h4_c), len(h1_c), len(entry_c)) < 50:
            msg = (f"Not enough HTF data (Daily={len(daily_c)} 4H={len(h4_c)} "
                   f"1H={len(h1_c)} Entry={len(entry_c)})")
            print(f"{pair}: {msg}")
            _bot_status["last_scan_result"] = msg
            return None
        if not entry_c:
            msg = "No entry timeframe data"
            print(f"{pair}: {msg}")
            _bot_status["last_scan_result"] = msg
            return None
        polygon_price_data = get_current_price(pair, ENTRY_INTERVAL)
        bot_price = polygon_price_data["price"] if polygon_price_data else entry_c[-1]["close"]
        print(f"\n{'='*70}")
        print(f"[PRICE RECONCILIATION] {pair}")
        print(f" Polygon (bot) latest close : {bot_price}")
        print(f" Entry candles last close : {entry_c[-1]['close']}")
        print(f" Discrepancy : {abs(bot_price - entry_c[-1]['close']):.5f}")
        print(f"{'='*70}\n")
        price = bot_price
        discrepancy = abs(bot_price - entry_c[-1]['close'])
        if pair == "XAU/USD" and discrepancy > 0.50:
            print(f"⚠️ LARGE PRICE DISCREPANCY on XAU/USD ({discrepancy:.2f})")
        elif discrepancy > 0.0005:
            print(f"⚠️ Price discrepancy detected on {pair} ({discrepancy:.5f})")
        fvgs = detect_fvgs(entry_c, 80)
        ifvgs = detect_ifvgs(fvgs, price)
        atr_value = atr(entry_c, 14) or 0.0010
        candle_quality_buy = candle_quality(entry_c[-1], "BUY")
        candle_quality_sell = candle_quality(entry_c[-1], "SELL")
        spike, vol_ratio = volume_spike(entry_c)
        print(f"{datetime.now()} | {pair} | Price={price} | DXY fallback={dxy_fallback}")
        signal = build_signal_v3(
            pair=pair, price=price,
            daily_candles=daily_c, h4_candles=h4_c, h1_candles=h1_c, entry_candles=entry_c,
            dxy_candles=dxy_c, fvgs=fvgs, ifvgs=ifvgs, atr_value=atr_value,
            candle_quality_buy=candle_quality_buy, candle_quality_sell=candle_quality_sell,
            volume_spike_result=(spike, vol_ratio), pair_config=cfg,
        )
        _bot_status["last_scan_result"] = (
            f"Signal: {signal['side']} @ {signal['entry']} ({signal['confidence']}%)"
            if signal else "No signal this cycle"
        )
        return signal
    except Exception as e:
        import traceback
        print(f"{pair}: ERROR: {str(e)}")
        print(traceback.format_exc())
        _bot_status["last_scan_result"] = f"ERROR: {str(e)}"
        return None

def get_broker_price(pair):
    if not MT5_AVAILABLE:
        print(f"[BROKER] MetaTrader5 not available for {pair}")
        return None
    if not mt5.initialize():
        print(f"[MT5] Failed to initialize for {pair}")
        return None
    symbol = pair.replace("/", "")
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        print(f"[MT5] Failed to get tick for {symbol}")
        mt5.shutdown()
        return None
    price = tick.bid
    print(f"[MT5] Broker price for {pair}: {price}")
    mt5.shutdown()
    return price

def confirm_broker_price_before_alert(signal):
    pair = signal["pair"]
    bot_entry = signal["entry"]
    broker_price = get_broker_price(pair)
    if broker_price is None:
        print(f"⚠️ Broker price unavailable for {pair} → Sending alert anyway")
        return True
    discrepancy = abs(bot_entry - broker_price)
    print(f"[BROKER CONFIRM] {pair} | Bot: {bot_entry} | Broker: {broker_price} | Diff: {discrepancy:.5f}")
    if pair == "XAU/USD" and discrepancy > 1.00 or discrepancy > 0.0010:
        print(f"❌ DISCREPANCY on {pair} → ALERT SKIPPED")
        return False
    return True

def run_bot_loop():
    try:
        send_telegram(
            "🤖 <b>Forex Bot V3 — ICT Confluence ONLINE</b>\n\n"
            "Engine:\n"
            "HTF Structure (BOS/MSS) → Liquidity Sweep → PD Array (OB/FVG) → DXY Correlation\n\n"
            f"Pairs: {', '.join(PAIRS)}\n"
            "Mode: Paper alerts only\n"
            f"Scan: Every {SCAN_SECONDS // 60} minutes"
        )
    except Exception as e:
        print(f"Startup Telegram message failed (non-fatal): {e}")
    last_signal_time = {}
    last_signal_side = {}
    while True:
        for pair in PAIRS:
            try:
                signal = run_pair_scan(pair)
                if signal:
                    now = time.time()
                    previous_time = last_signal_time.get(pair, 0)
                    previous_side = last_signal_side.get(pair)
                    cooldown_ok = now - previous_time >= COOLDOWN_SECONDS
                    side_changed = signal["side"] != previous_side
                    if cooldown_ok or side_changed:
                        if confirm_broker_price_before_alert(signal):
                            send_signal_v3(signal)
                            last_signal_time[pair] = now
                            last_signal_side[pair] = signal["side"]
                            print(f"{pair}: ✅ Signal SENT — {signal['side']} @ {signal['entry']}")
                        else:
                            print(f"{pair}: ❌ Signal SKIPPED (broker price mismatch)")
                    else:
                        print(f"{pair}: Signal skipped due to cooldown.")
                else:
                    print(f"{pair}: No signal this cycle.")
                time.sleep(PAIR_DELAY_SECONDS)
            except Exception as e:
                print(f"{pair}: Error: {e}")
        time.sleep(SCAN_SECONDS)

if __name__ == "__main__":
    # Start the trading bot loop in background
    bot_thread = threading.Thread(target=run_bot_loop, daemon=True)
    bot_thread.start()

    # Start MCP server (this is what Claude connects to)
    mcp.run(transport="streamable-http", host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
