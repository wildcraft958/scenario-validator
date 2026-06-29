"""Tests for the per-scenario rollup row builder (src/rollup.py).

These pin the trust-dashboard semantics: the Pass/Review rule, the Confidence
buckets, and the Advice text that flags heuristic failures for a human to confirm.
"""
from __future__ import annotations

from pathlib import Path

from src.models import CheckResult, SummaryStats
from src.rollup import build_scenario_row


def _result(check_id: str, status: str, level: str = "Fully Automated") -> CheckResult:
    return CheckResult(
        check_id=check_id,
        category="Scenario",
        description=check_id,
        status=status,  # type: ignore[arg-type]
        automation_level=level,
        automation_note="test",
    )


def _row(results: list[CheckResult], rel: str = "01_Batch 1/01_Car_to_Car/AEB_X"):
    stats = SummaryStats.from_results(
        results, scenario_name="AEB_X", run_timestamp="t", protocol_version="v"
    )
    return build_scenario_row(Path(rel), results=results, stats=stats)


def test_verdict_pass_requires_zero_fail_and_zero_manual():
    row = _row([_result("CH_SC_01", "PASS"), _result("CH_SC_02", "PASS")])
    assert row.verdict == "P"
    assert row.confidence == "High"
    assert row.advice == "Clean - all automated checks passed"


def test_manual_forces_review_even_with_no_failures():
    row = _row([_result("CH_SC_01", "PASS"), _result("CH_MD_06", "MANUAL_REVIEW")])
    assert row.verdict == "R"
    assert row.failed == 0
    assert "1 manual to review" in row.advice


def test_failure_forces_review_and_lists_ids():
    row = _row([_result("CH_SC_01", "PASS"), _result("CH_SC_07", "FAIL")])
    assert row.verdict == "R"
    assert row.advice.startswith("Verify 1 failed: CH_SC_07")
    assert "heuristic" not in row.advice  # fully-automated fail is not flagged heuristic


def test_heuristic_failure_is_flagged_for_confirmation():
    row = _row([_result("CH_SC_16", "FAIL", level="Partially Automated")])
    assert "CH_SC_16 (heuristic - confirm)" in row.advice


def test_confidence_high_when_all_decisive_are_fully_automated():
    row = _row([_result(f"CH_{i}", "PASS") for i in range(10)])
    assert row.confidence == "High"


def test_confidence_medium_for_mixed_tiers():
    results = [_result(f"CH_F{i}", "PASS") for i in range(7)]
    results += [_result(f"CH_P{i}", "PASS", level="Partially Automated") for i in range(3)]
    row = _row(results)  # ratio 0.7 -> Medium
    assert row.confidence == "Medium"


def test_confidence_low_when_mostly_heuristic():
    results = [_result("CH_F0", "PASS")]
    results += [_result(f"CH_P{i}", "PASS", level="Partially Automated") for i in range(4)]
    row = _row(results)  # ratio 0.2 -> Low
    assert row.confidence == "Low"


def test_confidence_na_when_no_decisive_verdicts():
    row = _row([_result("CH_MD_06", "MANUAL_REVIEW"), _result("CH_MD_07", "NA")])
    assert row.confidence == "n/a"


def test_manual_tier_decisive_lowers_confidence_not_na():
    # A "Manual"-tier check that still returned a verdict is a low-trust decisive verdict:
    # it must count in the denominator (drag confidence down), never silently vanish to n/a.
    results = [_result("CH_F0", "PASS"), _result("CH_SC_02", "PASS", level="Manual")]
    row = _row(results)
    assert row.confidence != "n/a"
    assert row.confidence == "Low"  # 1 fully / 2 decisive = 0.5 < CONF_MED


def test_error_row_is_marked_and_never_a_pass():
    row = build_scenario_row(Path("01_Batch 1/01_Car_to_Car/AEB_X"), error="ValueError: boom")
    assert row.verdict == "ERROR"
    assert row.advice.startswith("RUN ERROR: ValueError: boom")
    assert row.passed == row.failed == row.total == 0


def test_batch_and_category_parsed_from_path():
    row = _row([_result("CH_SC_01", "PASS")], rel="01_Batch 1/01_Car_to_Car/AEB_X")
    assert row.batch == "Batch 1"
    assert row.category == "Car_to_Car"


def test_flat_tree_leaves_batch_and_category_blank():
    results = [_result("CH_SC_01", "PASS")]
    stats = SummaryStats.from_results(results, scenario_name="CCFtap", run_timestamp="t", protocol_version="v")
    row = build_scenario_row(Path("CCFtap"), results=results, stats=stats)
    assert row.batch == ""
    assert row.category == ""


def test_automated_is_total_minus_manual():
    results = [_result("CH_1", "PASS"), _result("CH_2", "FAIL"),
               _result("CH_3", "NA"), _result("CH_4", "MANUAL_REVIEW")]
    row = _row(results)
    assert row.total == 4
    assert row.manual == 1
    assert row.automated == 3  # PASS + FAIL + NA


def test_advice_caps_listed_failure_ids():
    results = [_result(f"CH_F{i}", "FAIL") for i in range(9)]
    row = _row(results)
    assert "+3 more" in row.advice  # 9 fails, 6 shown
