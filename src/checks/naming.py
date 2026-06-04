"""CH_NM checks - naming, file discovery, and scenario directory contract."""
from __future__ import annotations

import logging
from pathlib import Path
from collections import Counter

from ..models import CheckResult, Config

log = logging.getLogger(__name__)

CATEGORY = "Naming"


def _make(check_id: str, status: str, comment: str = "") -> CheckResult:
    descriptions = {
        "CH_NM_01": "Actor names inside scenario follow EuroNCAP convention (VUT=Ego/VUT/Vehicle, targets=GVT/EPTa/EBTa/EPTc/EMT/SOV etc.)",
        "CH_NM_02": "Scenario name contains a configured EuroNCAP prefix and scenario type",
        "CH_NM_03": "All required scenario files are present",
        "CH_NM_04": "All non-TA files use one consistent base name",
        "CH_NM_05": "Scenario directory contains only valid RoadRunner/export/report extensions",
        "CH_NM_06": "No duplicate base names or case-insensitive naming risks",
        "CH_NM_07": ".rd file presence follows Model Desk mode",
    }
    return CheckResult(
        check_id=check_id,
        category=CATEGORY,
        description=descriptions[check_id],
        status=status,  # type: ignore[arg-type]
        comment=comment,
        source_file="scenario directory",
    )


def detect_scenario_tag(name: str, config: Config) -> str | None:
    """Detect configured scenario tag from a filename or scenario description."""
    upper_name = name.upper()
    scenario_keys = sorted(config.scenarios, key=len, reverse=True)
    for key in scenario_keys:
        if key.upper() in upper_name:
            return key
    for prefix in sorted(config.naming_convention.get("valid_prefixes", []), key=len, reverse=True):
        if prefix.upper() in upper_name:
            return prefix
    return None


def _scenario_files(scenario_dir: Path) -> list[Path]:
    return [p for p in scenario_dir.iterdir() if p.is_file()]


def _base_candidate_files(scenario_dir: Path, config: Config) -> list[Path]:
    required = set(config.required_file_extensions)
    return [
        p for p in _scenario_files(scenario_dir)
        if p.suffix in required and p.name not in config.required_standalone_files
    ]


def _canonical_base(scenario_dir: Path, config: Config) -> str | None:
    rrscene = sorted(scenario_dir.glob("*.rrscene"))
    if rrscene:
        return rrscene[0].stem
    candidates = _base_candidate_files(scenario_dir, config)
    if not candidates:
        return None
    counts = Counter(p.stem for p in candidates)
    return counts.most_common(1)[0][0]


def check_nm_01(scenario_dir: Path, config: Config) -> CheckResult:
    """Actor names inside the .xosc must follow EuroNCAP naming convention.

    VUT must be named one of: Ego, VUT, Vehicle (case-insensitive).
    Non-VUT actors must start with a recognised EuroNCAP target name prefix
    (GVT, EPTa, EBTa, EPTc, EMT, SOV, Vehicle2...) as defined in config.encap_actor_names.
    """
    from ..parsers import xosc as xosc_mod

    xosc_files = list(scenario_dir.glob("*.xosc"))
    if not xosc_files:
        return _make(
            "CH_NM_01",
            "MANUAL_REVIEW",
            "No .xosc file found - cannot verify actor naming convention",
        )

    try:
        root = xosc_mod.load(xosc_files[0])
    except Exception as exc:
        return _make("CH_NM_01", "MANUAL_REVIEW", f"Failed to parse .xosc: {exc}")

    entities = xosc_mod.get_entities(root)
    if not entities:
        return _make("CH_NM_01", "MANUAL_REVIEW", "No ScenarioObject entities found in .xosc")

    vut_names_upper = [n.upper() for n in config.vut_entity_names]
    allowed_upper = [n.upper() for n in config.encap_actor_names] if config.encap_actor_names else []

    vut_found = False
    wrong: list[str] = []

    for entity in entities:
        name = xosc_mod.get_entity_name(entity)
        name_upper = name.upper()
        is_vut = any(name_upper == v for v in vut_names_upper)
        if is_vut:
            vut_found = True
            continue
        # If no encap_actor_names configured, skip non-VUT name check
        if not allowed_upper:
            continue
        if not any(name_upper.startswith(a) for a in allowed_upper):
            wrong.append(name)

    if not vut_found:
        return _make(
            "CH_NM_01",
            "FAIL",
            f"No VUT entity found. VUT must be named one of: {', '.join(config.vut_entity_names)}. "
            f"Entities found: {', '.join(xosc_mod.get_entity_name(e) for e in entities)}",
        )

    if wrong:
        return _make(
            "CH_NM_01",
            "FAIL",
            f"Non-standard actor name(s): {', '.join(wrong)}. "
            f"Use EuroNCAP standard names: GVT, EPTa, EBTa, EPTc, EMT, SOV, Vehicle2, "
            f"LargeObstructionVehicle, SmallObstructionVehicle, etc.",
        )

    return _make(
        "CH_NM_01",
        "PASS",
        f"All {len(entities)} actor(s) follow EuroNCAP naming convention",
    )


