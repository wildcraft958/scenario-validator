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

# Confidence says how far a scenario's automated verdict can be trusted on its own.
# Two genuine false-result risks lower it:
#   1. A FAILURE that rests on a geometric estimate (a "Partially Automated" check that
#      FAILed) is the top false-ALARM risk - that flag may not survive HIL, so the whole
#      row drops to Low until a human confirms it. This is the signal that actually varies
#      scenario to scenario and is worth a reviewer's eye.
#   2. A low share of deterministic verdicts among the decisive ones - the more of the
#      pass/fail picture rests on estimates, the less a clean result can be trusted.
# A clean, well-validated scenario reads High even though ~1/3 of its checks are estimates:
# those estimate-based checks (impact %, turn radius, speed) are cross-checked against the
# filename ground truth, not blind guesses, so >=60% deterministic is high trust here.
# Tunable on purpose - these are reporting thresholds, not protocol tolerances, so they
# stay out of config.json.
CONF_HIGH = 0.6
CONF_MED = 0.4

_ADVICE_ID_CAP = 6
_ADVICE_REASON_CHARS = 70
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
    path: str = ""  # absolute path to the scenario folder, so a reviewer can open it directly


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


def _confidence(results: list[CheckResult]) -> str:
    decisive = [r for r in results if r.status in ("PASS", "FAIL")]
    if not decisive:
        return "n/a"
    # A flagged failure that rests on a geometric estimate may not survive HIL: treat the
    # whole row as low-trust until a human confirms it (the verdict could be a false alarm).
    if any(r.status == "FAIL" and r.automation_level == "Partially Automated" for r in decisive):
        return "Low"
    ratio = sum(1 for r in decisive if r.automation_level == "Fully Automated") / len(decisive)
    if ratio >= CONF_HIGH:
        return "High"
    if ratio >= CONF_MED:
        return "Medium"
    return "Low"


def _fail_reason(r: CheckResult) -> str:
    """Short id + the concrete failure reason, e.g. 'SC_18: VUT speed 100 ... outside [30,130]'.

    Leads with what actually failed (from the check's own comment) so a reviewer can act on the
    summary without opening the per-scenario file. Whether a failure rests on an estimate is now
    carried by the Confidence column (heuristic failure -> Low), not by a tag in the text.
    """
    short = r.check_id.removeprefix("CH_")
    reason = " ".join((r.comment or "").split())
    if len(reason) > _ADVICE_REASON_CHARS:
        reason = reason[:_ADVICE_REASON_CHARS].rsplit(" ", 1)[0] + "..."
    return f"{short}: {reason}" if reason else short


def _advice(results: list[CheckResult], manual_count: int, error: str | None) -> str:
    if error:
        return f"RUN ERROR: {error} - not validated, re-run"
    fails = [r for r in results if r.status == "FAIL"]
    parts: list[str] = []
    if fails:
        shown = [_fail_reason(r) for r in fails[:_ADVICE_ID_CAP]]
        more = len(fails) - len(shown)
        tail = f"; +{more} more" if more > 0 else ""
        parts.append("; ".join(shown) + tail)
    if manual_count:
        parts.append(f"{manual_count} to review")
    return ". ".join(parts) if parts else "All automated checks passed"


def build_scenario_row(
    rel_path: Path,
    results: list[CheckResult] | None = None,
    stats: SummaryStats | None = None,
    error: str | None = None,
    abs_path: str = "",
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
            path=abs_path,
        )

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
        confidence=_confidence(results),
        verdict=verdict,
        advice=_advice(results, stats.manual, None),
        path=abs_path,
    )
