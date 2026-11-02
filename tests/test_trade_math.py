"""Hand-checked examples and edge cases for TradeMath.

Worked size, account 2290.65, 10% risk, entry 12.50, stop 12.00, 100% notional:
    budget = 2290.65 * 0.10 = 229.065, half-up to 229.07
    risk/share = 0.50
    qty by risk = floor(229.065 / 0.50) = 458
    qty by notional = floor(2290.65 / 12.50) = 183
    qty = 183, actual risk = 91.50, notional = 2287.50

Worked P&L, long 100 from 12.50 to 13.40, stop 12.00:
    gross = 0.90 * 100 = 90.00, risk = 50.00, R = 1.800
    slippage 0.05/share on 2 fills = 10.00, net = 80.00, R = 1.600
    slippage share of risk = 0.05 / 0.50 = 0.100000
"""

from __future__ import annotations

import sys
import unittest
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trade_math import TradeMath, TradeMathError


def money(text: str) -> Decimal:
    return Decimal(text)


class TestPositionSize(unittest.TestCase):
    def test_notional_cap_hand_checked(self):
        size = TradeMath.position_size(2290.65, 10, "12.50", "12.00")
        self.assertEqual(size["qty"], 183)
        self.assertEqual(size["qty_by_risk"], 458)
        self.assertEqual(size["qty_by_notional"], 183)
        self.assertEqual(size["risk_budget"], money("229.07"))
        self.assertEqual(size["risk_per_share"], money("0.5000"))
        self.assertEqual(size["actual_risk"], money("91.50"))
        self.assertEqual(size["notional"], money("2287.50"))
        self.assertTrue(size["capped_by_notional"])
        # Interim float round(229.065, 2) is bankers' 229.06. Keep the cent.
        bankers = Decimal("229.065").quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        self.assertEqual(bankers, money("229.06"))
        self.assertNotEqual(size["risk_budget"], bankers)

    def test_risk_cap_hand_checked(self):
        size = TradeMath.position_size(10000, 1, 50, 49)
        self.assertEqual(size["qty"], 100)
        self.assertEqual(size["qty_by_risk"], 100)
        self.assertEqual(size["qty_by_notional"], 200)
        self.assertEqual(size["actual_risk"], money("100.00"))
        self.assertEqual(size["notional"], money("5000.00"))
        self.assertEqual(size["risk_budget"], money("100.00"))
        self.assertFalse(size["capped_by_notional"])

    def test_short_distance_without_side_matches_interim(self):
        unsigned = TradeMath.position_size(10000, 1, 50, 51)
        signed = TradeMath.position_size(10000, 1, 50, 51, side="short")
        self.assertEqual(unsigned["qty"], 100)
        self.assertEqual(signed["qty"], 100)
        self.assertEqual(signed["risk_per_share"], money("1.0000"))
        self.assertEqual(signed["actual_risk"], money("100.00"))

    def test_equal_risk_and_notional_qty_is_not_capped(self):
        # 2% of 10_000 = 200, risk/share 1, notional cap 10_000/50 = 200.
        size = TradeMath.position_size(10000, 2, 50, 49)
        self.assertEqual(size["qty"], 200)
        self.assertEqual(size["qty_by_risk"], 200)
        self.assertEqual(size["qty_by_notional"], 200)
        self.assertFalse(size["capped_by_notional"])
        self.assertEqual(size["notional"], money("10000.00"))

    def test_thirty_five_percent_notional_cap(self):
        # Engine-style cap: 1% risk wants 100 shares, 35% notional allows 70.
        size = TradeMath.position_size(10000, 1, 50, 49, max_notional_pct=35)
        self.assertEqual(size["qty_by_risk"], 100)
        self.assertEqual(size["qty_by_notional"], 70)
        self.assertEqual(size["qty"], 70)
        self.assertTrue(size["capped_by_notional"])
        self.assertEqual(size["actual_risk"], money("70.00"))
        self.assertEqual(size["notional"], money("3500.00"))

    def test_budget_too_small_for_one_share_is_zero_not_an_error(self):
        size = TradeMath.position_size(10, 1, 50, 49)
        self.assertEqual(size["risk_budget"], money("0.10"))
        self.assertEqual(size["qty_by_risk"], 0)
        self.assertEqual(size["qty_by_notional"], 0)
        self.assertEqual(size["qty"], 0)
        self.assertEqual(size["actual_risk"], money("0.00"))
        self.assertEqual(size["notional"], money("0.00"))
        self.assertFalse(size["capped_by_notional"])

    def test_notional_cap_zero_blocks_shares_after_valid_risk(self):
        size = TradeMath.position_size(10000, 1, 50, 49, max_notional_pct=0)
        self.assertEqual(size["qty_by_risk"], 100)
        self.assertEqual(size["qty"], 0)
        self.assertTrue(size["capped_by_notional"])

    def test_decimal_risk_per_share_not_binary_residue(self):
        # 10.10 - 10.00 is 0.09999999999999964 in binary. Sizing uses 0.10.
        # 0.5% of 10_000 is $50, so risk wants 500 shares. 100% notional
        # allows floor(10000 / 10.10) = 990, so risk binds.
        size = TradeMath.position_size(10000, "0.5", "10.10", "10.00")
        self.assertEqual(size["risk_per_share"], money("0.1000"))
        self.assertEqual(size["risk_budget"], money("50.00"))
        self.assertEqual(size["qty_by_risk"], 500)
        self.assertEqual(size["qty_by_notional"], 990)
        self.assertEqual(size["qty"], 500)
        self.assertEqual(size["actual_risk"], money("50.00"))
        self.assertFalse(size["capped_by_notional"])

    def test_half_cent_actual_risk_rounds_away_from_zero(self):
        # One share, 0.005 risk, half-up to a cent of actual risk.
        size = TradeMath.position_size(10, 100, "10", "9.995")
        self.assertEqual(size["qty"], 1)
        self.assertEqual(size["risk_per_share"], money("0.0050"))
        self.assertEqual(size["actual_risk"], money("0.01"))

    def test_string_and_decimal_inputs_match(self):
        from_strings = TradeMath.position_size("10000", "1", "50", "49", "100")
        from_decimals = TradeMath.position_size(
            Decimal("10000"), Decimal("1"), Decimal("50"), Decimal("49"), Decimal("100")
        )
        self.assertEqual(from_strings, from_decimals)

    def test_reported_scales(self):
        size = TradeMath.position_size(10000, 1, 50, 49)
        self.assertEqual(size["risk_budget"].as_tuple().exponent, -2)
        self.assertEqual(size["actual_risk"].as_tuple().exponent, -2)
        self.assertEqual(size["notional"].as_tuple().exponent, -2)
        self.assertEqual(size["risk_per_share"].as_tuple().exponent, -4)


