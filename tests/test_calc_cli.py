"""CLI compatibility with the interim calc.py flags."""

from __future__ import annotations

import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CALC = ROOT / "calc.py"


def run_calc(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CALC), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def lines(stdout: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in stdout.splitlines():
        key, value = line.split(": ", 1)
        parsed[key] = value
    return parsed


class TestCalcCli(unittest.TestCase):
    def test_size_flags_match_the_worked_example(self):
        result = run_calc(
            "size",
            "--account",
            "2290.65",
            "--risk-pct",
            "10",
            "--entry",
            "12.50",
            "--stop",
            "12.00",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = lines(result.stdout)
        self.assertEqual(parsed["qty"], "183")
        self.assertEqual(parsed["risk_budget"], "229.07")
        self.assertEqual(parsed["risk_per_share"], "0.5000")
        self.assertEqual(parsed["actual_risk"], "91.50")
        self.assertEqual(parsed["notional"], "2287.50")
        self.assertEqual(parsed["capped_by_notional"], "True")

    def test_size_optional_max_notional_and_short_side(self):
        result = run_calc(
            "size",
            "--account",
            "10000",
            "--risk-pct",
            "1",
            "--entry",
            "50",
            "--stop",
            "51",
            "--max-notional-pct",
            "35",
            "--side",
            "short",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = lines(result.stdout)
        self.assertEqual(parsed["qty"], "70")
        self.assertEqual(parsed["capped_by_notional"], "True")

    def test_invalid_size_is_a_clear_error(self):
        result = run_calc(
            "size",
            "--account",
            "10000",
            "--risk-pct",
            "1",
            "--entry",
            "50",
            "--stop",
            "51",
            "--side",
            "long",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("stop must be below entry for a long", result.stderr)
        self.assertEqual(result.stdout, "")

        zero_risk = run_calc(
            "size",
            "--account",
            "1000",
            "--risk-pct",
            "0",
            "--entry",
            "10",
            "--stop",
            "9",
        )
        self.assertEqual(zero_risk.returncode, 1)
        self.assertIn("risk_pct must be > 0", zero_risk.stderr)

    def test_pnl_flags_and_slippage(self):
        plain = run_calc(
            "pnl",
            "--side",
            "long",
            "--qty",
            "100",
            "--entry",
            "12.50",
            "--stop",
            "12.00",
            "--exit",
            "13.40",
        )
        self.assertEqual(plain.returncode, 0, plain.stderr)
        parsed = lines(plain.stdout)
        self.assertEqual(parsed["pnl_usd"], "90.00")
        self.assertEqual(parsed["r_multiple"], "1.800")
        self.assertEqual(parsed["outcome"], "WIN")
        self.assertEqual(parsed["pnl_after_slippage"], "90.00")

        slipped = run_calc(
            "pnl",
            "--side",
            "long",
            "--qty",
            "100",
            "--entry",
            "12.50",
            "--stop",
            "12.00",
            "--exit",
            "13.40",
            "--slippage-per-share",
            "0.05",
            "--slippage-sides",
            "2",
        )
        self.assertEqual(slipped.returncode, 0, slipped.stderr)
        parsed = lines(slipped.stdout)
        self.assertEqual(parsed["slippage_risk_share"], "0.100000")
        self.assertEqual(parsed["slippage_cost_usd"], "10.00")
        self.assertEqual(parsed["pnl_after_slippage"], "80.00")
        self.assertEqual(parsed["r_after_slippage"], "1.600")

        flat = run_calc(
            "pnl",
            "--side",
            "long",
            "--qty",
            "100",
            "--entry",
            "14.30",
            "--stop",
            "14.00",
            "--exit",
            "14.30",
        )
        self.assertEqual(lines(flat.stdout)["outcome"], "FLAT")

    def test_stats_filters_and_flat_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp) / "journal.csv"
            with journal.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["strategy", "pnl_usd", "r_multiple", "life"],
                )
                writer.writeheader()
                writer.writerows(
                    [
                        {"strategy": "S1", "pnl_usd": "100", "r_multiple": "2", "life": "1"},
                        {"strategy": "S1", "pnl_usd": "-50", "r_multiple": "-1", "life": "1"},
                        {"strategy": "S1", "pnl_usd": "0", "r_multiple": "0", "life": "1"},
                        {"strategy": "TOPUP", "pnl_usd": "2000", "r_multiple": "", "life": "2"},
                        {"strategy": "S2", "pnl_usd": "30", "r_multiple": "1", "life": "2"},
                    ]
                )
            result = run_calc("stats", "--journal", str(journal))
            self.assertEqual(result.returncode, 0, result.stderr)
            parsed = lines(result.stdout)
            self.assertEqual(parsed["trades"], "4")
            self.assertEqual(parsed["wins"], "2")
            self.assertEqual(parsed["losses"], "1")
            self.assertEqual(parsed["flats"], "1")
            self.assertEqual(parsed["total_pnl_usd"], "80.00")
            self.assertEqual(parsed["win_rate"], "0.5000")

            filtered = run_calc("stats", "--journal", str(journal), "--strategy", "S1", "--life", "1")
            self.assertEqual(lines(filtered.stdout)["trades"], "3")

        missing = run_calc("stats", "--journal", str(ROOT / "no-such-journal.csv"))
        self.assertEqual(missing.returncode, 1)
        self.assertIn("journal not found", missing.stderr)

    def test_missing_flag_still_fails_in_argparse(self):
        result = run_calc("size", "--account", "1000")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--risk-pct", result.stderr)

    def test_help_lists_interim_subcommands(self):
        result = run_calc("--help")
        self.assertEqual(result.returncode, 0)
        for name in ("size", "pnl", "stats", "test"):
            self.assertIn(name, result.stdout)

    def test_test_subcommand_runs_the_math_suite(self):
        result = run_calc("test")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OK", result.stderr)


if __name__ == "__main__":
    unittest.main()
