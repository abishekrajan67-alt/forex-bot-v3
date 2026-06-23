"""
TELEGRAM ALERTS V3 - Attractive Version
"""
import os
import requests
from dotenv import load_dotenv
from legacy_helpers import lithuania_time, ny_time, current_session

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

print("TELEGRAM DEBUG: TOKEN=", bool(TELEGRAM_TOKEN), "CHAT_ID=", bool(TELEGRAM_CHAT_ID))

def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Missing Telegram credentials.")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=10)
        print("Telegram sent" if r.ok else f"Telegram error: {r.text}")
    except Exception as e:
        print("Telegram exception:", e)

def send_signal_v3(s):
    emoji = "🟢" if s["side"] == "BUY" else "🔴"
    reasons = "\n".join([f"✅ {r}" for r in s.get("reasons", [])])
    warnings = "\n".join([f"⚠️ {w}" for w in s.get("warnings", [])]) or "None"

    message = f"""
{emoji} <b>{s['pair']} {s['side']} SIGNAL</b>

📍 <b>Entry:</b> <code>{s['entry']}</code>
🛑 <b>SL:</b> <code>{s['stop_loss']}</code>
🎯 <b>TP:</b> <code>{s['take_profit']}</code>
📊 <b>RR:</b> {s['rr']}x | Confidence: <b>{s['confidence']}%</b>

🕒 <b>Time:</b> {lithuania_time()} (LT) | {ny_time()} (NY)
Session: {current_session()}

<b>HTF Structure:</b> {s['htf_aligned_count']}/3 aligned
<b>PD Array:</b> {s['pd_type']} @ {s['pd_array']['low']}-{s['pd_array']['high']}

{reasons}

⚠️ <b>Warnings:</b>
{warnings}
"""
    send_telegram(message)
