#!/usr/bin/env python3
"""EuroNCAP RoadRunner Scenario Validator

Usage:
    python validator.py <scenario_dir> [options]

Options:
    --config PATH      Path to config.json  [default: config.json next to this script]
    --output DIR       Directory to write reports  [default: <scenario_dir>]
    --no-rd            Skip .rd Model Desk checks (if .rd file is missing)
    --quiet            Suppress console output (still logs to file)
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.models import CheckResult, SummaryStats

log = logging.getLogger(__name__)

_SCRIPT_DIR = Path(__file__).parent


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="EuroNCAP RoadRunner Scenario Validator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "scenario_dir", nargs="?", default=".",
        help="Path to the exported scenario directory (not needed with --check-config)",
    )
    parser.add_argument("--config", default=None, help="Path to config.json")
    parser.add_argument("--output", default=None, help="Output directory for reports")
    parser.add_argument("--no-rd", action="store_true", help="Skip Model Desk .rd checks")
    parser.add_argument("--quiet", action="store_true", help="Suppress console output")
    parser.add_argument(
        "--checklist", action="store_true",
        help="Also write a reviewer-checklist workbook (Review_Checklist_*.xlsx) matching the team's review format",
    )
    parser.add_argument(
        "--check-config", action="store_true",
        help="Validate the config file, print a summary of effective settings, and exit",
    )
    return parser.parse_args()


def _check_config(config_path: Path | None) -> int:
    """Load the config, print a plain-language summary, exit 0 on success / 1 on error."""
    from src.models import Config, ConfigError

    effective = config_path or (_SCRIPT_DIR / "config.json")
    try:
        config = Config.load(config_path)
    except ConfigError as exc:
        print(f"CONFIG ERROR in {effective}:\n{exc}", file=sys.stderr)
        return 1
    except FileNotFoundError:
        print(f"CONFIG ERROR: '{effective}' does not exist", file=sys.stderr)
        return 1

    print(f"Config OK: {effective}")
    print(f"  Protocol version     : {config.protocol_version}")
    print(f"  Traffic handedness   : {config.traffic_handedness}")
    print(f"  Scenarios defined    : {len(config.scenarios)} ({', '.join(sorted(config.scenarios))})")
    print(f"  Scenario prefixes    : {', '.join(config.naming_convention.get('valid_prefixes', []))}")
    print(f"  Required files       : {len(config.required_file_extensions)} extensions + "
          f"{', '.join(config.required_standalone_files)}")
    print(f"  Optional files       : {', '.join(config.optional_standalone_files) or '(none)'}")
    print(f"  VUT entity names     : {', '.join(config.vut_entity_names)}")
    print(f"  SOV entity names     : {', '.join(config.sov_entity_names)}")
    print(f"  Vehicle dimensions   : {len(config.vehicle_dimensions)} entries")
    print(f"  Sim-time speed bands : {len(config.simulation_time_by_speed_s)}")
    print(f"  Turn radii entries   : {len(config.curve_part2_radii_m)} (steady-state arc, Part 2)")
    return 0


def _resolve_file(scenario_dir: Path, extension: str) -> Path | None:
    matches = sorted(p for p in scenario_dir.iterdir() if p.is_file() and p.suffix == extension)
    if not matches:
        log.warning("No %s file found in %s", extension, scenario_dir)
        return None
    if len(matches) > 1:
        log.warning("Multiple %s files found - using %s", extension, matches[0].name)
    return matches[0]


def run_validation(
    scenario_dir: Path,
    config_path: Path | None = None,
    skip_rd: bool = False,
    cli_command: str = "",
) -> tuple[list[CheckResult], SummaryStats]:
    """Core validation runner. Returns (results, stats)."""
    from src.models import Config, SummaryStats
    from src.parsers import xosc as xosc_parser
    from src.parsers import xodr as xodr_parser
    from src.parsers import rd as rd_parser
    from src.checks import naming, road, scenario, model_desk, model_review, functional_block

    config = Config.load(config_path)
    effective_config_path = config_path or (_SCRIPT_DIR / "config.json")
    log.info("Config loaded: %s", effective_config_path.resolve())
    log.info("Files discovered: %s", ", ".join(sorted(p.name for p in scenario_dir.iterdir() if p.is_file())))

    # ---- Naming checks ----
    log.info("Running Naming checks...")
    naming_results = naming.run_all(scenario_dir, config, skip_rd=skip_rd)

    # ---- Resolve files ----
    xosc_path = _resolve_file(scenario_dir, ".xosc")
    xodr_path = _resolve_file(scenario_dir, ".xodr")
    rd_path = _resolve_file(scenario_dir, ".rd") if not skip_rd else None

    # ---- Detect scenario tag from xosc filename (used to scope junction checks) ----
    scenario_tag: str | None = None
    designed_impact_pct: float | None = None
    parsed_name = None
    if xosc_path:
        stem_upper = xosc_path.stem.upper()
        for prefix in sorted(
            config.naming_convention.get("valid_prefixes", []),
            key=len,
            reverse=True,
        ):
            if prefix.upper() in stem_upper:
                scenario_tag = prefix
                break
        # The filename's Imp token is the per-instance DESIGNED impact overlap; feed it to
        # SC_16/17 so the geometric estimate is judged against the design, not a static value.
        from src.checks.naming import parse_scenario_filename
        parsed_name = parse_scenario_filename(xosc_path.stem, config)
        designed_impact_pct = parsed_name.impact_pct if parsed_name.well_formed else None

    # ---- Road checks ----
    road_results = []
    if xodr_path:
        log.info("Running Road checks on %s...", xodr_path.name)
        try:
            xodr_root = xodr_parser.load(xodr_path)
            road_results = road.run_all(xodr_root, config)
            for result in road_results:
                result.source_file = xodr_path.name
        except Exception as exc:
            log.error("Failed to parse .xodr: %s", exc)
            from src.models import CheckResult
            road_results = [
                CheckResult(
                    check_id=f"CH_RD_0{i}",
                    category="Road",
                    description="Road check",
                    status="FAIL",
                    comment=f"Failed to parse .xodr: {exc}",
                    source_file=xodr_path.name,
                )
                for i in range(1, 7)
            ]
    else:
        from src.models import CheckResult
        road_results = [
            CheckResult(
                check_id=f"CH_RD_0{i}",
                category="Road",
                description="Road check",
                status="FAIL",
                comment=".xodr file not found",
                source_file="*.xodr",
            )
            for i in range(1, 7)
        ]

    # ---- Scenario checks ----
    scenario_results = []
    xosc_root = None
    xodr_root_for_sc = None
    if xosc_path:
        log.info("Running Scenario checks on %s...", xosc_path.name)
        try:
            xosc_root = xosc_parser.load(xosc_path)
            xodr_root_for_sc = xodr_parser.load(xodr_path) if xodr_path else None
            if xodr_root_for_sc is None:
                import io

                from lxml import etree  # type: ignore[import-untyped]
                _stub_parser = etree.XMLParser(no_network=True, resolve_entities=False, load_dtd=False)
                xodr_root_for_sc = etree.parse(io.BytesIO(b"<OpenDRIVE/>"), _stub_parser).getroot()
            scenario_results = scenario.run_all(
                xosc_root, xodr_root_for_sc, config,
                scenario_tag=scenario_tag, designed_impact_pct=designed_impact_pct,
                parsed_name=parsed_name,
            )
            for result in scenario_results:
                result.source_file = xosc_path.name
        except Exception as exc:
            log.error("Failed to run scenario checks: %s", exc)
            from src.models import CheckResult
            scenario_results = [
                CheckResult(
                    check_id=f"CH_SC_{str(i).zfill(2)}",
                    category="Scenario",
                    description="Scenario check",
                    status="FAIL",
                    comment=f"Parsing error: {exc}",
                    source_file=xosc_path.name,
                )
                for i in range(1, 23)
            ]
    else:
        from src.models import CheckResult
        scenario_results = [
            CheckResult(
                check_id=f"CH_SC_{str(i).zfill(2)}",
                category="Scenario",
                description="Scenario check",
                status="FAIL",
                comment=".xosc file not found",
                source_file="*.xosc",
            )
            for i in range(1, 23)
        ]

    # ---- CH_RD_04 entity-based precondition ----
    # The (0,0,0) leftmost-road origin rule applies only to junction scenarios that place
    # STATIC OBJECTS at the intersection (EuroNCAP checklist wording). The road check sees
    # only the .xodr and cannot know the scenario entities, so apply that precondition here:
    # with no static obstruction in the .xosc, RD_04 is not applicable -> NA.
    if xosc_root is not None:
        from src.checks.scenario import _obstruction_entity_names
        if not _obstruction_entity_names(xosc_root, config):
            from src.models import CheckResult
            road_results = [
                CheckResult(
                    check_id="CH_RD_04", category="Road", description=result.description,
                    status="NA",
                    comment="No static objects at the intersection, so the leftmost-road "
                            "(0,0,0) origin rule does not apply (CH_RD_04 covers obstruction scenarios).",
                    source_file=result.source_file,
                ) if (result.check_id == "CH_RD_04" and result.status in ("PASS", "FAIL")) else result
                for result in road_results
            ]

    # ---- Model Desk checks ----
    md_results = []
    if skip_rd:
        from src.models import CheckResult
        md_results = [
            CheckResult(
                check_id=f"CH_MD_0{i}",
                category="ModelDesk",
                description="Model Desk check",
                status="NA",
                comment="Skipped (--no-rd flag)",
                source_file="*.rd",
            )
            for i in range(1, 6)
        ]
    elif rd_path is None:
        from src.models import CheckResult
        if xodr_root_for_sc is not None:
            from src.checks.model_desk import check_md_01
            md_results = [check_md_01(xodr_root_for_sc)]
            md_results[0].source_file = xodr_path.name if xodr_path else "*.xodr"
        md_results += [
            CheckResult(
                check_id=f"CH_MD_0{i}",
                category="ModelDesk",
                description="Model Desk check",
                status="FAIL",
                comment=".rd file not found; provide the Model Desk route file or use --no-rd",
                source_file="*.rd",
            )
            for i in range(2 if md_results else 1, 6)
        ]
    elif xosc_root is None or xodr_root_for_sc is None:
        from src.models import CheckResult
        md_results = [
            CheckResult(
                check_id=f"CH_MD_0{i}",
                category="ModelDesk",
                description="Model Desk check",
                status="FAIL",
                comment="Cannot run .rd consistency checks because .xosc or .xodr parsing failed",
                source_file=rd_path.name,
            )
            for i in range(1, 6)
        ]
    else:
        log.info("Running Model Desk checks on %s...", rd_path.name)
        try:
            rd_data = rd_parser.load(rd_path)
            md_results = model_desk.run_all(rd_data, xosc_root, xodr_root_for_sc, config)
            for result in md_results:
                result.source_file = rd_path.name
        except Exception as exc:
            log.error("Failed to run Model Desk checks: %s", exc)
            from src.models import CheckResult
            md_results = [
                CheckResult(
                    check_id=f"CH_MD_0{i}",
                    category="ModelDesk",
                    description="Model Desk check",
                    status="FAIL",
                    comment=f"Parsing error: {exc}",
                    source_file=rd_path.name,
                )
                for i in range(1, 6)
            ]

    # ---- Model Review checks (CH_MR_01, CH_MR_02) ----
    mr_results = []
    if xosc_root is not None:
        log.info("Running Model Review checks...")
        try:
            mr_results = model_review.run_all(xosc_root, config)
            for result in mr_results:
                result.source_file = xosc_path.name if xosc_path else "*.xosc"
        except Exception as exc:
            log.error("Failed to run Model Review checks: %s", exc)
            from src.models import CheckResult
            mr_results = [
                CheckResult(
                    check_id=f"CH_MR_0{i}",
                    category="ModelReview",
                    description="Model Review check",
                    status="FAIL",
                    comment=f"Parsing error: {exc}",
                    source_file=xosc_path.name if xosc_path else "*.xosc",
                )
                for i in range(1, 3)
            ]
    else:
        from src.models import CheckResult
        mr_results = [
            CheckResult(
                check_id=f"CH_MR_0{i}",
                category="ModelReview",
                description="Model Review check",
                status="FAIL",
                comment=".xosc file not found",
                source_file="*.xosc",
            )
            for i in range(1, 3)
        ]

    # ---- Functional Block checks (CH_FB_01 - TA file) ----
    # Filesystem-only; runs regardless of .xosc/.xodr parse status.
    log.info("Running Functional Block checks...")
    fb_results = functional_block.run_all(scenario_dir, config)

    all_results = (
        naming_results
        + road_results
        + scenario_results
        + md_results
        + mr_results
        + fb_results
    )
    for result in all_results:
        if result.status == "FAIL" and not result.suggested_fix:
            result.suggested_fix = result.comment or "Correct the failing source data and rerun validation."

    # Determine scenario name from .rrscene filename or directory name
    rrscene_files = list(scenario_dir.glob("*.rrscene"))
    scenario_name = rrscene_files[0].stem if rrscene_files else scenario_dir.name

    run_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stats = SummaryStats.from_results(
        all_results,
        scenario_name=scenario_name,
        run_timestamp=run_ts,
        protocol_version=config.protocol_version,
        scenario_dir=str(scenario_dir),
        config_path=str(effective_config_path.resolve()),
        cli_command=cli_command,
        checklist_column_widths={int(k): v for k, v in config.checklist_column_widths.items()},
    )

    return all_results, stats


def main() -> int:
    args = _parse_args()
    scenario_dir = Path(args.scenario_dir).resolve()
    quiet = bool(args.quiet)

    def emit(message: str, *, error: bool = False) -> None:
        if not quiet:
            print(message, file=sys.stderr if error else sys.stdout)

    config_path = Path(args.config).resolve() if args.config else None
    if config_path and not config_path.is_file():
        emit(f"ERROR: config file '{config_path}' does not exist", error=True)
        return 1

    if args.check_config:
        return _check_config(config_path)

    if not scenario_dir.is_dir():
        emit(f"ERROR: '{scenario_dir}' is not a directory", error=True)
        return 1

    output_dir = Path(args.output).resolve() if args.output else scenario_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    log_path = output_dir / "validation_run.log"

    from src.reporter import setup_logging
    setup_logging(log_path, quiet=quiet)

    log.info("=" * 60)
    log.info("EuroNCAP Scenario Validator")
    log.info("Scenario directory: %s", scenario_dir)
    log.info("CLI command: %s", " ".join(sys.argv))
    log.info("=" * 60)
    log.info("Start time: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    from src.models import ConfigError

    try:
        results, stats = run_validation(
            scenario_dir,
            config_path=config_path,
            skip_rd=args.no_rd,
            cli_command=" ".join(sys.argv),
        )
    except ConfigError as exc:
        # User-facing config problem - plain message, no stack trace.
        log.error("Config error: %s", exc)
        emit(f"CONFIG ERROR:\n{exc}", error=True)
        log.info("Exit status: 1")
        return 1
    except Exception as exc:
        log.exception("Validation failed before report generation: %s", exc)
        emit(f"ERROR: validation failed before report generation: {exc}", error=True)
        log.info("Exit status: 1")
        return 1

    # ---- Write reports ----
    from src.reporter import write_excel

    ts_suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
    excel_path = output_dir / f"Validation_{stats.scenario_name}_{ts_suffix}.xlsx"

    write_excel(results, stats, excel_path)

    checklist_path = None
    if args.checklist:
        from src.reporter import write_reference_checklist
        checklist_path = output_dir / f"Review_Checklist_{stats.scenario_name}_{ts_suffix}.xlsx"
        write_reference_checklist(results, stats, checklist_path)
        log.info("Reviewer checklist written: %s", checklist_path)

    exit_code = 0 if stats.failed == 0 else 1
    log.info("Excel written: %s", excel_path)
    log.info("Exit status: %s", exit_code)

    # ---- Console summary ----
    if not quiet:
        print()
        print("=" * 60)
        print(f"  Scenario : {stats.scenario_name}")
        print(f"  Protocol : {stats.protocol_version}")
        print(f"  Total    : {stats.total}  |  Passed: {stats.passed}  |  Failed: {stats.failed}  |  Manual: {stats.manual}  |  NA: {stats.na}")
        print(f"  Automatable Pass Rate: {stats.pass_rate:.1f}%")
        if stats.critical_failures:
            print(f"  FAILURES : {', '.join(stats.critical_failures)}")
        print(f"  Report   : {excel_path}")
        if checklist_path:
            print(f"  Checklist: {checklist_path}")
        print(f"  Log      : {log_path}")
        print("=" * 60)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
