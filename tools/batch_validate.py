#!/usr/bin/env python3
"""One-command batch validation for a nested tree of exported scenario folders.

Hand it the root folder; it finds every leaf scenario folder (one that directly
contains a .xosc) no matter how deeply nested, validates each, drops the per-folder
reports in place, and writes a single root-level trust-dashboard summary so a
reviewer can triage the whole batch without opening each file.

The run never aborts on one bad scenario: a folder that raises becomes an ERROR row
in the summary and the run continues.

Usage:
    python tools/batch_validate.py <root> [--config PATH] [--summary PATH]
                                   [--no-checklist] [--no-reports] [--quiet]
"""
from __future__ import annotations

import argparse
import logging
import sys
import traceback
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.discovery import discover_scenarios  # noqa: E402
from src.reporter import write_batch_summary, write_excel, write_reference_checklist  # noqa: E402
from src.rollup import BatchSummaryMeta, ScenarioRow, build_scenario_row  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="One-command batch scenario validation + root-level summary dashboard",
    )
    parser.add_argument("root", help="Root folder to scan (nested batches handled automatically)")
    parser.add_argument("--config", default=None, help="Path to config.json / config.xlsx")
    parser.add_argument("--summary", default=None, help="Path for the root summary workbook")
    parser.add_argument("--no-checklist", action="store_true",
                        help="Do not write the per-folder reviewer checklist")
    parser.add_argument("--no-reports", action="store_true",
                        help="Skip per-folder reports; write only the root summary")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-scenario progress lines")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"ERROR: '{root}' is not a directory", file=sys.stderr)
        return 1

    config_path = Path(args.config).resolve() if args.config else None
    if config_path and not config_path.is_file():
        print(f"ERROR: config file '{config_path}' does not exist", file=sys.stderr)
        return 1

    run_ts = datetime.now()
    ts_suffix = run_ts.strftime("%Y%m%d_%H%M%S")
    summary_path = (
        Path(args.summary).resolve() if args.summary
        else root / f"Summary_Stats_{root.name}_{ts_suffix}.xlsx"
    )
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    # Keep the log beside the summary so a redirected --summary does not litter the data root.
    logging.basicConfig(
        level=logging.WARNING,
        filename=str(summary_path.parent / "batch_validate.log"),
        filemode="w",
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        force=True,
    )

    from validator import run_validation

    scenario_dirs, incompatible = discover_scenarios(root)
    if not args.quiet:
        print(f"Discovered {len(scenario_dirs)} scenario folder(s), "
              f"{len(incompatible)} skipped (no .xosc) under {root}")

    rows: list[ScenarioRow] = []
    error_details: list[tuple[str, str]] = []
    report_warnings: list[tuple[str, str]] = []
    checks_per_scenario = 0

    for i, sdir in enumerate(scenario_dirs, start=1):
        rel = sdir.relative_to(root)
        skip_rd = not any(p.suffix == ".rd" for p in sdir.iterdir() if p.is_file())
        try:
            results, stats = run_validation(sdir, config_path=config_path, skip_rd=skip_rd)
        except Exception as exc:  # noqa: BLE001 - batch must survive any single failure
            msg = f"{type(exc).__name__}: {exc}"
            error_details.append((str(rel), msg))
            logging.error("Scenario %s crashed:\n%s", rel, traceback.format_exc())
            rows.append(build_scenario_row(rel, error=msg))
            if not args.quiet:
                print(f"[{i}/{len(scenario_dirs)}] ERROR  {rel}  ({type(exc).__name__})")
            continue

        row = build_scenario_row(rel, results=results, stats=stats)
        rows.append(row)
        checks_per_scenario = max(checks_per_scenario, stats.total)

        if not args.no_reports:
            # A failed report write (most often a reviewer has the previous file open in
            # Excel -> PermissionError) must not abort the batch or lose the summary: the
            # verdict is already recorded above, so warn and carry on.
            try:
                write_excel(results, stats, sdir / f"Validation_{stats.scenario_name}_{ts_suffix}.xlsx")
                if not args.no_checklist:
                    write_reference_checklist(
                        results, stats,
                        sdir / f"Review_Checklist_{stats.scenario_name}_{ts_suffix}.xlsx",
                    )
            except Exception as exc:  # noqa: BLE001 - a report write must never kill the run
                wmsg = f"{type(exc).__name__}: {exc}"
                report_warnings.append((str(rel), wmsg))
                logging.error("Report write failed for %s:\n%s", rel, traceback.format_exc())
                if not args.quiet:
                    print(f"      ! report write failed for {rel} ({type(exc).__name__})")
        if not args.quiet:
            print(f"[{i}/{len(scenario_dirs)}] {row.verdict:<5} {rel}  "
                  f"({row.passed} pass, {row.failed} fail, {row.manual} manual, conf {row.confidence})")

    meta = BatchSummaryMeta(
        root=str(root),
        run_timestamp=run_ts.strftime("%Y-%m-%d %H:%M:%S"),
        discovered=len(scenario_dirs),
        validated=len(scenario_dirs) - len(error_details),
        skipped=len(incompatible),
        errored=len(error_details),
        checks_per_scenario=checks_per_scenario,
        incompatible_dirs=[str(p.relative_to(root)) for p in incompatible],
        error_details=error_details,
        report_warnings=report_warnings,
    )
    write_batch_summary(rows, meta, summary_path)
    print(f"\nSummary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
