"""CH_RD_01 through CH_RD_06 - Road layout checks (from .xodr)."""
from __future__ import annotations

import logging
import math
from typing import Any

from ..models import CheckResult, Config
from ..parsers import xodr

log = logging.getLogger(__name__)

CATEGORY = "Road"

_DESCRIPTIONS = {
    "CH_RD_01": "Lane width = 3.5 m (EuroNCAP standard) and road markings present (straight alignment is visual check)",
    "CH_RD_02": "Road has >= 2 segments (trajectory coverage of both segments requires manual check)",
    "CH_RD_03": "Junction curvature radius maintained at 8 m",
    "CH_RD_04": "Junction scenarios: leftmost road starts at (0,0,0) heading east (0°) in RoadRunner coordinates",
    "CH_RD_05": "Junction road heading aligned with east/west (VUT entry/exit alignment requires manual check)",
    "CH_RD_06": "Junction lanes on main driving lane, NOT shoulder lane",
}


def _make(check_id: str, status: str, comment: str = "") -> CheckResult:
    return CheckResult(
        check_id=check_id,
        category=CATEGORY,
        description=_DESCRIPTIONS[check_id],
        status=status,  # type: ignore[arg-type]
        comment=comment,
    )


def check_rd_01(root: Any, config: Config) -> CheckResult:
    """Lane width should be 3.5 m, road markings present."""
    widths = xodr.get_lane_widths(root)
    if not widths:
        return _make("CH_RD_01", "FAIL", "No lane width elements found in .xodr")

    tolerance = config.lane_width_tolerance_m
    target = config.lane_width_m
    bad = [w for w in widths if abs(w - target) > tolerance]

    markings = xodr.get_road_markings(root)
    has_markings = bool(markings) and any(m not in ("none", "") for m in markings)

    if bad:
        return _make(
            "CH_RD_01",
            "FAIL",
            f"Lane widths out of spec: {[round(w, 3) for w in bad]} "
            f"(expected {target} ± {tolerance} m). "
            + ("" if has_markings else "Also: no road markings found."),
        )
    if not has_markings:
        return _make("CH_RD_01", "FAIL", "Lane widths OK but no road markings found")
    return _make("CH_RD_01", "PASS")


def check_rd_02(root: Any, config: Config) -> CheckResult:
    """Road must have >= 2 segments."""
    count = xodr.get_road_count(root)
    if count >= 2:
        return _make("CH_RD_02", "PASS")
    return _make("CH_RD_02", "FAIL", f"Only {count} road segment(s) found - need at least 2")


def _is_junction_scenario(scenario_tag: str | None, config: Config) -> bool:
    """True when the scenario TAG is configured as an EuroNCAP intersection type."""
    if not scenario_tag or not config.junction_scenario_prefixes:
        return False
    tag_upper = scenario_tag.upper()
    return any(tag_upper.startswith(p.upper()) for p in config.junction_scenario_prefixes)


def _junction_geometry_applies(
    root: Any, scenario_tag: str | None, config: Config
) -> tuple[bool, str]:
    """Decide whether the intersection geometry checks (RD_03-06) apply.

    Combines config and a file heuristic so detection is not brittle:
      * if there is no junction element at all -> NA
      * if the scenario tag is a configured junction type -> apply
      * else, if the .xodr junction has connecting roads that genuinely TURN
        (any arc radius <= junction_detect_max_radius_m), apply anyway - this
        auto-detects an un-configured turn/crossing scenario (the CCFtap class
        of bug) instead of silently short-circuiting to NA
      * a junction with no tight arcs (lane structure/transition only) -> NA

    Returns (applies, na_reason). na_reason is the message to show when NA.
    """
    if not xodr.has_junctions(root):
        return False, "No junctions found - check not applicable"
    if _is_junction_scenario(scenario_tag, config):
        return True, ""
    if xodr.has_turning_junction(root, config.junction_detect_max_radius_m):
        return True, ""
    return False, (
        "Junction element present but its connecting roads do not turn "
        "(lane-structure only) and the scenario tag is not a configured junction "
        "type - intersection geometry check does not apply"
    )


def _heuristic_note(scenario_tag: str | None, config: Config) -> str:
    """Hint appended when a junction was auto-detected from geometry, not config."""
    if _is_junction_scenario(scenario_tag, config):
        return ""
    return (
        " [junction auto-detected from .xodr geometry; the scenario tag is not in "
        "junction_scenario_prefixes - add it to config to make this explicit]"
    )


