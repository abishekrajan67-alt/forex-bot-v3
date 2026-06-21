"""
MAIN.PY - FOREX BOT V3
========================
Full pipeline per scan cycle, per pair:

1. Fetch Daily / 4H / 1H / Entry(5m) candles + DXY candles (Polygon)
2. Compute FVG/IFVG, ATR, candle quality, volume spike (legacy_helpers)
3. Run build_signal_v3() - the new confluence engine (Stages 1-6)
4. If a signal fires and cooldown allows -> send Telegram alert

Run: python3 main.py
"""

import time
from datetime import datetime

from config import PAIRS, SCAN_SECONDS, PAIR_DELAY_SECONDS, COOLDOWN_SECONDS, get_pair_config
from data_connector import get_candles, get_dxy_candles
from legacy_helpers import (
    detect_fvgs, detect_ifvgs, atr, candle_quality, volume_spike,
    execution_session_ok, current_session,
)
from signal_engine import build_signal_v3
from telegram_alerts import send_telegram, send_signal_v3


# Entry timeframe per pair (5-minute charts for both, matching v2)
ENTRY_INTERVAL = "5min"
HTF_DAILY = "1day"
HTF_4H = "4h"
HTF_1H = "1h"


def run_pair_scan(pair):
    """
    Runs one full scan cycle for a single pair. Returns a signal dict
    or None.
    """
    cfg = get_pair_config(pair)

    daily_c = get_candles(pair, HTF_DAILY, 60)
    h4_c = get_candles(pair, HTF_4H, 120)
    h1_c = get_candles(pair, HTF_1H, 160)
    entry_c = get_candles(pair, ENTRY_INTERVAL, 200)
    dxy_c, dxy_fallback = get_dxy_candles(HTF_1H, 120)

    if min(len(daily_c), len(h4_c), len(h1_c), len(entry_c)) < 50:
        print(f"{pair}: Not enough HTF data (Daily={len(daily_c)} 4H={len(h4_c)} "
              f"1H={len(h1_c)} Entry={len(entry_c)}).")
        return None

    if not entry_c:
        print(f"{pair}: No entry timeframe data.")
        return None

    price = entry_c[-1]["close"]

    if not execution_session_ok():
        print(f"{pair}: Outside London/New York execution window. Session={current_session()}")
        return None

    # FVG/IFVG (reused from v2)
    fvgs = detect_fvgs(entry_c, 80)
    ifvgs = detect_ifvgs(fvgs, price)

    # ATR / candle quality / volume (reused from v2)
    atr_value = atr(entry_c, 14) or 0.0010
    candle_quality_buy = candle_quality(entry_c[-1], "BUY")
    candle_quality_sell = candle_quality(entry_c[-1], "SELL")
    spike, vol_ratio = volume_spike(entry_c)

    print(
        f"{datetime.now()} | {pair} | Price={price} | "
        f"DXY fallback={dxy_fallback} | Session={current_session()}"
    )

    signal = build_signal_v3(
        pair=pair,
        price=price,
        daily_candles=daily_c,
        h4_candles=h4_c,
        h1_candles=h1_c,
        entry_candles=entry_c,
        dxy_candles=dxy_c,
        fvgs=fvgs,
        ifvgs=ifvgs,
        atr_value=atr_value,
        candle_quality_buy=candle_quality_buy,
        candle_quality_sell=candle_quality_sell,
        volume_spike_result=(spike, vol_ratio),
        pair_config=cfg,
    )

    return signal


def main():
    send_telegram(
        "🤖 <b>Forex Bot V3 — ICT Confluence ONLINE</b>\n\n"
        "Engine:\n"
        "HTF Structure (BOS/MSS) → Liquidity Sweep → PD Array (OB/FVG) → DXY Correlation\n\n"
        f"Pairs: {', '.join(PAIRS)}\n"
        "Mode: Paper alerts only\n"
        f"Scan: Every {SCAN_SECONDS // 60} minutes"
    )

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
                        send_signal_v3(signal)
                        last_signal_time[pair] = now
                        last_signal_side[pair] = signal["side"]
                        print(f"{pair}: Signal sent — {signal['side']} @ {signal['entry']} "
                              f"(confidence {signal['confidence']}%)")
                    else:
                        print(f"{pair}: Signal skipped due to cooldown.")
                else:
                    print(f"{pair}: No signal this cycle.")

                time.sleep(PAIR_DELAY_SECONDS)

            except Exception as e:
                print(f"{pair}: Error: {e}")

        time.sleep(SCAN_SECONDS)


if __name__ == "__main__":
    main()