class TestGuards(unittest.TestCase):
    def test_non_positive_account_risk_and_entry(self):
        for kwargs in (
            {"account": 0, "risk_pct": 1, "entry": 10, "stop": 9},
            {"account": -1, "risk_pct": 1, "entry": 10, "stop": 9},
            {"account": 1000, "risk_pct": 0, "entry": 10, "stop": 9},
            {"account": 1000, "risk_pct": -5, "entry": 10, "stop": 9},
            {"account": 1000, "risk_pct": 1, "entry": 0, "stop": -1},
            {"account": 1000, "risk_pct": 1, "entry": -10, "stop": -11},
        ):
            with self.assertRaises(TradeMathError):
                TradeMath.position_size(**kwargs)

    def test_messages_name_the_bad_field(self):
        with self.assertRaisesRegex(TradeMathError, "account must be > 0"):
            TradeMath.position_size(0, 1, 10, 9)
        with self.assertRaisesRegex(TradeMathError, "risk_pct must be > 0"):
            TradeMath.position_size(1000, 0, 10, 9)
        with self.assertRaisesRegex(TradeMathError, "entry must be > 0"):
            TradeMath.position_size(1000, 1, 0, 1)
        with self.assertRaisesRegex(TradeMathError, "entry and stop must differ"):
            TradeMath.position_size(1000, 1, 10, 10)
        with self.assertRaisesRegex(TradeMathError, "max_notional_pct must be >= 0"):
            TradeMath.position_size(1000, 1, 10, 9, max_notional_pct=-1)

    def test_stop_on_the_wrong_side_raises_instead_of_zero_qty(self):
        with self.assertRaisesRegex(TradeMathError, "stop must be below entry for a long"):
            TradeMath.position_size(10000, 1, 50, 51, side="long")
        with self.assertRaisesRegex(TradeMathError, "stop must be below entry for a long"):
            TradeMath.position_size(10000, 1, 50, 50, side="LONG")
        with self.assertRaisesRegex(TradeMathError, "stop must be above entry for a short"):
            TradeMath.position_size(10000, 1, 50, 49, side="short")
        with self.assertRaisesRegex(TradeMathError, "side must be long or short"):
            TradeMath.position_size(10000, 1, 50, 49, side="buy")

    def test_non_finite_and_non_numeric(self):
        with self.assertRaises(TradeMathError):
            TradeMath.position_size(float("nan"), 1, 10, 9)
        with self.assertRaises(TradeMathError):
            TradeMath.position_size(float("inf"), 1, 10, 9)
        with self.assertRaises(TradeMathError):
            TradeMath.position_size(True, 1, 10, 9)
        with self.assertRaises(TradeMathError):
            TradeMath.position_size("ten", 1, 10, 9)
        with self.assertRaises(TradeMathError):
            TradeMath.position_size(None, 1, 10, 9)

    def test_pnl_rejects_bad_qty_side_exit_and_wrong_stop(self):
        with self.assertRaisesRegex(TradeMathError, "qty must be > 0"):
            TradeMath.trade_pnl("long", 0, 10, 9, 11)
        with self.assertRaisesRegex(TradeMathError, "side must be long or short"):
            TradeMath.trade_pnl("flat", 1, 10, 9, 11)
        with self.assertRaisesRegex(TradeMathError, "exit must be >= 0"):
            TradeMath.trade_pnl("long", 1, 10, 9, -1)
        with self.assertRaisesRegex(TradeMathError, "stop must be below entry for a long"):
            TradeMath.trade_pnl("long", 10, 50, 51, 49)
        with self.assertRaisesRegex(TradeMathError, "stop must be above entry for a short"):
            TradeMath.trade_pnl("short", 10, 50, 49, 48)
        with self.assertRaisesRegex(TradeMathError, "stop must be below entry for a long"):
            TradeMath.trade_pnl("long", 10, 50, 50, 51)
        with self.assertRaisesRegex(TradeMathError, "slippage_per_share must be >= 0"):
            TradeMath.trade_pnl("long", 10, 50, 49, 51, slippage_per_share=-0.01)
        with self.assertRaisesRegex(TradeMathError, "slippage_sides must be 1 or 2"):
            TradeMath.trade_pnl("long", 10, 50, 49, 51, slippage_sides=3)
        with self.assertRaisesRegex(TradeMathError, "slippage_sides must be 1 or 2"):
            TradeMath.trade_pnl("long", 10, 50, 49, 51, slippage_sides=True)
        with self.assertRaisesRegex(TradeMathError, "slippage_sides must be 1 or 2"):
            TradeMath.trade_pnl("long", 10, 50, 49, 51, slippage_sides=1.5)


