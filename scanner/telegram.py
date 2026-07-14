"""
telegram.py — Send scanner picks to Marc's Telegram chat
Credentials pulled from bebot_mcp_server.py constants.
"""

import urllib.request
import urllib.parse
import json

TELEGRAM_TOKEN = "8667299658:AAG6VcDT3_MDTNpn7Knga4coXENo_bquYJA"
TELEGRAM_CHAT_ID = "8700829988"

RANK_EMOJIS = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]


def send_telegram(text: str) -> bool:
    """Send a plain text message via Telegram Bot API. Returns True on success."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
            return result.get("ok", False)
    except Exception as e:
        print(f"[telegram] Send failed: {e}")
        return False


def format_picks_message(output: dict) -> str:
    """Format the scanner output JSON into a Telegram message."""
    date_str = output.get("date", "")
    n_screened = output.get("candidates_screened", 0)
    trades = output.get("trades", [])

    lines = [
        f"🔍 <b>SCANNER — {date_str}</b> | {n_screened} candidates screened",
        "",
    ]

    if not trades:
        lines.append("⚠️ No qualifying trades today (min SMB score not met)")
        lines.append("")
        lines.append("⏰ Enter after 9:35 AM ET — confirm VWAP first")
        return "\n".join(lines)

    for i, trade in enumerate(trades):
        emoji = RANK_EMOJIS[i] if i < len(RANK_EMOJIS) else f"{i+1}."
        ticker = trade.get("ticker", "?")
        smb = trade.get("smb_score", 0)
        catalyst = trade.get("catalyst", "N/A")
        entry = trade.get("entry", 0)
        stop = trade.get("stop", 0)
        target = trade.get("target", 0)
        shares = trade.get("shares", 0)
        max_loss = trade.get("max_loss", 0)
        rr = trade.get("rr", 0)
        gap = trade.get("gap_pct", 0)
        vol_ratio = trade.get("volume_ratio", 0)
        vwap_status = "above ✅" if trade.get("above_vwap") else "below ⚠️"

        lines += [
            f"{emoji} <b>TRADE {i+1}: ${ticker}</b> — SMB {smb}/25",
            f"Catalyst: {catalyst}",
            f"Entry: ${entry:.2f} | Stop: ${stop:.2f} | Target: ${target:.2f}",
            f"Shares: {shares} | Risk: ${max_loss:.0f} | R:R: {rr:.1f}:1",
            f"Gap: +{gap:.1f}% | Vol: {vol_ratio:.1f}x avg | VWAP: {vwap_status}",
            "",
        ]

    lines.append("⏰ Enter after 9:35 AM ET — confirm VWAP first")
    return "\n".join(lines)


def send_picks(output: dict) -> bool:
    """Format and send scanner picks to Telegram. Returns True on success."""
    message = format_picks_message(output)
    print("[telegram] Sending picks...")
    print(message)
    success = send_telegram(message)
    if success:
        print("[telegram] ✓ Message sent")
    else:
        print("[telegram] ✗ Message failed")
    return success


if __name__ == "__main__":
    # Test with a dummy pick
    test_output = {
        "date": "2026-07-14",
        "candidates_screened": 12,
        "trades": [
            {
                "ticker": "TEST",
                "smb_score": 19,
                "catalyst": "FDA approval detected",
                "entry": 8.50,
                "stop": 8.25,
                "target": 9.00,
                "shares": 100,
                "max_loss": 25,
                "rr": 2.0,
                "gap_pct": 12.5,
                "volume_ratio": 3.2,
                "above_vwap": True,
            }
        ],
    }
    send_picks(test_output)