def check_nm_02(scenario_dir: Path, config: Config) -> CheckResult:
    """Scenario name must contain a configured EuroNCAP prefix."""
    base = _canonical_base(scenario_dir, config) or scenario_dir.name
    tag = detect_scenario_tag(base, config)
    if not tag:
        return _make(
            "CH_NM_02",
            "FAIL",
            f"Scenario name '{base}' does not contain a configured EuroNCAP scenario prefix. "
            "Add the prefix to config.json/scenarios or rename the scenario.",
        )
    proto = config.scenario_protocol(tag)
    if proto:
        return _make("CH_NM_02", "PASS", f"Detected scenario tag '{tag}' ({proto.type})")
    return _make(
        "CH_NM_02",
        "MANUAL_REVIEW",
        f"Detected configured prefix '{tag}', but no exact scenario protocol entry matched. "
        "Verify the scenario type manually or add an exact config.json/scenarios entry.",
    )


def check_nm_03(scenario_dir: Path, config: Config, skip_rd: bool = False) -> CheckResult:
    """All required files must be present with matching base names."""
    base = _canonical_base(scenario_dir, config)
    if not base:
        return _make("CH_NM_03", "FAIL", "No scenario files found - cannot determine base name")
    missing: list[str] = []

    for ext in config.required_file_extensions:
        if ext == ".rd" and skip_rd:
            continue
        if not (scenario_dir / f"{base}{ext}").exists():
            missing.append(f"{base}{ext}")

    for standalone in config.required_standalone_files:
        if not (scenario_dir / standalone).exists():
            missing.append(standalone)

    # Report optional files (presence/absence does not affect PASS/FAIL)
    optional_files = getattr(config, "optional_standalone_files", [])
    opt_present = [f for f in optional_files if (scenario_dir / f).exists()]
    opt_absent = [f for f in optional_files if f not in opt_present]
    opt_note = ""
    if opt_present:
        opt_note += f" Optional catalog file(s) present: {', '.join(opt_present)}."
    if opt_absent:
        opt_note += f" Optional catalog file(s) absent (not required): {', '.join(opt_absent)}."

    if not missing:
        return _make("CH_NM_03", "PASS", opt_note.strip())
    return _make("CH_NM_03", "FAIL", f"Missing files: {', '.join(missing)}.{opt_note}")


def check_nm_04(scenario_dir: Path, config: Config) -> CheckResult:
    """All required non-TA files must share one base name."""
    candidates = _base_candidate_files(scenario_dir, config)
    if not candidates:
        return _make("CH_NM_04", "FAIL", "No non-TA scenario files found")

    bases = sorted({p.stem for p in candidates})
    if len(bases) == 1:
        return _make("CH_NM_04", "PASS", f"Base name '{bases[0]}' is consistent")

    by_base = {base: sorted(p.name for p in candidates if p.stem == base) for base in bases}
    details = "; ".join(f"{base}: {', '.join(names)}" for base, names in by_base.items())
    return _make(
        "CH_NM_04",
        "FAIL",
        f"Unexpected duplicate/mismatched base names found. All non-TA files must share one base name. {details}",
    )


