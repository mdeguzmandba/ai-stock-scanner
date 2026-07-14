"""
yf_data.py — Pull OHLCV from yfinance, compute VWAP and EMA9
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, date
import warnings

warnings.filterwarnings("ignore")


def get_stock_data(ticker: str) -> dict:
    """
    Fetch intraday + daily data for a ticker.
    Returns enriched dict with vwap, ema9, avg_volume, volume_ratio, above_vwap.
    """
    result = {
        "ticker": ticker,
        "vwap": 0.0,
        "ema9": 0.0,
        "avg_volume": 0,
        "volume_ratio": 0.0,
        "above_vwap": False,
        "price": 0.0,
        "prev_close": 0.0,
        "gap_pct": 0.0,
        "volume_today": 0,
        "error": None,
    }

    try:
        tk = yf.Ticker(ticker)

        # --- Daily history for avg volume and prev close ---
        hist = tk.history(period="30d", interval="1d", auto_adjust=True)
        if hist.empty:
            result["error"] = "no daily history"
            return result

        # Average daily volume (last 20 days excluding today)
        avg_vol = int(hist["Volume"].iloc[:-1].tail(20).mean()) if len(hist) > 1 else 0
        result["avg_volume"] = avg_vol
        result["prev_close"] = round(float(hist["Close"].iloc[-2]), 4) if len(hist) >= 2 else 0.0

        # --- Intraday data for VWAP ---
        intra = tk.history(period="1d", interval="5m", auto_adjust=True)
        if not intra.empty:
            intra = intra.copy()
            # VWAP = cumulative(price * volume) / cumulative(volume)
            intra["TP"] = (intra["High"] + intra["Low"] + intra["Close"]) / 3
            intra["TPxV"] = intra["TP"] * intra["Volume"]
            cum_vol = intra["Volume"].cumsum()
            cum_tpv = intra["TPxV"].cumsum()
            intra["VWAP"] = cum_tpv / cum_vol.replace(0, pd.NA)
            vwap = float(intra["VWAP"].dropna().iloc[-1]) if not intra["VWAP"].dropna().empty else 0.0
            current_price = float(intra["Close"].iloc[-1])
            volume_today = int(intra["Volume"].sum())

            # EMA9 on 5-min closes
            if len(intra) >= 9:
                ema9 = float(intra["Close"].ewm(span=9, adjust=False).mean().iloc[-1])
            else:
                ema9 = float(intra["Close"].mean()) if not intra.empty else 0.0

            result["vwap"] = round(vwap, 4)
            result["ema9"] = round(ema9, 4)
            result["price"] = round(current_price, 4)
            result["above_vwap"] = current_price > vwap if vwap > 0 else False
            result["volume_today"] = volume_today
            result["volume_ratio"] = round(volume_today / avg_vol, 2) if avg_vol > 0 else 0.0

            if result["prev_close"] > 0:
                result["gap_pct"] = round(
                    (current_price - result["prev_close"]) / result["prev_close"] * 100, 2
                )
        else:
            # Market not yet open — use fast_info for pre-market price
            info = tk.fast_info
            pm_price = getattr(info, "last_price", 0) or 0
            result["price"] = round(float(pm_price), 4) if pm_price else 0.0
            if result["prev_close"] > 0 and result["price"] > 0:
                result["gap_pct"] = round(
                    (result["price"] - result["prev_close"]) / result["prev_close"] * 100, 2
                )

    except Exception as e:
        result["error"] = str(e)

    return result


def enrich_movers(movers: list[dict]) -> list[dict]:
    """
    Take list of movers from finviz, enrich each with yfinance data.
    Filters out stocks that fail hard criteria.
    """
    enriched = []
    for stock in movers:
        ticker = stock["ticker"]
        print(f"[yf] Fetching {ticker}...", end=" ", flush=True)
        data = get_stock_data(ticker)

        if data["error"]:
            print(f"skip ({data['error']})")
            continue

        # Merge yf data into stock dict
        stock["vwap"] = data["vwap"]
        stock["ema9"] = data["ema9"]
        stock["above_vwap"] = data["above_vwap"]
        stock["volume_today"] = data["volume_today"]
        stock["volume_ratio"] = data["volume_ratio"]

        # Prefer yfinance avg_volume if finviz didn't have it
        if data["avg_volume"] > 0:
            stock["avg_volume"] = data["avg_volume"]

        # Update price and gap if yfinance has better data
        if data["price"] > 0:
            stock["price_premarket"] = data["price"]
        if data["gap_pct"] != 0:
            stock["gap_pct"] = data["gap_pct"]

        # Hard filters per spec
        avg_vol = stock.get("avg_volume", 0)
        pm_vol = stock.get("volume_premarket", 0) or stock.get("volume_today", 0)
        price = stock.get("price_premarket", 0)
        gap = stock.get("gap_pct", 0)

        if price <= 0 or price >= 20:
            print(f"skip (price ${price})")
            continue
        if avg_vol < 300_000:
            print(f"skip (avg_vol {avg_vol:,})")
            continue
        if pm_vol < 50_000:
            print(f"skip (pm_vol {pm_vol:,})")
            continue
        if gap < 5.0:
            print(f"skip (gap {gap}%)")
            continue

        print(f"✓ gap={gap}% vol_ratio={stock['volume_ratio']}x")
        enriched.append(stock)

    return enriched


if __name__ == "__main__":
    test = get_stock_data("AAPL")
    print(test)
