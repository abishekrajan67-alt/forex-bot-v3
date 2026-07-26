"""
TELEGRAM ALERTS
"""
import os
import sys
import requests
from datetime import datetime, timezone

def log(msg):
    """Print to stderr to avoid closed stdout issues"""
    print(msg, file=sys.stderr, flush=True)

def send_telegram(message):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        log(f"TELEGRAM DEBUG: TOKEN={bool(token)} CHAT_ID={bool(chat_id)}")
        log("Missing Telegram credentials.")
        return False
    
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            log(f"Telegram error: {resp.status_code} {resp.text}")
            return False
        return True
    except Exception as e:
        log(f"Telegram send error: {e}")
        return False

def send_signal_v3(signal):
    pair = signal["pair"]
    side = signal["side"]
    entry = signal["entry"]
    sl = signal["stop_loss"]
    tp = signal["take_profit"]
    rr = signal["rr"]
    conf = signal["confidence"]
    reasons = signal.get("reasons", [])
    warnings = signal.get("warnings", [])
    
    msg = f"""<b>🚨 FOREX BOT V3 SIGNAL</b>
<b>{pair}</b> - <b>{side}</b>
Entry: {entry}
Stop Loss: {sl}
Take Profit: {tp}
R:R: {rr}
Confidence: {conf}%

<b>Reasons:</b>
{chr(10).join(f'• {r}' for r in reasons[:5])}

<b>Warnings:</b>
{chr(10).join(f'• {w}' for w in warnings[:3]) if warnings else 'None'}

<b>Timestamp:</b> {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
"""
    return send_telegram(msg)
