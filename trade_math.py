"""Paper-only trade math. No broker connections and no I/O.

One class, :class:`TradeMath`, owns position sizing, P&L, R-multiples,
slippage, and journal aggregates. Scanner pick sizing in
``scanner/positions.py`` is a different policy (fixed dollar risk, synthetic
percent stop) and is intentionally not called from here.

Rounding
    Every reported money, price, R, rate, and slippage-share figure is
    quantized with ``Decimal`` half-away-from-zero (``ROUND_HALF_UP``).
    Share counts use exact ``Decimal`` division and floor. That replaces the
    interim calculator's binary ``float`` and Python bankers' ``round``,
    which turns a risk budget of 229.065 into 229.06 instead of 229.07.
    Inputs that arrive as ``float`` are parsed with ``str(float)`` (shortest
    round-trip), so pass the original prices rather than a float subtraction.

Sizing
    risk_budget = account * risk_pct / 100
    risk_per_share = distance from entry to a valid stop
    qty_by_risk = floor(risk_budget / risk_per_share)
    qty_by_notional = floor(account * max_notional_pct / 100 / entry)
    qty = min(qty_by_risk, qty_by_notional)

    The share count uses the exact budget, then the displayed budget is
    rounded to cents. A stop on the wrong side is an error when ``side`` is
    known. Without ``side``, either direction is accepted and a zero
    distance still raises. A budget that cannot buy one share returns
    ``qty`` 0; that is a cap, not an invalid input.

P&L
    gross = direction * (exit - entry) * qty
    R = gross / (risk_per_share * qty)
    slippage_risk_share = slippage_per_share / risk_per_share
    slippage_cost = slippage_per_share * qty * slippage_sides
    net = gross - slippage_cost

    ``slippage_sides`` defaults to 2 (entry and exit). Slippage is always
    adverse. Outcome is WIN, LOSS, or FLAT from the cent-rounded net P&L.
    A rounded net of 0 is FLAT, including a trade that closed at the entry.
"""

from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, ROUND_HALF_UP
from typing import Mapping, Optional, Sequence, Union

Number = Union[Decimal, int, str, float]

_MONEY = Decimal("0.01")
_PRICE = Decimal("0.0001")
_R = Decimal("0.001")
_RATE = Decimal("0.0001")
_SHARE = Decimal("0.000001")


class TradeMathError(ValueError):
    """Invalid trade input. Callers get a message instead of a silent zero."""


