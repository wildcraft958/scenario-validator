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
    """True when the scenario type requires EuroNCAP intersection geometry checks.

    Curved car-to-car following scenarios (CCF*, CCR*, CMR*) use a RoadRunner
    multi-connection junction element purely for lane structure on a curved road -
    that is NOT an EuroNCAP intersection and must not trigger the 8 m radius check.
    """
    if not scenario_tag or not config.junction_scenario_prefixes:
        return False
    tag_upper = scenario_tag.upper()
    return any(tag_upper.startswith(p.upper()) for p in config.junction_scenario_prefixes)


def check_rd_03(root: Any, config: Config, scenario_tag: str | None = None) -> CheckResult:
    """Junction curvature radius should be 8 m."""
    if not xodr.has_junctions(root):
        return _make("CH_RD_03", "NA", "No junctions found - check not applicable")
    if not _is_junction_scenario(scenario_tag, config):
        return _make(
            "CH_RD_03", "NA",
            "Not a junction/crossing scenario - curvature radius check does not apply"
        )

    radii = xodr.junction_curvature_radii(root)
    if not radii:
        return _make("CH_RD_03", "FAIL", "Junction present but no curvature/arc geometry found")

    target = config.junction_radius_m
    tolerance = config.junction_radius_tolerance_m
    bad = [r for r in radii if abs(r - target) > tolerance]
    if bad:
        return _make(
            "CH_RD_03",
            "FAIL",
            f"Junction radii out of spec: {[round(r, 2) for r in bad]} "
            f"(expected {target} ± {tolerance} m)",
        )
    return _make("CH_RD_03", "PASS")


def check_rd_04(root: Any, config: Config, scenario_tag: str | None = None) -> CheckResult:
    """For junction scenarios: leftmost road must start at (0,0) heading east (0°).

    Protocol requires (x=0, y=0, z=0, hdg=0) so the VUT approach road is at world origin
    and goes left-to-right (east). Tolerance: ±5° on heading to absorb floating-point noise.
    """
    if not xodr.has_junctions(root):
        return _make("CH_RD_04", "NA", "No junctions - check not applicable")
    if not _is_junction_scenario(scenario_tag, config):
        return _make("CH_RD_04", "NA", "Not a junction/crossing scenario - check not applicable")

    origin = xodr.get_leftmost_road_origin(root)
    if origin is None:
        return _make("CH_RD_04", "FAIL", "Could not determine leftmost road origin")

    x_ok = abs(origin["x"]) < 0.01
    y_ok = abs(origin["y"]) < 0.01
    hdg_deg = math.degrees(origin["hdg"]) % 360
    # heading=0° means east (left-to-right); allow ±5° for floating-point noise
    hdg_ok = hdg_deg <= 5.0 or hdg_deg >= 355.0

    issues = []
    if not x_ok or not y_ok:
        issues.append(f"position ({origin['x']:.3f}, {origin['y']:.3f}) != (0, 0)")
    if not hdg_ok:
        issues.append(f"heading {hdg_deg:.1f}° != 0° (east)")

    if not issues:
        return _make("CH_RD_04", "PASS", "Leftmost road starts at (0, 0) heading east (0°)")
    return _make("CH_RD_04", "FAIL", f"Leftmost road: {'; '.join(issues)}")


def check_rd_05(root: Any, config: Config, scenario_tag: str | None = None) -> CheckResult:
    """Junction roads must be oriented along VUT direction (entry=start, exit=end)."""
    if not xodr.has_junctions(root):
        return _make("CH_RD_05", "NA", "No junctions - check not applicable")
    if not _is_junction_scenario(scenario_tag, config):
        return _make("CH_RD_05", "NA", "Not a junction/crossing scenario - check not applicable")

    positions = xodr.get_road_start_end_positions(root)
    if not positions:
        return _make("CH_RD_05", "FAIL", "No road geometry data found")

    # Roads should have consistent headings - straight approach roads should have
    # heading close to 0 (east) or π (west) for standard left-to-right scenarios.
    headings = [p["hdg"] for p in positions]
    # Check that not all headings are perpendicular (which would suggest roads
    # are aligned N-S instead of E-W, violating entry=start/exit=end convention)
    # This is a heuristic: at least one road should have hdg within 45° of 0 or π
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
    if not xodr.has_junctions(root):
        return _make("CH_RD_06", "NA", "No junctions - check not applicable")
    if not _is_junction_scenario(scenario_tag, config):
        return _make("CH_RD_06", "NA", "Not a junction/crossing scenario - check not applicable")

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
