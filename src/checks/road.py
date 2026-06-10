"""CH_RD_01 through CH_RD_06 - Road layout checks (from .xodr)."""
from __future__ import annotations

import math
from typing import Any

from ..models import CheckResult, CheckStatus, Config
from ..parsers import xodr

CATEGORY = "Road"

_DESCRIPTIONS = {
    "CH_RD_01": "Lane width = 3.5 m (EuroNCAP standard) and road markings present (straight alignment is visual check)",
    "CH_RD_02": "Road has >= 2 segments (trajectory coverage of both segments requires manual check)",
    "CH_RD_03": "Junction curvature radius maintained at 8 m",
    "CH_RD_04": "Junction scenarios: leftmost road starts at the RoadRunner origin (0,0,0) position",
    "CH_RD_05": "Junction road heading aligned with east/west (VUT entry/exit alignment requires manual check)",
    "CH_RD_06": "Junction lanes on main driving lane, NOT shoulder lane",
}


def _make(check_id: str, status: CheckStatus, comment: str = "") -> CheckResult:
    return CheckResult(
        check_id=check_id,
        category=CATEGORY,
        description=_DESCRIPTIONS[check_id],
        status=status,
        comment=comment,
    )


def check_rd_01(root: Any, config: Config) -> CheckResult:
    """Lane width per EuroNCAP Frontal v1.1 Figure 4.2, road markings present.

    Main approach lanes are lane_width_m (3.5 m). Junction side/connecting lanes may be
    junction_lane_width_min_m..lane_width_m (3.25-3.5 m), so they are graded against the wider
    band instead of being false-failed for a protocol-legal 3.25 m width.
    """
    main_w, junc_w = xodr.get_lane_widths_by_road_kind(root)
    if not main_w and not junc_w:
        return _make("CH_RD_01", "FAIL", "No lane width elements found in .xodr")

    tol = config.lane_width_tolerance_m
    target = config.lane_width_m
    junc_min = config.junction_lane_width_min_m
    bad_main = [w for w in main_w if abs(w - target) > tol]
    bad_junc = [w for w in junc_w if not (junc_min - tol <= w <= target + tol)]

    markings = xodr.get_road_markings(root)
    has_markings = bool(markings) and any(m not in ("none", "") for m in markings)

    if bad_main or bad_junc:
        parts = []
        if bad_main:
            parts.append(f"main-road lane(s) {[round(w, 3) for w in bad_main]} (expected {target} ± {tol} m)")
        if bad_junc:
            parts.append(
                f"junction connecting-lane(s) {[round(w, 3) for w in bad_junc]} "
                f"(expected {junc_min}-{target} m per Figure 4.2)"
            )
        return _make(
            "CH_RD_01",
            "FAIL",
            "Lane widths out of spec: " + "; ".join(parts) + ". "
            + ("" if has_markings else "Also: no road markings found."),
        )
    if not has_markings:
        return _make("CH_RD_01", "FAIL", "Lane widths OK but no road markings found")
    return _make("CH_RD_01", "PASS")


def check_rd_02(root: Any, config: Config) -> CheckResult:
    """Road must have >= 2 connected segments (no 'blue dot' disconnected roads)."""
    count = xodr.get_road_count(root)
    if count < 2:
        return _make("CH_RD_02", "FAIL", f"Only {count} road segment(s) found - need at least 2")

    # A raw count >= 2 can still hide a 'blue dot' road whose link references a
    # missing junction/road - it never joins the network, so the second segment is
    # not actually reachable. EuroNCAP needs both segments traversable.
    disconnected = xodr.find_disconnected_roads(root)
    if disconnected:
        return _make(
            "CH_RD_02",
            "FAIL",
            f"{count} road segment(s) found, but road(s) {sorted(disconnected)} have a missing "
            f"link connection ('blue dot' problem) - they reference a junction/road that does "
            f"not exist, so the network is not fully connected. Fix the road links in RoadRunner.",
        )
    return _make("CH_RD_02", "PASS")


def _junction_geometry_applies(root: Any, config: Config) -> tuple[bool, str]:
    """Decide whether the intersection geometry checks (RD_03-06) apply — purely from
    the .xodr, no scenario list. A junction counts as a real EuroNCAP intersection
    (turning OR straight crossing) when its incoming roads come from different
    directions; a lane-structure junction that links only parallel roads does not.

    Returns (applies, na_reason).
    """
    if not xodr.has_junctions(root):
        return False, "No junctions found - check not applicable"
    if xodr.has_intersection_junction(root, config.junction_intersection_min_spread_deg):
        return True, ""
    return False, (
        "Junction connects only parallel roads (lane structure, not an intersection) "
        "- intersection geometry check does not apply"
    )