class TradeMath:
    """Static paper-trade calculations.

    Methods do not read files, talk to a broker, or keep state.
    """

    MONEY = _MONEY
    PRICE = _PRICE
    R = _R
    RATE = _RATE
    SHARE = _SHARE

    @staticmethod
    def position_size(
        account: Number,
        risk_pct: Number,
        entry: Number,
        stop: Number,
        max_notional_pct: Number = 100,
        side: Optional[str] = None,
    ) -> dict[str, object]:
        """Whole-share size from account, risk percent, entry, stop, and notional cap.

        ``side`` is optional. ``"long"`` requires ``stop < entry``. ``"short"``
        requires ``stop > entry``. Omit ``side`` to size off the absolute
        distance, which is what the interim calculator did.
        """
        account_d = TradeMath._positive(account, "account")
        risk_pct_d = TradeMath._positive(risk_pct, "risk_pct")
        entry_d = TradeMath._positive(entry, "entry")
        stop_d = TradeMath._decimal(stop, "stop")
        cap_pct = TradeMath._decimal(max_notional_pct, "max_notional_pct")
        if cap_pct < 0:
            raise TradeMathError("max_notional_pct must be >= 0")

        direction = TradeMath._side(side, required=False)
        risk_per_share = TradeMath._risk_per_share(direction, entry_d, stop_d)

        risk_budget = account_d * risk_pct_d / Decimal(100)
        notional_cap = account_d * cap_pct / Decimal(100)
        qty_by_risk = TradeMath._floor_div(risk_budget, risk_per_share)
        qty_by_notional = TradeMath._floor_div(notional_cap, entry_d)
        qty = min(qty_by_risk, qty_by_notional)

        return {
            "qty": qty,
            "qty_by_risk": qty_by_risk,
            "qty_by_notional": qty_by_notional,
            "risk_budget": TradeMath._q(risk_budget, _MONEY),
            "risk_per_share": TradeMath._q(risk_per_share, _PRICE),
            "actual_risk": TradeMath._q(Decimal(qty) * risk_per_share, _MONEY),
            "notional": TradeMath._q(Decimal(qty) * entry_d, _MONEY),
            "capped_by_notional": qty_by_notional < qty_by_risk,
        }

    @staticmethod
    def trade_pnl(
        side: str,
        qty: Number,
        entry: Number,
        stop: Number,
        exit_price: Number,
        slippage_per_share: Number = 0,
        slippage_sides: Number = 2,
    ) -> dict[str, object]:
        """Gross and slippage-adjusted P&L, R, and WIN/LOSS/FLAT.

        ``slippage_per_share`` is an adverse price. ``slippage_sides`` is 1
        (one fill) or 2 (entry and exit, the default for a closed trade).
        ``slippage_risk_share`` is that per-share slippage divided by risk
        per share.
        """
        direction = TradeMath._side(side, required=True)
        qty_d = TradeMath._positive(qty, "qty")
        entry_d = TradeMath._positive(entry, "entry")
        stop_d = TradeMath._decimal(stop, "stop")
        exit_d = TradeMath._decimal(exit_price, "exit")
        if exit_d < 0:
            raise TradeMathError("exit must be >= 0")
        slip = TradeMath._decimal(slippage_per_share, "slippage_per_share")
        if slip < 0:
            raise TradeMathError("slippage_per_share must be >= 0")
        sides = TradeMath._slippage_sides(slippage_sides)

        risk_per_share = TradeMath._risk_per_share(direction, entry_d, stop_d)
        sign = Decimal(1) if direction == "long" else Decimal(-1)
        gross = sign * (exit_d - entry_d) * qty_d
        risk_dollars = risk_per_share * qty_d
        cost = slip * qty_d * Decimal(sides)
        net = gross - cost
        share = TradeMath.slippage_risk_share(slip, risk_per_share)

        return {
            "pnl_usd": TradeMath._q(gross, _MONEY),
            "r_multiple": TradeMath._q(gross / risk_dollars, _R),
            "outcome": TradeMath.classify(net),
            "slippage_per_share": TradeMath._q(slip, _PRICE),
            "slippage_sides": sides,
            "slippage_risk_share": share,
            "slippage_cost_usd": TradeMath._q(cost, _MONEY),
            "pnl_after_slippage": TradeMath._q(net, _MONEY),
            "r_after_slippage": TradeMath._q(net / risk_dollars, _R),
        }

    @staticmethod
    def slippage_risk_share(slippage_per_share: Number, risk_per_share: Number) -> Decimal:
        """Slippage on one fill as a fraction of per-share risk.

        0.05 of slippage against 0.50 of risk is 0.100000, or 0.1R.
        """
        slip = TradeMath._decimal(slippage_per_share, "slippage_per_share")
        risk = TradeMath._decimal(risk_per_share, "risk_per_share")
        if slip < 0:
            raise TradeMathError("slippage_per_share must be >= 0")
        if risk <= 0:
            raise TradeMathError("risk_per_share must be > 0")
        return TradeMath._q(slip / risk, _SHARE)

    @staticmethod
    def classify(pnl: Number) -> str:
        """WIN, LOSS, or FLAT from cent-rounded P&L. A rounded 0 is FLAT."""
        money = TradeMath._q(TradeMath._decimal(pnl, "pnl"), _MONEY)
        if money > 0:
            return "WIN"
        if money < 0:
            return "LOSS"
        return "FLAT"

    @staticmethod
    def summary_stats(
        rows: Sequence[Mapping[str, object]],
        strategy: Optional[str] = None,
        life: Optional[object] = None,
    ) -> dict[str, object]:
        """Aggregate closed trades.

        Top-up rows (strategy ``TOPUP``, any case) are excluded. Rows with a
        blank or non-numeric ``pnl_usd`` are open and skipped. A cent-rounded
        P&L of 0 counts as ``flats``, not as a loss. ``win_rate`` is wins
        divided by closed trades, so a flat is not a win either.

        ``expectancy_r`` is the mean R of trades that recorded one, matching
        the interim calculator. ``expectancy_usd`` is
        ``win_rate * avg_win + loss_rate * avg_loss`` with flats contributing
        zero. No closed trades returns ``{"trades": 0}``.
        """
        if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence):
            raise TradeMathError("rows must be a sequence of journal records")

        pnls: list[Decimal] = []
        rs: list[Decimal] = []
        for row in rows:
            if not isinstance(row, Mapping):
                raise TradeMathError("each journal row must be a mapping")
            if str(row.get("strategy") or "").upper() == "TOPUP":
                continue
            if strategy is not None and row.get("strategy") != strategy:
                continue
            if life is not None and str(row.get("life")) != str(life):
                continue
            pnl = TradeMath._optional_decimal(row.get("pnl_usd"))
            if pnl is None:
                continue
            pnls.append(pnl)
            r_value = TradeMath._optional_decimal(row.get("r_multiple"))
            if r_value is not None:
                rs.append(r_value)

        n = len(pnls)
        if n == 0:
            return {"trades": 0}

        wins = [p for p in pnls if TradeMath.classify(p) == "WIN"]
        losses = [p for p in pnls if TradeMath.classify(p) == "LOSS"]
        flats = n - len(wins) - len(losses)
        win_rate = Decimal(len(wins)) / Decimal(n)
        loss_rate = Decimal(len(losses)) / Decimal(n)
        avg_win = sum(wins, Decimal(0)) / Decimal(len(wins)) if wins else Decimal(0)
        avg_loss = sum(losses, Decimal(0)) / Decimal(len(losses)) if losses else Decimal(0)
        expectancy = win_rate * avg_win + loss_rate * avg_loss

        equity = Decimal(0)
        peak = Decimal(0)
        drawdown = Decimal(0)
        for pnl in pnls:
            equity += pnl
            if equity > peak:
                peak = equity
            drop = peak - equity
            if drop > drawdown:
                drawdown = drop

        avg_r = (sum(rs, Decimal(0)) / Decimal(len(rs))) if rs else None
        return {
            "trades": n,
            "wins": len(wins),
            "losses": len(losses),
            "flats": flats,
            "win_rate": TradeMath._q(win_rate, _RATE),
            "avg_r": None if avg_r is None else TradeMath._q(avg_r, _R),
            "expectancy_usd": TradeMath._q(expectancy, _MONEY),
            "expectancy_r": None if avg_r is None else TradeMath._q(avg_r, _R),
            "max_drawdown_usd": TradeMath._q(drawdown, _MONEY),
            "total_pnl_usd": TradeMath._q(sum(pnls, Decimal(0)), _MONEY),
        }

    @staticmethod
    def _risk_per_share(side: Optional[str], entry: Decimal, stop: Decimal) -> Decimal:
        if side == "long" and stop >= entry:
            raise TradeMathError(
                f"stop must be below entry for a long (entry={entry}, stop={stop})"
            )
        if side == "short" and stop <= entry:
            raise TradeMathError(
                f"stop must be above entry for a short (entry={entry}, stop={stop})"
            )
        distance = abs(entry - stop)
        if distance <= 0:
            raise TradeMathError("entry and stop must differ")
        return distance

    @staticmethod
    def _side(side: Optional[str], *, required: bool) -> Optional[str]:
        if side is None:
            if required:
                raise TradeMathError("side must be long or short")
            return None
        if not isinstance(side, str):
            raise TradeMathError("side must be long or short")
        norm = side.strip().lower()
        if norm not in ("long", "short"):
            raise TradeMathError("side must be long or short")
        return norm

    @staticmethod
    def _slippage_sides(value: Number) -> int:
        if isinstance(value, bool):
            raise TradeMathError("slippage_sides must be 1 or 2")
        try:
            if isinstance(value, int):
                sides = value
            elif isinstance(value, float):
                if not math.isfinite(value) or not value.is_integer():
                    raise TradeMathError("slippage_sides must be 1 or 2")
                sides = int(value)
            else:
                dec = TradeMath._decimal(value, "slippage_sides")
                if dec != dec.to_integral_value():
                    raise TradeMathError("slippage_sides must be 1 or 2")
                sides = int(dec)
        except TradeMathError:
            raise
        except (InvalidOperation, ValueError, ArithmeticError) as exc:
            raise TradeMathError("slippage_sides must be 1 or 2") from exc
        if sides not in (1, 2):
            raise TradeMathError("slippage_sides must be 1 or 2")
        return sides

    @staticmethod
    def _positive(value: Number, name: str) -> Decimal:
        dec = TradeMath._decimal(value, name)
        if dec <= 0:
            raise TradeMathError(f"{name} must be > 0")
        return dec

    @staticmethod
    def _optional_decimal(value: object) -> Optional[Decimal]:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        try:
            return TradeMath._decimal(value, "value")
        except TradeMathError:
            return None

    @staticmethod
    def _decimal(value: object, name: str) -> Decimal:
        if isinstance(value, bool) or value is None:
            raise TradeMathError(f"{name} must be a finite number")
        try:
            if isinstance(value, Decimal):
                dec = value
            elif isinstance(value, int):
                dec = Decimal(value)
            elif isinstance(value, float):
                if not math.isfinite(value):
                    raise TradeMathError(f"{name} must be a finite number")
                dec = Decimal(str(value))
            elif isinstance(value, str):
                dec = Decimal(value.strip())
            else:
                raise TradeMathError(f"{name} must be a finite number")
        except TradeMathError:
            raise
        except (InvalidOperation, ValueError, ArithmeticError) as exc:
            raise TradeMathError(f"{name} must be a finite number") from exc
        if not dec.is_finite():
            raise TradeMathError(f"{name} must be a finite number")
        return dec

    @staticmethod
    def _q(value: Decimal, quantum: Decimal) -> Decimal:
        return value.quantize(quantum, rounding=ROUND_HALF_UP)

    @staticmethod
    def _floor_div(numerator: Decimal, denominator: Decimal) -> int:
        if denominator <= 0:
            raise TradeMathError("divisor must be > 0")
        if numerator < 0:
            raise TradeMathError("share count numerator must be >= 0")
        return int(divmod(numerator, denominator)[0].to_integral_value(rounding=ROUND_FLOOR))
