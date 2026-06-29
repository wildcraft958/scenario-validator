#!/usr/bin/env python3
"""Batch validation runner for a corpus of exported scenario folders.

Walks a root directory, runs the validator on every scenario folder it finds
(a folder that directly contains at least one .xosc), writes a per-scenario
Excel report, and aggregates everything into a single markdown report.

The batch never aborts on one bad scenario: a folder that raises is recorded as
an error row and the run continues, so the aggregate always covers the whole
corpus. Paths with spaces are handled.

Usage:
    python tools/run_eval.py <root_dir> [--output DIR] [--report PATH]
                             [--config PATH] [--no-reports] [--label TEXT]
"""
from __future__ import annotations

import argparse
import logging
import sys
import traceback
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from src.discovery import discover_scenarios  # noqa: E402,F401
from src.models import Config  # noqa: E402

_STATUS_ORDER = ["PASS", "FAIL", "MANUAL_REVIEW", "NA"]
_STATUS_LABEL = {"PASS": "Yes", "FAIL": "No", "MANUAL_REVIEW": "Manual", "NA": "NA"}


def family_of(scenario_dir: Path, config: Config) -> str:
    """Longest registered prefix found in the folder/base name, else 'unknown'."""
    stem_upper = scenario_dir.name.upper()
    for prefix in sorted(
        config.naming_convention.get("valid_prefixes", []), key=len, reverse=True
    ):
        if prefix.upper() in stem_upper:
            return prefix
    return "unknown"


def _pct(part: int, whole: int) -> str:
    return f"{(part / whole * 100):.1f}%" if whole else "n/a"


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch scenario validation runner")
    parser.add_argument("root", help="Root directory to scan for scenario folders")
    parser.add_argument("--output", default=None, help="Output root for per-scenario reports")
    parser.add_argument("--report", default=None, help="Path to write the aggregate markdown report")
    parser.add_argument("--config", default=None, help="Path to config.json")
    parser.add_argument("--no-reports", action="store_true", help="Skip per-scenario Excel reports (faster)")
    parser.add_argument("--label", default="", help="Label for this run (e.g. 'Before', 'After')")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"ERROR: '{root}' is not a directory", file=sys.stderr)
        return 1

    output_root = Path(args.output).resolve() if args.output else (root.parent / "eval_reports")
    output_root.mkdir(parents=True, exist_ok=True)
    report_path = Path(args.report).resolve() if args.report else (output_root / "aggregate.md")
    config_path = Path(args.config).resolve() if args.config else None

    # Quiet the validator's own logging; keep a file trail next to the reports.
    logging.basicConfig(
        level=logging.WARNING,
        filename=str(output_root / "run_eval.log"),
        filemode="w",
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        force=True,
    )

    from validator import run_validation

    config = Config.load(config_path)

    scenario_dirs, incompatible = discover_scenarios(root)
    print(f"Discovered {len(scenario_dirs)} scenario folder(s), "
          f"{len(incompatible)} incompatible dir(s) under {root}")

    # Per-scenario records and corpus-wide accumulators.
    records: list[dict] = []
    errors: list[tuple[str, str]] = []
    per_check: dict[str, Counter] = defaultdict(Counter)
    per_category: dict[str, Counter] = defaultdict(Counter)
    per_family: dict[str, list[float]] = defaultdict(list)
    automation_counter: Counter = Counter()

    for i, sdir in enumerate(scenario_dirs, start=1):
        rel = sdir.relative_to(root)
        skip_rd = not any(p.suffix == ".rd" for p in sdir.iterdir() if p.is_file())
        try:
            results, stats = run_validation(sdir, config_path=config_path, skip_rd=skip_rd)
        except Exception as exc:  # noqa: BLE001 - batch must survive any single failure
            errors.append((str(rel), f"{type(exc).__name__}: {exc}"))
            logging.error("Scenario %s crashed:\n%s", rel, traceback.format_exc())
            print(f"[{i}/{len(scenario_dirs)}] ERROR  {rel}  ({type(exc).__name__})")
            continue

        fam = family_of(sdir, config)
        per_family[fam].append(stats.pass_rate)
        for r in results:
            per_check[r.check_id][r.status] += 1
            per_category[r.category][r.status] += 1
            level = getattr(r, "automation_level", "") or "(unset)"
            automation_counter[level] += 1

        records.append({
            "rel": str(rel),
            "family": fam,
            "total": stats.total,
            "passed": stats.passed,
            "failed": stats.failed,
            "manual": stats.manual,
            "na": stats.na,
            "pass_rate": stats.pass_rate,
            "failures": stats.critical_failures,
        })

        if not args.no_reports:
            from src.reporter import write_excel
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_dir = output_root / rel.parent
            out_dir.mkdir(parents=True, exist_ok=True)
            write_excel(results, stats, out_dir / f"Validation_{stats.scenario_name}_{ts}.xlsx")
        print(f"[{i}/{len(scenario_dirs)}] OK     {rel}  "
              f"(pass {stats.pass_rate:.0f}%, {stats.failed} fail, {stats.manual} manual)")

    _write_report(report_path, args.label, root, config_path, config, scenario_dirs,
                  incompatible, records, errors, per_check,
                  per_category, per_family, automation_counter)
    print(f"\nAggregate report: {report_path}")
    return 0


