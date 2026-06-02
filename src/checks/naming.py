"""CH_NM_01, CH_NM_02, CH_NM_03 - Naming convention checks."""
from __future__ import annotations

import logging
from pathlib import Path

from ..models import CheckResult, Config

log = logging.getLogger(__name__)

CATEGORY = "Naming"


def _make(check_id: str, status: str, comment: str = "") -> CheckResult:
    descriptions = {
        "CH_NM_01": "Actor names inside scenario follow EuroNCAP convention (VUT=Ego/VUT/Vehicle, targets=GVT/EPTa/EBTa/EPTc/EMT/SOV etc.)",
        "CH_NM_02": ".rrscene base name matches .rrscenario base name",
        "CH_NM_03": "All required files present (9 extensions + TA.xml)",
    }
    return CheckResult(
        check_id=check_id,
        category=CATEGORY,
        description=descriptions[check_id],
        status=status,  # type: ignore[arg-type]
        comment=comment,
    )


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
    """Base name of .rrscene must equal base name of .rrscenario."""
    rrscene = list(scenario_dir.glob("*.rrscene"))
    rrscenario = list(scenario_dir.glob("*.rrscenario"))

    if not rrscene:
        return _make("CH_NM_02", "FAIL", "No .rrscene file found")
    if not rrscenario:
        return _make("CH_NM_02", "FAIL", "No .rrscenario file found")

    if rrscene[0].stem == rrscenario[0].stem:
        return _make("CH_NM_02", "PASS")
    return _make(
        "CH_NM_02",
        "FAIL",
        f".rrscene name '{rrscene[0].stem}' != .rrscenario name '{rrscenario[0].stem}'",
    )


def check_nm_03(scenario_dir: Path, config: Config) -> CheckResult:
    """All required files must be present with matching base names."""
    rrscene_files = list(scenario_dir.glob("*.rrscene"))
    if not rrscene_files:
        return _make("CH_NM_03", "FAIL", "No .rrscene file found - cannot determine base name")

    base = rrscene_files[0].stem
    missing: list[str] = []

    for ext in config.required_file_extensions:
        if not (scenario_dir / f"{base}{ext}").exists():
            missing.append(f"{base}{ext}")

    for standalone in config.required_standalone_files:
        if not (scenario_dir / standalone).exists():
            missing.append(standalone)

    if not missing:
        return _make("CH_NM_03", "PASS")
    return _make("CH_NM_03", "FAIL", f"Missing files: {', '.join(missing)}")


def run_all(scenario_dir: Path, config: Config) -> list[CheckResult]:
    return [
        check_nm_01(scenario_dir, config),
        check_nm_02(scenario_dir, config),
        check_nm_03(scenario_dir, config),
    ]
