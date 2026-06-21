"""
TELEGRAM ALERTS V3
========================
Sends formatted signal alerts. Updated to show the NEW confluence
factors (structure events, liquidity sweeps, PD array type including
Order Blocks, DXY correlation) so you can see WHY each signal fired,
not just that it fired.
"""

import os
import requests
from dotenv import load_dotenv
from legacy_helpers import lithuania_time, ny_time, current_session

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Missing Telegram credentials.")
        return

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        r = requests.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"},
            timeout=10,
        )
        if not r.ok:
            print("Telegram error:", r.text)
    except Exception as e:
        print("Telegram exception:", e)


def send_signal_v3(s):
    emoji = "🟢" if s["side"] == "BUY" else "🔴"

    reasons = "\n".join([f"✅ {r}" for r in s["reasons"]])
    warnings = "\n".join([f"⚠️ {w}" for w in s["warnings"]]) or "None"

    sweep = s["sweep"]
    sweep_line = (
        f"{sweep['swing_type']} swept @ {sweep['swing_price']} "
        f"(wick {sweep['sweep_extreme']}) -> {sweep['direction']}"
    )

    message = f"""
{emoji} <b>{s['pair']} {s['side']} — ICT CONFLUENCE ENTRY</b>

<b>Entry:</b> {s['entry']}
<b>Stop Loss:</b> {s['stop_loss']}
<b>Take Profit:</b> {s['take_profit']}
<b>Risk:Reward:</b> {s['rr']}x
<b>Confidence:</b> {s['confidence']}%

<b>Time:</b>
Lithuania: {lithuania_time()}
New York: {ny_time()}
Session: {current_session()}

<b>HTF Structure (need 2/3 minimum):</b>
Daily: {s['daily_structure']['trend']} (last: {s['daily_structure']['last_event_type']})
4H: {s['h4_structure']['trend']} (last: {s['h4_structure']['last_event_type']})
1H: {s['h1_structure']['trend']} (last: {s['h1_structure']['last_event_type']})
Aligned: {s['htf_aligned_count']}/3

<b>Entry TF Structure:</b>
Trend: {s['entry_structure']['trend']}
Last Event: {s['entry_structure']['last_event_type']} ({s['entry_structure']['last_event_direction']})

<b>Liquidity Sweep:</b>
{sweep_line}

<b>PD Array:</b>
Type: {s['pd_type']}
Zone: {s['pd_array']['low']} - {s['pd_array']['high']}

<b>DXY Correlation:</b>
Trend: {s['dxy_structure']['trend']}

<b>Volume Ratio:</b> {s['volume_ratio']}x

<b>Confluence Factors:</b>
{reasons}

<b>Warnings:</b>
{warnings}

<b>Mode:</b> Paper Alert Only
"""

    send_telegram(message)