def _write_report(report_path, label, root, config_path, config, scenario_dirs,
                  incompatible, records, errors, per_check,
                  per_category, per_family, automation_counter) -> None:
    processed = len(records)
    discovered = len(scenario_dirs)
    total_results = sum(r["total"] for r in records)
    status_totals: Counter = Counter()
    for r in records:
        status_totals["PASS"] += r["passed"]
        status_totals["FAIL"] += r["failed"]
        status_totals["MANUAL_REVIEW"] += r["manual"]
        status_totals["NA"] += r["na"]
    rates = [r["pass_rate"] for r in records]
    avg_rate = sum(rates) / len(rates) if rates else 0.0

    lines: list[str] = []
    title = f"# Eval batch report{f' ({label})' if label else ''}"
    lines.append(title)
    lines.append("")
    lines.append(f"- Root: `{root}`")
    lines.append(f"- Config: `{config_path or 'config.json (default)'}`  |  Protocol: {config.protocol_version}")
    lines.append(f"- Scenarios discovered: **{discovered}**  |  processed OK: **{processed}**  |  errored: **{len(errors)}**")
    lines.append(f"- Incompatible dirs (RoadRunner-native, no .xosc/.xodr): **{len(incompatible)}**")
    lines.append(f"- Checks evaluated: **{total_results}**  |  mean automatable pass rate: **{avg_rate:.1f}%**")
    lines.append("")

    lines.append("## Verdict distribution (all checks, all scenarios)")
    lines.append("")
    lines.append("| Verdict | Count | Share |")
    lines.append("|---|---:|---:|")
    for st in _STATUS_ORDER:
        lines.append(f"| {_STATUS_LABEL[st]} ({st}) | {status_totals[st]} | {_pct(status_totals[st], total_results)} |")
    lines.append("")

    if any(k != "(unset)" for k in automation_counter):
        lines.append("## Automation coverage (check instances by trust tier)")
        lines.append("")
        lines.append("| Automation level | Count | Share |")
        lines.append("|---|---:|---:|")
        for level in ["Fully Automated", "Partially Automated", "Manual", "(unset)"]:
            if automation_counter.get(level):
                lines.append(f"| {level} | {automation_counter[level]} | {_pct(automation_counter[level], total_results)} |")
        lines.append("")

    lines.append("## Per-category verdicts")
    lines.append("")
    lines.append("| Category | Yes | No | Manual | NA |")
    lines.append("|---|---:|---:|---:|---:|")
    for cat in sorted(per_category):
        c = per_category[cat]
        lines.append(f"| {cat} | {c['PASS']} | {c['FAIL']} | {c['MANUAL_REVIEW']} | {c['NA']} |")
    lines.append("")

    lines.append("## Per-check outcomes across the corpus")
    lines.append("")
    lines.append("| Check | Yes | No | Manual | NA | Pass rate* |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for cid in sorted(per_check):
        c = per_check[cid]
        decided = c["PASS"] + c["FAIL"]
        lines.append(f"| {cid} | {c['PASS']} | {c['FAIL']} | {c['MANUAL_REVIEW']} | {c['NA']} | {_pct(c['PASS'], decided)} |")
    lines.append("")
    lines.append("\\* Pass rate = Yes / (Yes + No), ignoring Manual/NA.")
    lines.append("")

    lines.append("## Per-scenario-family summary")
    lines.append("")
    lines.append("| Family | Scenarios | Mean automatable pass rate |")
    lines.append("|---|---:|---:|")
    for fam in sorted(per_family):
        vals = per_family[fam]
        mean = sum(vals) / len(vals) if vals else 0.0
        lines.append(f"| {fam} | {len(vals)} | {mean:.1f}% |")
    lines.append("")

    if errors:
        lines.append("## Errors (scenarios that raised)")
        lines.append("")
        lines.append("| Scenario | Exception |")
        lines.append("|---|---|")
        for rel, exc in errors:
            lines.append(f"| {rel} | {exc} |")
        lines.append("")
    else:
        lines.append("## Errors")
        lines.append("")
        lines.append("None - every discovered scenario was processed without raising.")
        lines.append("")

    if incompatible:
        lines.append("## Incompatible directories")
        lines.append("")
        lines.append("These hold RoadRunner-native exports (.rrscene/.rrscenario) without the "
                     "OpenSCENARIO/OpenDRIVE (.xosc/.xodr) export the validator consumes.")
        lines.append("")
        for d in incompatible:
            rrscene = len(list(d.glob("*.rrscene")))
            lines.append(f"- `{d.relative_to(root.parent)}` - {rrscene} .rrscene export(s), no .xosc")
        lines.append("")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
