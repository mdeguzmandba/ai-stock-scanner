#!/usr/bin/env python3
"""
scanner.py — AI Pre-Market Stock Scanner Orchestrator
Usage: python3 scanner/scanner.py [--mode normal|aggressive|conservative]

Flow:
  1. Get pre-market movers from Finviz
  2. Enrich with yfinance (VWAP, EMA9, avg vol)
  3. Score each with SMB 5-step framework
  4. Filter to tradeable (score ≥ threshold)
  5. Size positions
  6. Save to today-picks.json
  7. Send Telegram alert
"""

import json
import sys
import os
import argparse
import shutil
from datetime import datetime, date

# Allow running as `python3 scanner/scanner.py` from repo root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from finviz import get_premarket_movers
from yf_data import enrich_movers
from scorer import score_stock, filter_tradeable
from positions import size_all_positions, MAX_POSITIONS, DEFAULT_RR
from telegram import send_picks

OUTPUT_PATH = "/Users/claudeco/Documents/MarcBrain/paper-trading/today-picks.json"
HISTORY_DIR = "/Users/claudeco/Documents/MarcBrain/paper-trading/history"
ACCOUNT_BALANCE = 2226.38  # update this manually or link to tracker


def parse_args():
    parser = argparse.ArgumentParser(description="AI Pre-Market Stock Scanner")
    parser.add_argument(
        "--mode",
        choices=["normal", "aggressive", "conservative"],
        default="normal",
        help="Scoring threshold mode (default: normal ≥15)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Score and print but don't send Telegram or save JSON",
    )
    parser.add_argument(
        "--no-telegram",
        action="store_true",
        help="Skip Telegram notification",
    )
    return parser.parse_args()


def build_output(
    trades: list[dict],
    candidates_screened: int,
    mode: str,
) -> dict:
    """Build the final JSON output structure."""
    now_pt = datetime.now()  # server is in PT per setup
    return {
        "date": date.today().isoformat(),
        "generated_at": now_pt.strftime("%I:%M %p PT"),
        "mode": mode,
        "balance_start": ACCOUNT_BALANCE,
        "candidates_screened": candidates_screened,
        "trades_found": len(trades),
        "trades": [
            {
                "rank": i + 1,
                "ticker": t.get("ticker"),
                "company": t.get("company", ""),
                "catalyst": t.get("catalyst", ""),
                "price_premarket": t.get("price_premarket"),
                "gap_pct": t.get("gap_pct"),
                "volume_premarket": t.get("volume_premarket", t.get("volume_today", 0)),
                "avg_volume": t.get("avg_volume", 0),
                "volume_ratio": t.get("volume_ratio", 0),
                "vwap": t.get("vwap"),
                "ema9": t.get("ema9"),
                "above_vwap": t.get("above_vwap", False),
                "smb_score": t.get("smb_score"),
                "score_breakdown": t.get("score_breakdown", {}),
                "entry": t.get("entry"),
                "stop": t.get("stop"),
                "target": t.get("target"),
                "risk_per_share": t.get("risk_per_share"),
                "rr": t.get("rr"),
                "shares": t.get("shares"),
                "capital": t.get("capital"),
                "max_loss": t.get("max_loss"),
                "entry_note": t.get("entry_note", ""),
            }
            for i, t in enumerate(trades)
        ],
    }


def save_output(output: dict, path: str, history_dir: str):
    """Save to today-picks.json and archive to history/."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    os.makedirs(history_dir, exist_ok=True)

    with open(path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"[scanner] Saved → {path}")

    # Archive copy
    history_path = os.path.join(history_dir, f"picks-{output['date']}.json")
    shutil.copy2(path, history_path)
    print(f"[scanner] Archived → {history_path}")


def main():
    args = parse_args()
    mode = args.mode

    print(f"\n{'='*60}")
    print(f"  AI Pre-Market Scanner | {date.today()} | mode={mode}")
    print(f"{'='*60}\n")

    # ── Step 1: Get Finviz movers ──────────────────────────────
    print("[1/5] Fetching Finviz pre-market movers...")
    raw_movers = get_premarket_movers(max_results=50)
    print(f"      → {len(raw_movers)} raw candidates\n")

    if not raw_movers:
        print("⚠️  No movers from Finviz. Markets may not be open yet or rate-limited.")
        print("    Exiting without sending Telegram.\n")
        return

    # ── Step 2: Enrich with yfinance ──────────────────────────
    print("[2/5] Enriching with yfinance (VWAP, EMA9, volume)...")
    enriched = enrich_movers(raw_movers)
    candidates_screened = len(raw_movers)
    print(f"\n      → {len(enriched)} passed hard filters\n")

    # ── Step 3: Score each stock ───────────────────────────────
    print("[3/5] Scoring with SMB 5-step framework...")
    scored = []
    for stock in enriched:
        stock = score_stock(stock)
        scored.append(stock)
        bd = stock.get("score_breakdown", {})
        print(
            f"      {stock['ticker']:6s} SMB={stock['smb_score']:2d}/25 "
            f"[cat={bd.get('catalyst',0)} vwap={bd.get('vwap',0)} "
            f"ema9={bd.get('ema9',0)} vol={bd.get('volume',0)} gap={bd.get('gap',0)}]"
        )
    print()

    # ── Step 4: Filter tradeable ───────────────────────────────
    print(f"[4/5] Filtering (mode={mode})...")
    tradeable = filter_tradeable(scored, mode=mode)
    print(f"      → {len(tradeable)} tradeable stocks\n")

    # ── Step 5: Size positions ─────────────────────────────────
    print("[5/5] Sizing positions...")
    rr_map = {"normal": 2.0, "aggressive": 1.5, "conservative": 2.5}
    rr = rr_map.get(mode, 2.0)
    sized = size_all_positions(tradeable, max_positions=MAX_POSITIONS, rr=rr)
    for s in sized:
        print(
            f"      {s['ticker']:6s} entry=${s.get('entry',0):.2f} "
            f"stop=${s.get('stop',0):.2f} target=${s.get('target',0):.2f} "
            f"shares={s.get('shares',0)} capital=${s.get('capital',0):.0f}"
        )
    print()

    # ── Build output ───────────────────────────────────────────
    output = build_output(sized, candidates_screened, mode)

    if args.dry_run:
        print("[dry-run] Output preview:")
        print(json.dumps(output, indent=2))
        return

    # ── Save JSON ──────────────────────────────────────────────
    save_output(output, OUTPUT_PATH, HISTORY_DIR)

    # ── Send Telegram ──────────────────────────────────────────
    if not args.no_telegram:
        send_picks(output)

    print(f"\n✅ Scanner complete. {len(sized)} trade(s) found.\n")


if __name__ == "__main__":
    main()
