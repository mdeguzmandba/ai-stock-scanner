"""
finviz.py — Scrape Finviz pre-market movers under $20
Returns list of dicts: {ticker, company, price, gap_pct, volume, avg_volume}
"""

import requests
from bs4 import BeautifulSoup
import re

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

FINVIZ_URL = (
    "https://finviz.com/screener.ashx"
    "?v=111"
    "&f=cap_micro,geo_usa,sh_price_u20,sh_avgvol_o200"
    "&o=-premagapperc"
    "&r=1"
)

ETF_KEYWORDS = ["ETF", "Trust", "Fund", "ProShares", "Direxion", "iShares", "Vanguard"]


def _parse_float(s: str) -> float:
    """Strip %, $, commas and return float. Returns 0.0 on failure."""
    try:
        return float(re.sub(r"[%$,]", "", s.strip()))
    except (ValueError, AttributeError):
        return 0.0


def _is_etf(company: str) -> bool:
    return any(kw.lower() in company.lower() for kw in ETF_KEYWORDS)


def get_premarket_movers(max_results: int = 50) -> list[dict]:
    """
    Fetch Finviz screener and return filtered pre-market movers.
    """
    try:
        resp = requests.get(FINVIZ_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[finviz] Request failed: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # Finviz screener table has class "screener-body-table-nw" rows
    table = soup.find("table", {"id": "screener-views-table"})
    if not table:
        # fallback: look for the data table by class
        table = soup.find("table", class_=re.compile(r"screener"))

    rows = []
    if table:
        all_rows = table.find_all("tr")
        # First row is header; skip it
        header_row = all_rows[0] if all_rows else None
        if header_row:
            headers = [th.get_text(strip=True) for th in header_row.find_all("td")]
        else:
            headers = []

        col_map = {name: idx for idx, name in enumerate(headers)}

        for row in all_rows[1:]:
            cols = row.find_all("td")
            if len(cols) < 10:
                continue
            try:
                # Finviz v=111 columns (roughly):
                # 0=No, 1=Ticker, 2=Company, 3=Sector, 4=Industry, 5=Country,
                # 6=Mkt Cap, 7=P/E, 8=Price, 9=Change, 10=Volume
                ticker_el = cols[1].find("a")
                ticker = ticker_el.get_text(strip=True) if ticker_el else cols[1].get_text(strip=True)
                company = cols[2].get_text(strip=True)
                price = _parse_float(cols[8].get_text(strip=True))
                change_pct = _parse_float(cols[9].get_text(strip=True))
                volume = _parse_float(cols[10].get_text(strip=True).replace("K", "e3").replace("M", "e6"))

                # Hard filters
                if not ticker or price <= 0 or price >= 20:
                    continue
                if _is_etf(company):
                    continue

                rows.append({
                    "ticker": ticker.upper(),
                    "company": company,
                    "price_premarket": round(price, 4),
                    "gap_pct": round(change_pct, 2),
                    "volume_premarket": int(volume),
                    "avg_volume": 0,  # will be filled by yf_data
                })

            except Exception:
                continue

    if not rows:
        # Try alternate parse — newer Finviz layout uses JS-rendered data
        # Fall back to parsing <a> tags with ticker hrefs
        rows = _parse_finviz_fallback(soup)

    print(f"[finviz] Found {len(rows)} pre-market movers (pre-filter)")
    return rows[:max_results]


def _parse_finviz_fallback(soup: BeautifulSoup) -> list[dict]:
    """Alternate parser for Finviz when table structure changes."""
    results = []
    # Look for ticker links pattern: /quote.ashx?t=TICKER
    ticker_links = soup.find_all("a", href=re.compile(r"quote\.ashx\?t="))
    seen = set()

    for link in ticker_links:
        ticker = link.get_text(strip=True)
        if not ticker or ticker in seen or len(ticker) > 5:
            continue
        seen.add(ticker)

        # Try to grab siblings for price/change
        parent_row = link.find_parent("tr")
        if not parent_row:
            continue
        cols = parent_row.find_all("td")
        if len(cols) < 9:
            continue

        try:
            price = _parse_float(cols[8].get_text(strip=True))
            if price <= 0 or price >= 20:
                continue
            change_pct = _parse_float(cols[9].get_text(strip=True)) if len(cols) > 9 else 0.0
            company = cols[2].get_text(strip=True) if len(cols) > 2 else ""
            if _is_etf(company):
                continue

            results.append({
                "ticker": ticker.upper(),
                "company": company,
                "price_premarket": round(price, 4),
                "gap_pct": round(change_pct, 2),
                "volume_premarket": 0,
                "avg_volume": 0,
            })
        except Exception:
            continue

    return results


if __name__ == "__main__":
    movers = get_premarket_movers()
    for m in movers[:10]:
        print(m)