class TestTradePnl(unittest.TestCase):
    def test_long_winner_hand_checked(self):
        pnl = TradeMath.trade_pnl("long", 100, "12.50", "12.00", "13.40")
        self.assertEqual(pnl["pnl_usd"], money("90.00"))
        self.assertEqual(pnl["r_multiple"], money("1.800"))
        self.assertEqual(pnl["outcome"], "WIN")
        self.assertEqual(pnl["pnl_after_slippage"], money("90.00"))
        self.assertEqual(pnl["r_after_slippage"], money("1.800"))
        self.assertEqual(pnl["slippage_cost_usd"], money("0.00"))
        self.assertEqual(pnl["slippage_risk_share"], money("0.000000"))
        self.assertEqual(pnl["slippage_sides"], 2)

    def test_short_loser_hand_checked(self):
        pnl = TradeMath.trade_pnl("short", 10, 50, 51, 52)
        self.assertEqual(pnl["pnl_usd"], money("-20.00"))
        self.assertEqual(pnl["r_multiple"], money("-2.000"))
        self.assertEqual(pnl["outcome"], "LOSS")

    def test_short_winner(self):
        pnl = TradeMath.trade_pnl("Short", 10, 50, 51, 48)
        self.assertEqual(pnl["pnl_usd"], money("20.00"))
        self.assertEqual(pnl["r_multiple"], money("2.000"))
        self.assertEqual(pnl["outcome"], "WIN")

    def test_zero_price_move_is_flat_not_a_loss(self):
        # 10-19 SD-style scratch: exit equals entry.
        pnl = TradeMath.trade_pnl("long", 100, "14.30", "14.00", "14.30")
        self.assertEqual(pnl["pnl_usd"], money("0.00"))
        self.assertEqual(pnl["r_multiple"], money("0.000"))
        self.assertEqual(pnl["outcome"], "FLAT")

    def test_stop_out_is_minus_one_r(self):
        pnl = TradeMath.trade_pnl("long", 100, "12.50", "12.00", "12.00")
        self.assertEqual(pnl["pnl_usd"], money("-50.00"))
        self.assertEqual(pnl["r_multiple"], money("-1.000"))
        self.assertEqual(pnl["outcome"], "LOSS")

    def test_two_r_target(self):
        pnl = TradeMath.trade_pnl("long", 100, "12.50", "12.00", "13.50")
        self.assertEqual(pnl["pnl_usd"], money("100.00"))
        self.assertEqual(pnl["r_multiple"], money("2.000"))

    def test_fractional_qty(self):
        pnl = TradeMath.trade_pnl("long", "0.5", 100, 90, 110)
        self.assertEqual(pnl["pnl_usd"], money("5.00"))
        self.assertEqual(pnl["r_multiple"], money("1.000"))

    def test_half_cent_loss_rounds_away_from_zero_and_is_a_loss(self):
        # Exact gross -0.005 rounds to -0.01. A raw +0.004 rounds to 0.00 FLAT.
        loss = TradeMath.trade_pnl("long", 1, 10, 9, "9.995")
        self.assertEqual(loss["pnl_usd"], money("-0.01"))
        self.assertEqual(loss["r_multiple"], money("-0.005"))
        self.assertEqual(loss["outcome"], "LOSS")
        scratch = TradeMath.trade_pnl("long", 1, 10, 9, "10.004")
        self.assertEqual(scratch["pnl_usd"], money("0.00"))
        self.assertEqual(scratch["r_multiple"], money("0.004"))
        self.assertEqual(scratch["outcome"], "FLAT")

    def test_exit_zero_is_allowed(self):
        pnl = TradeMath.trade_pnl("long", 2, 10, 8, 0)
        self.assertEqual(pnl["pnl_usd"], money("-20.00"))
        self.assertEqual(pnl["r_multiple"], money("-5.000"))