def check_rd_03(root: Any, config: Config) -> CheckResult:
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
    applies, na_reason = _junction_geometry_applies(root, config)
    if not applies:
        return _make("CH_RD_03", "NA", na_reason)

    radii = xodr.junction_curvature_radii(root)
    if not radii:
        return _make("CH_RD_03", "FAIL", "Junction present but no curvature/arc geometry found")

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
            f"tighter than {target} m. Increase the Corner Radius in RoadRunner.",
        )

    if any(abs(r - target) <= tolerance for r in rounded):
        return _make(
            "CH_RD_03",
            "PASS",
            f"Connecting-road arc radius ≈ {target} m found (radii: {rounded}).",
        )

    smallest = min(rounded)
    return _make(
        "CH_RD_03",
        "MANUAL_REVIEW",
        f"Connecting-road arc radii {rounded} m are lane-centre paths that run OUTSIDE the kerb "
        f"fillet, so the kerb/corner radius is necessarily ≤ the smallest of these ({smallest} m); "
        f"RoadRunner does not export the kerb radius itself to OpenDRIVE. A {target} m corner "
        f"radius is consistent with this layout, and the actual driven turn radius is "
        f"independently validated by CH_SC_07. You can sign off this manual review if CH_SC_07 "
        f"passes and Corner Radius = {target} m is set in the RoadRunner scene.",
    )


def check_rd_04(root: Any, config: Config) -> CheckResult:
    """For junction scenarios with static objects at the intersection: the leftmost road
    must start at the RoadRunner origin (0, 0, 0).

    EuroNCAP checklist (verbatim): "the start of the leftmost road coordinates should be at
    the (0,0,0) position of the RoadRunner". Only the POSITION is constrained - the road's
    compass heading is NOT part of this requirement (VUT direction is covered by CH_SC_06).
    """
    applies, na_reason = _junction_geometry_applies(root, config)
    if not applies:
        return _make("CH_RD_04", "NA", na_reason)

    origin = xodr.get_leftmost_road_origin(root)
    if origin is None:
        return _make("CH_RD_04", "FAIL", "Could not determine leftmost road origin")

    tol = config.road_origin_tolerance_m
    x_ok = abs(origin["x"]) < tol
    y_ok = abs(origin["y"]) < tol
    if x_ok and y_ok:
        return _make("CH_RD_04", "PASS", "Leftmost road starts at the RoadRunner origin (0, 0)")
    return _make(
        "CH_RD_04",
        "FAIL",
        f"Leftmost road starts at ({origin['x']:.3f}, {origin['y']:.3f}) - must be at the "
        f"RoadRunner origin (0, 0, 0) per EuroNCAP checklist (intersection/static-object scenarios).",
    )


def check_rd_05(root: Any, config: Config) -> CheckResult:
    """Junction roads must be oriented along VUT direction (entry=start, exit=end)."""
    applies, na_reason = _junction_geometry_applies(root, config)
    if not applies:
        return _make("CH_RD_05", "NA", na_reason)

    positions = xodr.get_road_start_end_positions(root)
    if not positions:
        return _make("CH_RD_05", "FAIL", "No road geometry data found")

    # Checklist: junction roads must be oriented along the VUT's direction of travel
    # (road start = entry, road end = exit). RoadRunner authors intersections axis-aligned,
    # so every road should run along a cardinal axis (0/90/180/270 deg) within the configured
    # tolerance. A diagonal road misaligns the VUT entry/exit and indicates a bad junction.
    tol = config.cardinal_heading_tolerance_deg
    off_axis: list[float] = []
    for p in positions:
        deg = math.degrees(p["hdg"]) % 90.0
        dist_to_cardinal = min(deg, 90.0 - deg)
        if dist_to_cardinal > tol:
            off_axis.append(round(math.degrees(p["hdg"]) % 360.0, 1))

    if not off_axis:
        return _make("CH_RD_05", "PASS")
    return _make(
        "CH_RD_05",
        "FAIL",
        f"Junction road heading(s) {sorted(set(off_axis))} deg are not aligned with a cardinal "
        f"axis (0/90/180/270) within +/-{tol:.0f} deg - roads must run along the VUT's straight "
        f"entry/exit directions. A diagonal junction misaligns VUT entry and exit.",
    )


def check_rd_06(root: Any, config: Config) -> CheckResult:
    """Junction scenario lanes must NOT be on shoulder lane."""
    applies, na_reason = _junction_geometry_applies(root, config)
    if not applies:
        return _make("CH_RD_06", "NA", na_reason)

    bad_types = xodr.junction_nondriving_lane_types(root)
    if bad_types:
        return _make(
            "CH_RD_06",
            "FAIL",
            f"Non-driving lane type(s) {bad_types} found on junction-connecting road(s) - "
            "this causes a lane-index mismatch in Model Desk. Junction lanes must be on the "
            "main driving lane only (the structural 'none' reference lane is allowed).",
        )
    return _make("CH_RD_06", "PASS")


def run_all(xodr_root: Any, config: Config) -> list[CheckResult]:
    return [
        check_rd_01(xodr_root, config),
        check_rd_02(xodr_root, config),
        check_rd_03(xodr_root, config),
        check_rd_04(xodr_root, config),
        check_rd_05(xodr_root, config),
        check_rd_06(xodr_root, config),
    ]
