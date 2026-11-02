#!/usr/bin/env python3
"""Paper-only trade calculator. No broker connections.

Replaces the interim calc.py. Subcommands and flags are unchanged, and two
optional flags are added: ``size --side`` and ``pnl --slippage-per-share``.

Usage:
  python3 calc.py size --account 2290.65 --risk-pct 10 --entry 12.50 --stop 12.00 [--max-notional-pct 100] [--side long]
  python3 calc.py pnl --side long --qty 100 --entry 12.50 --stop 12.00 --exit 13.40 [--slippage-per-share 0.05] [--slippage-sides 2]
  python3 calc.py stats [--journal journal.csv] [--strategy S1] [--life 1]
  python3 calc.py test
"""

from __future__ import annotations

import argparse
import csv
import sys
import unittest
from decimal import Decimal
from pathlib import Path

from trade_math import TradeMath, TradeMathError

HERE = Path(__file__).resolve().parent
DEFAULT_JOURNAL = HERE / "journal.csv"


def load_journal(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def format_value(value: object) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def print_result(result: dict[str, object]) -> None:
    for key, value in result.items():
        print(f"{key}: {format_value(value)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Paper trade calculator (TradeMath)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    size = sub.add_parser("size", help="whole-share size from account, risk percent, and stop")
    size.add_argument("--account", required=True)
    size.add_argument("--risk-pct", required=True)
    size.add_argument("--entry", required=True)
    size.add_argument("--stop", required=True)
    size.add_argument("--max-notional-pct", default="100")
    size.add_argument(
        "--side",
        default=None,
        help="long or short; rejects a stop on the wrong side (default: either side)",
    )

    pnl = sub.add_parser("pnl", help="P&L, R, and WIN/LOSS/FLAT, with optional slippage")
    pnl.add_argument("--side", required=True)
    pnl.add_argument("--qty", required=True)
    pnl.add_argument("--entry", required=True)
    pnl.add_argument("--stop", required=True)
    pnl.add_argument("--exit", required=True)
    pnl.add_argument("--slippage-per-share", default="0")
    pnl.add_argument("--slippage-sides", default="2", help="1 or 2 adverse fills (default: 2)")

    stats = sub.add_parser("stats", help="summarize a paper journal csv")
    stats.add_argument("--journal", default=str(DEFAULT_JOURNAL))
    stats.add_argument("--strategy")
    stats.add_argument("--life")

    sub.add_parser("test", help="run the TradeMath unit tests")
    return parser


def run_tests() -> int:
    # Script directory is on sys.path, so the tests package imports directly.
    # Discover insists on a start package and rejects this layout.
    suite = unittest.defaultTestLoader.loadTestsFromName("tests.test_trade_math")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "size":
            result = TradeMath.position_size(
                args.account,
                args.risk_pct,
                args.entry,
                args.stop,
                args.max_notional_pct,
                side=args.side,
            )
        elif args.cmd == "pnl":
            result = TradeMath.trade_pnl(
                args.side,
                args.qty,
                args.entry,
                args.stop,
                args.exit,
                slippage_per_share=args.slippage_per_share,
                slippage_sides=args.slippage_sides,
            )
        elif args.cmd == "stats":
            journal = Path(args.journal)
            try:
                rows = load_journal(journal)
            except FileNotFoundError:
                print(f"error: journal not found: {journal}", file=sys.stderr)
                return 1
            except OSError as exc:
                print(f"error: cannot read journal: {exc}", file=sys.stderr)
                return 1
            result = TradeMath.summary_stats(rows, args.strategy, args.life)
        else:
            return run_tests()
    except TradeMathError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print_result(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
