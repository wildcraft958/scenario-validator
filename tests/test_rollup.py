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
    assert row.advice == "All automated checks passed"


def test_manual_forces_review_even_with_no_failures():
    row = _row([_result("CH_SC_01", "PASS"), _result("CH_MD_06", "MANUAL_REVIEW")])
    assert row.verdict == "R"
    assert row.failed == 0
    assert "1 to review" in row.advice


def test_failure_forces_review_and_lists_ids():
    row = _row([_result("CH_SC_01", "PASS"), _result("CH_SC_07", "FAIL")])
    assert row.verdict == "R"
    assert row.advice.startswith("SC_07")  # short id, no "CH_" prefix
    assert "heuristic" not in row.advice  # the tag is gone; Confidence carries that signal


def test_advice_leads_with_concrete_reason_no_heuristic_tag():
    r = CheckResult(
        check_id="CH_SC_18", category="Scenario", description="VUT speed",
        status="FAIL", automation_level="Partially Automated", automation_note="t",
        comment="VUT speed = 100.0 km/h - outside protocol range [30, 130] km/h",
    )
    stats = SummaryStats.from_results([r], scenario_name="X", run_timestamp="t", protocol_version="v")
    row = build_scenario_row(Path("X"), results=[r], stats=stats)
    assert row.advice.startswith("SC_18: VUT speed = 100.0 km/h")  # leads with the concrete reason
    assert "heuristic" not in row.advice
    assert row.confidence == "Low"  # a heuristic failure is flagged here, via Confidence


def test_confidence_high_when_all_decisive_are_fully_automated():
    row = _row([_result(f"CH_{i}", "PASS") for i in range(10)])
    assert row.confidence == "High"


def test_confidence_high_at_60pct_deterministic_boundary():
    # A clean, well-validated scenario (>=60% deterministic, no heuristic failure) is High:
    # the estimate-based checks here are cross-checked against the filename, not blind guesses.
    results = [_result(f"CH_F{i}", "PASS") for i in range(6)]
    results += [_result(f"CH_P{i}", "PASS", level="Partially Automated") for i in range(4)]
    row = _row(results)  # ratio 0.6 -> High
    assert row.confidence == "High"


def test_confidence_medium_for_estimate_heavy_clean_run():
    results = [_result(f"CH_F{i}", "PASS") for i in range(4)]
    results += [_result(f"CH_P{i}", "PASS", level="Partially Automated") for i in range(6)]
    row = _row(results)  # ratio 0.4 -> Medium
    assert row.confidence == "Medium"


def test_confidence_low_when_mostly_heuristic():
    results = [_result("CH_F0", "PASS")]
    results += [_result(f"CH_P{i}", "PASS", level="Partially Automated") for i in range(4)]
    row = _row(results)  # ratio 0.2 -> Low
    assert row.confidence == "Low"


def test_confidence_na_when_no_decisive_verdicts():
    row = _row([_result("CH_MD_06", "MANUAL_REVIEW"), _result("CH_MD_07", "NA")])
    assert row.confidence == "n/a"


def test_manual_tier_decisive_counts_in_denominator_not_na():
    # A "Manual"-tier check that still returned a verdict is a decisive verdict: it must
    # count in the denominator (drag confidence down), never silently vanish to n/a.
    results = [_result("CH_F0", "PASS"), _result("CH_SC_02", "PASS", level="Manual")]
    row = _row(results)
    assert row.confidence != "n/a"
    assert row.confidence == "Medium"  # 1 fully / 2 decisive = 0.5 -> Medium


def test_heuristic_failure_forces_low_confidence():
    # A failure on a Partially-Automated (estimate) check is the top false-alarm risk:
    # the whole row drops to Low even when the deterministic share is otherwise high.
    results = [_result(f"CH_F{i}", "PASS") for i in range(9)]
    results += [_result("CH_SC_16", "FAIL", level="Partially Automated")]
    row = _row(results)  # ratio 0.9, but a heuristic failure -> Low
    assert row.confidence == "Low"


def test_deterministic_failure_keeps_confidence_high():
    # A hard, reproducible failure does not lower trust in the verdict - it IS the verdict.
    results = [_result(f"CH_F{i}", "PASS") for i in range(9)]
    results += [_result("CH_NM_03", "FAIL")]  # Fully Automated failure
    row = _row(results)
    assert row.confidence == "High"


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