class TestSlippage(unittest.TestCase):
    def test_round_trip_slippage_hand_checked(self):
        pnl = TradeMath.trade_pnl(
            "long", 100, "12.50", "12.00", "13.40", slippage_per_share="0.05"
        )
        self.assertEqual(pnl["pnl_usd"], money("90.00"))
        self.assertEqual(pnl["r_multiple"], money("1.800"))
        self.assertEqual(TradeMath.slippage_risk_share("0.05", "0.50"), money("0.100000"))
        self.assertEqual(pnl["slippage_risk_share"], money("0.100000"))
        self.assertEqual(pnl["slippage_sides"], 2)
        self.assertEqual(pnl["slippage_cost_usd"], money("10.00"))
        self.assertEqual(pnl["pnl_after_slippage"], money("80.00"))
        self.assertEqual(pnl["r_after_slippage"], money("1.600"))
        self.assertEqual(pnl["outcome"], "WIN")

    def test_one_fill_slippage(self):
        pnl = TradeMath.trade_pnl(
            "long",
            100,
            "12.50",
            "12.00",
            "13.40",
            slippage_per_share="0.05",
            slippage_sides=1,
        )
        self.assertEqual(pnl["slippage_cost_usd"], money("5.00"))
        self.assertEqual(pnl["pnl_after_slippage"], money("85.00"))
        self.assertEqual(pnl["r_after_slippage"], money("1.700"))
        self.assertEqual(pnl["slippage_risk_share"], money("0.100000"))

    def test_slippage_can_flip_a_winner_to_a_loss(self):
        # Gross +5.00 (0.050R). Two fills at 0.04 cost 8.00, net -3.00.
        pnl = TradeMath.trade_pnl(
            "long", 100, 10, 9, "10.05", slippage_per_share="0.04"
        )
        self.assertEqual(pnl["pnl_usd"], money("5.00"))
        self.assertEqual(pnl["r_multiple"], money("0.050"))
        self.assertEqual(pnl["slippage_risk_share"], money("0.040000"))
        self.assertEqual(pnl["slippage_cost_usd"], money("8.00"))
        self.assertEqual(pnl["pnl_after_slippage"], money("-3.00"))
        self.assertEqual(pnl["r_after_slippage"], money("-0.030"))
        self.assertEqual(pnl["outcome"], "LOSS")

    def test_slippage_that_lands_on_zero_is_flat(self):
        pnl = TradeMath.trade_pnl(
            "long", 10, 10, 9, "10.20", slippage_per_share="0.10"
        )
        # Gross 2.00, two-sided cost 2.00.
        self.assertEqual(pnl["pnl_usd"], money("2.00"))
        self.assertEqual(pnl["pnl_after_slippage"], money("0.00"))
        self.assertEqual(pnl["outcome"], "FLAT")

    def test_three_share_odd_lot(self):
        # Gross 0.30, cost 0.06, net 0.24, R 0.100 and 0.080 on 3.00 of risk.
        pnl = TradeMath.trade_pnl(
            "long", 3, 10, 9, "10.10", slippage_per_share="0.01", slippage_sides=2
        )
        self.assertEqual(pnl["pnl_usd"], money("0.30"))
        self.assertEqual(pnl["slippage_cost_usd"], money("0.06"))
        self.assertEqual(pnl["pnl_after_slippage"], money("0.24"))
        self.assertEqual(pnl["r_multiple"], money("0.100"))
        self.assertEqual(pnl["r_after_slippage"], money("0.080"))
        self.assertEqual(pnl["slippage_risk_share"], money("0.010000"))

    def test_share_rejects_non_positive_risk(self):
        with self.assertRaisesRegex(TradeMathError, "risk_per_share must be > 0"):
            TradeMath.slippage_risk_share("0.01", 0)
        with self.assertRaisesRegex(TradeMathError, "slippage_per_share must be >= 0"):
            TradeMath.slippage_risk_share("-0.01", "0.50")


