"""
positions.py — Position sizing calculator
$300 max risk per trade, 3% stop, 2:1 R:R default
Capital capped at 1/3 of account per position.
"""

ACCOUNT_SIZE = 2000        # current paper balance
MAX_RISK_PER_TRADE = 300   # $300 max loss per trade
MAX_POSITIONS = 3
STOP_PCT = 0.03            # 3% below entry
DEFAULT_RR = 2.0           # 2:1 R:R
MAX_CAPITAL_PER_TRADE = ACCOUNT_SIZE // MAX_POSITIONS  # ~$666 max per position


def calculate_position(
    stock: dict,
    rr: float = DEFAULT_RR,
    stop_pct: float = STOP_PCT,
) -> dict:
    """
    Calculate entry, stop, target, shares, capital for a stock.
    Risk capped at $300/trade and capital capped at $666/position.
    """
    price = stock.get("price_premarket", 0.0)
    if price <= 0:
        stock["position_error"] = "invalid price"
        return stock

    # Entry = current pre-market price (round to nearest cent)
    entry = round(price, 2)

    # Stop = entry * (1 - stop_pct)
    stop = round(entry * (1 - stop_pct), 2)
    risk_per_share = round(entry - stop, 4)

    if risk_per_share <= 0:
        stock["position_error"] = "risk_per_share <= 0"
        return stock

    # Shares via risk sizing
    shares_by_risk = int(MAX_RISK_PER_TRADE / risk_per_share)

    # Shares via capital cap (no more than 1/3 of account per position)
    shares_by_capital = int(MAX_CAPITAL_PER_TRADE / entry)

    # Take the smaller of the two
    shares = min(shares_by_risk, shares_by_capital)
    if shares <= 0:
        shares = 1

    # Target = entry + (risk_per_share * rr)
    target = round(entry + (risk_per_share * rr), 2)

    # Capital deployed and actual max loss
    capital = round(shares * entry, 2)
    max_loss = round(shares * risk_per_share, 2)

    # Actual R:R
    actual_rr = round((target - entry) / risk_per_share, 2) if risk_per_share > 0 else 0

    stock["entry"] = entry
    stock["stop"] = stop
    stock["target"] = target
    stock["risk_per_share"] = risk_per_share
    stock["shares"] = shares
    stock["capital"] = capital
    stock["max_loss"] = max_loss
    stock["rr"] = actual_rr
    stock["entry_note"] = (
        f"Enter on first 5m candle close above pre-market high of ${entry:.2f}. "
        f"Confirm VWAP hold at 9:35 AM ET."
    )
    return stock


def size_all_positions(
    stocks: list[dict],
    max_positions: int = MAX_POSITIONS,
    rr: float = DEFAULT_RR,
    stop_pct: float = STOP_PCT,
) -> list[dict]:
    """Apply position sizing to top N stocks."""
    sized = []
    for stock in stocks[:max_positions]:
        sized.append(calculate_position(stock, rr=rr, stop_pct=stop_pct))
    return sized


if __name__ == "__main__":
    test = {"ticker": "XXXX", "price_premarket": 8.42}
    result = calculate_position(test)
    print(f"Entry: ${result['entry']} | Stop: ${result['stop']} | Target: ${result['target']}")
    print(f"Shares: {result['shares']} | Capital: ${result['capital']} | Max Loss: ${result['max_loss']}")
    print(f"R:R: {result['rr']}:1")
