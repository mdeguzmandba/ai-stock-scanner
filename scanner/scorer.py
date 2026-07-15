"""
scorer.py — SMB 5-step scoring framework
Max score: 25. Need ≥15 to trade (or ≥13 aggressive / ≥18 conservative).
"""

import requests
from concurrent.futures import ThreadPoolExecutor
from datetime import date

THRESHOLDS = {
    "normal": 15,
    "aggressive": 13,
    "conservative": 18,
}
MAX_CATALYST_SCORE = 5
MAX_WORKERS = 8  # concurrent catalyst lookups


# ── Catalyst detection ──────────────────────────────────────────────────────

def _check_catalyst(ticker: str) -> tuple[int, str]:
    """
    Quick catalyst check via StockAnalysis news headline scrape.
    Returns (score 0-5, catalyst description string).
    """
    today_str = date.today().isoformat()

    # Try StockAnalysis
    try:
        url = f"https://stockanalysis.com/stocks/{ticker.lower()}/"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
            )
        }
        resp = requests.get(url, headers=headers, timeout=8)
        text = resp.text.lower()

        # High-conviction catalysts
        strong_keywords = [
            "fda approved", "fda approval", "fda granted", "acquired", "acquisition",
            "merger", "earnings beat", "raised guidance", "beat estimates",
            "patent granted", "clinical trial results", "phase 3", "breakthrough",
        ]
        moderate_keywords = [
            "earnings", "revenue", "quarterly results", "analyst upgrade",
            "price target raised", "collaboration", "contract", "agreement",
        ]

        for kw in strong_keywords:
            if kw in text:
                return 5, f"Strong catalyst: {kw.title()} detected"

        for kw in moderate_keywords:
            if kw in text:
                return 3, f"Moderate catalyst: {kw.title()} detected"

    except Exception:
        pass

    return 1, "No catalyst confirmed (gap on volume)"


# ── Individual scoring functions ────────────────────────────────────────────

def score_catalyst(ticker: str, gap_pct: float) -> tuple[int, str]:
    """Step 1 — Stock In Play (0-5)"""
    catalyst_score, catalyst_desc = _check_catalyst(ticker)
    # Boost if gap is also huge
    if gap_pct >= 10 and catalyst_score >= 5:
        return 5, catalyst_desc
    elif gap_pct >= 5 and catalyst_score >= 3:
        return min(catalyst_score, 4), catalyst_desc
    else:
        return catalyst_score, catalyst_desc


def score_vwap(price: float, vwap: float) -> int:
    """Step 2 — VWAP Position (0-5)"""
    if vwap <= 0:
        return 2  # unknown — neutral
    diff_pct = (price - vwap) / vwap * 100
    if diff_pct > 1.0:
        return 5
    elif diff_pct > -0.5:
        return 3
    else:
        return 0


def score_ema9(price: float, ema9: float) -> int:
    """Step 3 — Key Level (using EMA9 as dynamic support) (0-5)"""
    if ema9 <= 0:
        return 2  # unknown — neutral
    diff_pct = (price - ema9) / ema9 * 100
    if diff_pct > 1.0:
        return 5
    elif diff_pct > -1.0:
        return 3
    else:
        return 1


def score_volume(volume_ratio: float) -> int:
    """Step 4 — Volume (0-5)"""
    if volume_ratio >= 2.0:
        return 5
    elif volume_ratio >= 1.5:
        return 3
    elif volume_ratio >= 1.0:
        return 1
    else:
        return 0


def score_gap(gap_pct: float) -> int:
    """Step 5 — Gap % as proxy for R:R potential (0-5)"""
    if gap_pct >= 15:
        return 5
    elif gap_pct >= 10:
        return 4
    elif gap_pct >= 7:
        return 3
    elif gap_pct >= 5:
        return 2
    else:
        return 0


# ── Main scoring functions ──────────────────────────────────────────────────

def _score_base(stock: dict) -> dict:
    """Compute the 4 local (no-network) scores: vwap, ema9, volume, gap."""
    price = stock.get("price_premarket", 0.0)
    return {
        "vwap": score_vwap(price, stock.get("vwap", 0.0)),
        "ema9": score_ema9(price, stock.get("ema9", 0.0)),
        "volume": score_volume(stock.get("volume_ratio", 0.0)),
        "gap": score_gap(stock.get("gap_pct", 0.0)),
    }


def _finalize(stock: dict, base: dict, cat_score: int, catalyst_desc: str) -> dict:
    stock["catalyst"] = catalyst_desc
    stock["smb_score"] = cat_score + sum(base.values())
    stock["score_breakdown"] = {"catalyst": cat_score, **base}
    return stock


def score_stock(stock: dict) -> dict:
    """
    Run all 5 SMB scoring steps on a stock dict.
    Adds 'smb_score', 'score_breakdown', 'catalyst' keys.
    Returns updated stock dict.
    """
    base = _score_base(stock)
    cat_score, catalyst_desc = score_catalyst(
        stock.get("ticker", ""), stock.get("gap_pct", 0.0)
    )
    return _finalize(stock, base, cat_score, catalyst_desc)


def score_stocks(
    stocks: list[dict],
    mode: str = "normal",
    max_workers: int = MAX_WORKERS,
) -> list[dict]:
    """
    Score a batch of stocks. The 4 local scores are computed first; the
    catalyst lookup (an HTTP request per ticker) only runs for stocks that
    could still reach the mode's threshold with a perfect catalyst score,
    and those lookups run concurrently.
    """
    min_score = THRESHOLDS.get(mode, 15)

    needs_catalyst = []
    for stock in stocks:
        base = _score_base(stock)
        if sum(base.values()) + MAX_CATALYST_SCORE < min_score:
            # Can't reach threshold even with a perfect catalyst — skip the lookup
            _finalize(stock, base, 1, "No catalyst confirmed (gap on volume)")
        else:
            needs_catalyst.append((stock, base))

    if needs_catalyst:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            cat_results = list(pool.map(
                lambda sb: score_catalyst(
                    sb[0].get("ticker", ""), sb[0].get("gap_pct", 0.0)
                ),
                needs_catalyst,
            ))
        for (stock, base), (cat_score, desc) in zip(needs_catalyst, cat_results):
            _finalize(stock, base, cat_score, desc)

    return stocks


def filter_tradeable(
    stocks: list[dict],
    mode: str = "normal"
) -> list[dict]:
    """
    Filter stocks by minimum SMB score based on mode.
    Modes: 'normal' (≥15), 'aggressive' (≥13), 'conservative' (≥18)
    """
    min_score = THRESHOLDS.get(mode, 15)
    tradeable = [s for s in stocks if s.get("smb_score", 0) >= min_score]
    return sorted(tradeable, key=lambda x: x["smb_score"], reverse=True)


if __name__ == "__main__":
    test = {
        "ticker": "AAPL",
        "price_premarket": 12.50,
        "vwap": 12.20,
        "ema9": 12.00,
        "gap_pct": 8.5,
        "volume_ratio": 2.1,
    }
    result = score_stock(test)
    print(f"SMB Score: {result['smb_score']}/25")
    print(f"Breakdown: {result['score_breakdown']}")
    print(f"Catalyst: {result['catalyst']}")