class TestClassify(unittest.TestCase):
    def test_sign_after_cent_rounding(self):
        self.assertEqual(TradeMath.classify("0"), "FLAT")
        self.assertEqual(TradeMath.classify("0.00"), "FLAT")
        self.assertEqual(TradeMath.classify("-0.00"), "FLAT")
        self.assertEqual(TradeMath.classify("0.004"), "FLAT")
        self.assertEqual(TradeMath.classify("-0.004"), "FLAT")
        self.assertEqual(TradeMath.classify("0.005"), "WIN")
        self.assertEqual(TradeMath.classify("-0.005"), "LOSS")
        self.assertEqual(TradeMath.classify(90), "WIN")
        self.assertEqual(TradeMath.classify("-20.00"), "LOSS")

    def test_bad_pnl(self):
        with self.assertRaises(TradeMathError):
            TradeMath.classify(None)
        with self.assertRaises(TradeMathError):
            TradeMath.classify("n/a")


class TestSummaryStats(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {"strategy": "S1", "pnl_usd": "100", "r_multiple": "2", "life": "1"},
            {"strategy": "S1", "pnl_usd": "-50", "r_multiple": "-1", "life": "1"},
            {"strategy": "S1", "pnl_usd": "-50", "r_multiple": "-1", "life": "1"},
            {"strategy": "TOPUP", "pnl_usd": "2000", "r_multiple": "", "life": "2"},
            {"strategy": "S2", "pnl_usd": "30", "r_multiple": "1", "life": "2"},
            {"strategy": "S2", "pnl_usd": "", "r_multiple": "", "life": "2"},
        ]

    def test_interim_sample_plus_flat_count(self):
        # Wins 100 and 30, losses -50 and -50. Top-up and blank P&L are out.
        # avg win 65, avg loss -50, expectancy 0.5*65 + 0.5*(-50) = 7.50.
        # Equity 100, 50, 0, 30. Peak 100, max drawdown 100.
        # Mean R (2 - 1 - 1 + 1) / 4 = 0.250.
        stats = TradeMath.summary_stats(self.rows)
        self.assertEqual(stats["trades"], 4)
        self.assertEqual(stats["wins"], 2)
        self.assertEqual(stats["losses"], 2)
        self.assertEqual(stats["flats"], 0)
        self.assertEqual(stats["total_pnl_usd"], money("30.00"))
        self.assertEqual(stats["max_drawdown_usd"], money("100.00"))
        self.assertEqual(stats["win_rate"], money("0.5000"))
        self.assertEqual(stats["avg_r"], money("0.250"))
        self.assertEqual(stats["expectancy_usd"], money("7.50"))
        self.assertEqual(stats["expectancy_r"], money("0.250"))

    def test_filters_and_empty(self):
        self.assertEqual(TradeMath.summary_stats(self.rows, strategy="S1")["trades"], 3)
        self.assertEqual(TradeMath.summary_stats(self.rows, life=2)["trades"], 1)
        self.assertEqual(TradeMath.summary_stats(self.rows, life="2")["trades"], 1)
        self.assertEqual(TradeMath.summary_stats([])["trades"], 0)
        self.assertEqual(set(TradeMath.summary_stats([])), {"trades"})

    def test_flat_is_not_a_win_or_a_loss(self):
        rows = [
            {"strategy": "S1", "pnl_usd": "100", "r_multiple": "1", "life": "1"},
            {"strategy": "S1", "pnl_usd": "0", "r_multiple": "0", "life": "1"},
            {"strategy": "S1", "pnl_usd": "-50", "r_multiple": "-1", "life": "1"},
            {"strategy": "topup", "pnl_usd": "999", "r_multiple": "9", "life": "1"},
        ]
        stats = TradeMath.summary_stats(rows)
        self.assertEqual(stats["trades"], 3)
        self.assertEqual(stats["wins"], 1)
        self.assertEqual(stats["losses"], 1)
        self.assertEqual(stats["flats"], 1)
        self.assertEqual(stats["win_rate"], money("0.3333"))
        # (1/3)*100 + (1/3)*(-50) = 16.666... -> 16.67
        self.assertEqual(stats["expectancy_usd"], money("16.67"))
        self.assertEqual(stats["total_pnl_usd"], money("50.00"))
        self.assertEqual(stats["max_drawdown_usd"], money("50.00"))
        self.assertEqual(stats["avg_r"], money("0.000"))

    def test_sub_cent_flat_and_half_up_average_r(self):
        rows = [
            {"pnl_usd": "0.004", "r_multiple": "1.2345"},
            {"pnl_usd": "-0.004", "r_multiple": ""},
        ]
        stats = TradeMath.summary_stats(rows)
        self.assertEqual(stats["flats"], 2)
        self.assertEqual(stats["wins"], 0)
        self.assertEqual(stats["losses"], 0)
        self.assertEqual(stats["total_pnl_usd"], money("0.00"))
        self.assertEqual(stats["avg_r"], money("1.235"))
        self.assertEqual(stats["expectancy_usd"], money("0.00"))

    def test_drawdown_half_cent_rounds_away_from_zero(self):
        rows = [
            {"pnl_usd": "100.005", "r_multiple": "1"},
            {"pnl_usd": "-100.005", "r_multiple": "-1"},
        ]
        stats = TradeMath.summary_stats(rows)
        self.assertEqual(stats["max_drawdown_usd"], money("100.01"))
        self.assertEqual(stats["total_pnl_usd"], money("0.00"))

    def test_missing_r_is_left_out_of_the_average(self):
        rows = [
            {"pnl_usd": "10", "r_multiple": None},
            {"pnl_usd": "-4", "r_multiple": "not-a-number"},
        ]
        stats = TradeMath.summary_stats(rows)
        self.assertEqual(stats["trades"], 2)
        self.assertIsNone(stats["avg_r"])
        self.assertIsNone(stats["expectancy_r"])
        self.assertEqual(stats["total_pnl_usd"], money("6.00"))

    def test_only_wins_and_only_losses(self):
        wins = TradeMath.summary_stats([{"pnl_usd": "8", "r_multiple": "1"}])
        self.assertEqual(wins["expectancy_usd"], money("8.00"))
        self.assertEqual(wins["losses"], 0)
        losses = TradeMath.summary_stats([{"pnl_usd": "-3", "r_multiple": "-1"}])
        self.assertEqual(losses["expectancy_usd"], money("-3.00"))
        self.assertEqual(losses["win_rate"], money("0.0000"))

    def test_bad_rows(self):
        with self.assertRaisesRegex(TradeMathError, "sequence"):
            TradeMath.summary_stats("nope")
        with self.assertRaisesRegex(TradeMathError, "mapping"):
            TradeMath.summary_stats(["nope"])

    def test_rows_are_not_mutated(self):
        rows = [{"strategy": "S1", "pnl_usd": "1", "r_multiple": "1", "life": "1"}]
        before = [dict(row) for row in rows]
        TradeMath.summary_stats(rows)
        self.assertEqual(rows, before)


class TestNoBrokerImports(unittest.TestCase):
    def test_module_stays_off_the_network_and_the_broker(self):
        import trade_math

        source = Path(trade_math.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import requests", source)
        self.assertNotIn("ibkr", source.lower())
        self.assertNotIn("socket", source)
        self.assertNotIn("open(", source)


if __name__ == "__main__":
    unittest.main()