def check_nm_05(scenario_dir: Path, config: Config) -> CheckResult:
    """Detect wrong extensions while allowing known RoadRunner auxiliary/report outputs."""
    allowed_suffixes = set(config.required_file_extensions) | {
        ".geojson",
        ".osgb",
        ".xlsx",
        ".csv",
        ".log",
    }
    wrong: list[str] = []
    case_risk: list[str] = []
    for path in _scenario_files(scenario_dir):
        if path.name in config.required_standalone_files:
            continue
        if path.suffix != path.suffix.lower():
            case_risk.append(path.name)
        if path.suffix.lower() not in allowed_suffixes:
            wrong.append(path.name)

    if wrong:
        return _make(
            "CH_NM_05",
            "FAIL",
            f"Unsupported file extension(s): {', '.join(sorted(wrong))}. "
            "Use only configured scenario files plus known RoadRunner auxiliary/report outputs.",
        )
    if case_risk:
        return _make(
            "CH_NM_05",
            "FAIL",
            f"Case-sensitive extension risk: {', '.join(sorted(case_risk))}. "
            "Use lower-case required extensions exactly.",
        )
    return _make("CH_NM_05", "PASS")


def check_nm_06(scenario_dir: Path, config: Config) -> CheckResult:
    """Detect duplicate base names and case-insensitive collisions."""
    files = _scenario_files(scenario_dir)
    lower_names = Counter(p.name.lower() for p in files)
    duplicate_names = sorted(name for name, count in lower_names.items() if count > 1)
    exact_stems = {p.stem for p in _base_candidate_files(scenario_dir, config)}
    stems_by_lower: dict[str, set[str]] = {}
    for stem in exact_stems:
        stems_by_lower.setdefault(stem.lower(), set()).add(stem)
    case_collisions = sorted(
        lower for lower, variants in stems_by_lower.items()
        if len(variants) > 1
    )

    issues = []
    if duplicate_names:
        issues.append(f"case-insensitive duplicate filenames: {', '.join(duplicate_names)}")
    if len(exact_stems) > 1:
        issues.append("multiple scenario base names detected")
    if case_collisions:
        issues.append(f"case-insensitive duplicate base names: {', '.join(case_collisions)}")

    if issues:
        return _make("CH_NM_06", "FAIL", "; ".join(issues))
    return _make("CH_NM_06", "PASS")


def check_nm_07(scenario_dir: Path, config: Config, skip_rd: bool = False) -> CheckResult:
    base = _canonical_base(scenario_dir, config)
    rd_path = scenario_dir / f"{base}.rd" if base else None
    if skip_rd:
        if rd_path and rd_path.exists():
            return _make("CH_NM_07", "PASS", ".rd present, but --no-rd was requested")
        return _make("CH_NM_07", "NA", ".rd checks skipped by --no-rd")
    if rd_path and rd_path.exists():
        return _make("CH_NM_07", "PASS", ".rd file present")
    return _make("CH_NM_07", "FAIL", ".rd file is required unless --no-rd is used")


def run_all(scenario_dir: Path, config: Config, skip_rd: bool = False) -> list[CheckResult]:
    return [
        check_nm_01(scenario_dir, config),
        check_nm_02(scenario_dir, config),
        check_nm_03(scenario_dir, config, skip_rd=skip_rd),
        check_nm_04(scenario_dir, config),
        check_nm_05(scenario_dir, config),
        check_nm_06(scenario_dir, config),
        check_nm_07(scenario_dir, config, skip_rd=skip_rd),
    ]