def check_rd_03(root: Any, config: Config, scenario_tag: str | None = None) -> CheckResult:
    """Junction curvature radius should be 8 m (kerb/corner radius).

    The 8 m spec is the junction CORNER (kerb fillet) radius set in RoadRunner.
    RoadRunner does NOT export that fillet to OpenDRIVE — the .xodr only contains
    the auto-generated connecting roads, whose <arc> radii are lane-centre path
    values (reference-line geometry), always LARGER than the kerb radius by the
    lateral lane offsets. So from the .xodr alone the kerb radius can only be
    bounded from below:
      - any connecting radius < 8 m  → junction is tighter than spec → FAIL
      - a connecting radius ≈ 8 m    → kerb-tangent arc present → PASS
      - all radii > 8 m              → consistent with an 8 m kerb → MANUAL_REVIEW
        (verify Corner Radius = 8 m in the RoadRunner scene; the VUT's driven
        Part-2 radius is independently validated by CH_SC_07).
    """
    applies, na_reason = _junction_geometry_applies(root, scenario_tag, config)
    if not applies:
        return _make("CH_RD_03", "NA", na_reason)
    hint = _heuristic_note(scenario_tag, config)

    radii = xodr.junction_curvature_radii(root)
    if not radii:
        return _make("CH_RD_03", "FAIL", f"Junction present but no curvature/arc geometry found.{hint}")

    target = config.junction_radius_m
    tolerance = config.junction_radius_tolerance_m
    rounded = sorted({round(r, 2) for r in radii})

    too_small = [r for r in rounded if r < target - tolerance]
    if too_small:
        return _make(
            "CH_RD_03",
            "FAIL",
            f"Connecting-road radii {too_small} are below the {target} m kerb radius spec — "
            f"lane-centre paths are always wider than the kerb, so the junction corner is "
            f"tighter than {target} m. Increase the Corner Radius in RoadRunner.{hint}",
        )

    if any(abs(r - target) <= tolerance for r in rounded):
        return _make(
            "CH_RD_03",
            "PASS",
            f"Connecting-road arc radius ≈ {target} m found (radii: {rounded}).{hint}",
        )

    return _make(
        "CH_RD_03",
        "MANUAL_REVIEW",
        f"Connecting-road arc radii {rounded} m are lane-centre values; RoadRunner does not "
        f"export the kerb/corner radius to OpenDRIVE. All radii are consistent with a kerb "
        f"radius ≥ {target} m — verify Corner Radius = {target} m in the RoadRunner scene. "
        f"(VUT driven Part-2 turn radius is independently validated by CH_SC_07.){hint}",
    )


def check_rd_04(root: Any, config: Config, scenario_tag: str | None = None) -> CheckResult:
    """For junction scenarios with static objects at the intersection: the leftmost road
    must start at the RoadRunner origin (0, 0, 0).

    EuroNCAP checklist (verbatim): "the start of the leftmost road coordinates should be at
    the (0,0,0) position of the RoadRunner". Only the POSITION is constrained - the road's
    compass heading is NOT part of this requirement (VUT direction is covered by CH_SC_06).
    """
    applies, na_reason = _junction_geometry_applies(root, scenario_tag, config)
    if not applies:
        return _make("CH_RD_04", "NA", na_reason)

    origin = xodr.get_leftmost_road_origin(root)
    if origin is None:
        return _make("CH_RD_04", "FAIL", "Could not determine leftmost road origin")

    x_ok = abs(origin["x"]) < 0.01
    y_ok = abs(origin["y"]) < 0.01
    if x_ok and y_ok:
        return _make("CH_RD_04", "PASS", "Leftmost road starts at the RoadRunner origin (0, 0)")
    return _make(
        "CH_RD_04",
        "FAIL",
        f"Leftmost road starts at ({origin['x']:.3f}, {origin['y']:.3f}) - must be at the "
        f"RoadRunner origin (0, 0, 0) per EuroNCAP checklist (intersection/static-object scenarios).",
    )


def check_rd_05(root: Any, config: Config, scenario_tag: str | None = None) -> CheckResult:
    """Junction roads must be oriented along VUT direction (entry=start, exit=end)."""
    applies, na_reason = _junction_geometry_applies(root, scenario_tag, config)
    if not applies:
        return _make("CH_RD_05", "NA", na_reason)

    positions = xodr.get_road_start_end_positions(root)
    if not positions:
        return _make("CH_RD_05", "FAIL", "No road geometry data found")

    # Checklist: junction roads must be oriented along the VUT's direction of travel
    # (road start = entry, road end = exit). Precise verification needs VUT-trajectory
    # correlation; as a heuristic, at least one approach road should run along an axis the
    # VUT can travel straight on (within 45 deg of an axis). RoadRunner authors axis-aligned
    # roads, so a purely diagonal road network would indicate a misaligned junction.
    headings = [p["hdg"] for p in positions]
    aligned = any(
        abs(h) < math.pi / 4 or abs(abs(h) - math.pi) < math.pi / 4
        for h in headings
    )
    if aligned:
        return _make("CH_RD_05", "PASS")
    return _make(
        "CH_RD_05",
        "FAIL",
        "Road headings suggest roads are not aligned with VUT travel direction. "
        f"Headings (rad): {[round(h, 3) for h in headings]}",
    )


def check_rd_06(root: Any, config: Config, scenario_tag: str | None = None) -> CheckResult:
    """Junction scenario lanes must NOT be on shoulder lane."""
    applies, na_reason = _junction_geometry_applies(root, scenario_tag, config)
    if not applies:
        return _make("CH_RD_06", "NA", na_reason)

    if xodr.has_shoulder_lane_at_junction(root):
        return _make(
            "CH_RD_06",
            "FAIL",
            "Shoulder lane found on junction-connecting road - this causes lane index "
            "mismatch in Model Desk. Use main driving lane only.",
        )
    return _make("CH_RD_06", "PASS")


def run_all(xodr_root: Any, config: Config, scenario_tag: str | None = None) -> list[CheckResult]:
    return [
        check_rd_01(xodr_root, config),
        check_rd_02(xodr_root, config),
        check_rd_03(xodr_root, config, scenario_tag),
        check_rd_04(xodr_root, config, scenario_tag),
        check_rd_05(xodr_root, config, scenario_tag),
        check_rd_06(xodr_root, config, scenario_tag),
    ]
