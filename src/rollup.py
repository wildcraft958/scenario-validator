"""Per-scenario rollup rows for the root-level batch summary.

One ScenarioRow condenses a scenario's full run into the figures a reviewer needs to
triage it without opening the file: how many checks the tool decided by itself, how
trustworthy those automated verdicts are (Confidence), the Pass/Review verdict, and
an Advice line that calls out exactly what to look at. The priority is catching false
positives, so a failure on a Partially-Automated (heuristic) check is flagged for a
human to confirm.
"""
from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel

from .models import CheckResult, SummaryStats

# Confidence buckets over the decisive (PASS/FAIL) verdicts, by share that is FULLY
# automated. Anything not fully automated (heuristic "Partially Automated", or a
# judgement "Manual"-tier check that still returned a verdict) lowers it, because those
# are exactly where a false positive can hide. Tunable here on purpose - these are
# reporting thresholds, not protocol tolerances, so they stay out of config.json.
CONF_HIGH = 0.9
CONF_MED = 0.6

_ADVICE_ID_CAP = 6
_NUM_PREFIX = re.compile(r"^\d+[_\s]+")


class ScenarioRow(BaseModel):
    """One row of the root summary table (Design A: trust dashboard)."""

    batch: str = ""
    category: str = ""
    scenario: str
    total: int = 0
    automated: int = 0  # checks the tool decided itself (PASS + FAIL + NA = total - manual)
    passed: int = 0
    failed: int = 0
    manual: int = 0
    na: int = 0
    confidence: str = "n/a"  # High / Medium / Low / n/a
    verdict: str = "ERROR"  # P / R / ERROR
    advice: str = ""


class BatchSummaryMeta(BaseModel):
    """Top-box metadata for the root summary workbook."""

    root: str
    run_timestamp: str
    discovered: int
    validated: int
    skipped: int  # RoadRunner-native folders with no .xosc (never validated)
    errored: int
    checks_per_scenario: int = 0
    incompatible_dirs: list[str] = []
    error_details: list[tuple[str, str]] = []  # (relative path, error message)
    report_warnings: list[tuple[str, str]] = []  # validation OK but the report file failed to write


def _clean(name: str) -> str:
    """Drop a leading ordering prefix ('01_Batch 1' -> 'Batch 1') for display."""
    return _NUM_PREFIX.sub("", name).strip()


def _split_path(rel_path: Path) -> tuple[str, str]:
    """(batch, category) from the scenario folder's lineage: grandparent / parent.

    Depth-agnostic: a flat tree (e.g. examples/CCFtap) yields ('', ''); a batch passed
    directly as the root yields ('', '<category>').
    """
    parts = rel_path.parts
    category = _clean(parts[-2]) if len(parts) >= 2 else ""
    batch = _clean(parts[-3]) if len(parts) >= 3 else ""
    return batch, category


def _confidence(fully: int, decisive: int) -> str:
    if decisive == 0:
        return "n/a"
    ratio = fully / decisive
    if ratio >= CONF_HIGH:
        return "High"
    if ratio >= CONF_MED:
        return "Medium"
    return "Low"


def _advice(results: list[CheckResult], manual_count: int, error: str | None) -> str:
    if error:
        return f"RUN ERROR: {error} - not validated, re-run"
    fails = [r for r in results if r.status == "FAIL"]
    parts: list[str] = []
    if fails:
        ids = [
            f"{r.check_id} (heuristic - confirm)"
            if r.automation_level == "Partially Automated"
            else r.check_id
            for r in fails
        ]
        shown = ids[:_ADVICE_ID_CAP]
        more = len(ids) - len(shown)
        tail = f" +{more} more" if more > 0 else ""
        parts.append(f"Verify {len(fails)} failed: {', '.join(shown)}{tail}")
    if manual_count:
        parts.append(f"{manual_count} manual to review")
    return "; ".join(parts) if parts else "Clean - all automated checks passed"


def build_scenario_row(
    rel_path: Path,
    results: list[CheckResult] | None = None,
    stats: SummaryStats | None = None,
    error: str | None = None,
) -> ScenarioRow:
    """Condense one scenario run into a summary row. Pass `error` (and omit results/stats)
    for a scenario that crashed - it becomes an ERROR row so it is never mistaken for a pass."""
    batch, category = _split_path(rel_path)
    scenario = stats.scenario_name if stats is not None else rel_path.name

    if error is not None or stats is None or results is None:
        return ScenarioRow(
            batch=batch,
            category=category,
            scenario=scenario,
            verdict="ERROR",
            confidence="n/a",
            advice=_advice([], 0, error or "validation did not complete"),
        )

    decisive = [r for r in results if r.status in ("PASS", "FAIL")]
    fully = sum(1 for r in decisive if r.automation_level == "Fully Automated")
    verdict = "P" if (stats.failed == 0 and stats.manual == 0) else "R"

    return ScenarioRow(
        batch=batch,
        category=category,
        scenario=scenario,
        total=stats.total,
        automated=stats.total - stats.manual,
        passed=stats.passed,
        failed=stats.failed,
        manual=stats.manual,
        na=stats.na,
        confidence=_confidence(fully, len(decisive)),
        verdict=verdict,
        advice=_advice(results, stats.manual, None),
    )
