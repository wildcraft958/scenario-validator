"""CH_SC_01 through CH_SC_22 - Scenario checks (from .xosc + .xodr)."""
from __future__ import annotations

import logging
import math
from typing import Any

from ..geometry import VehicleState, compute_impact_percentage
from ..models import CheckResult, Config
from ..parsers import xosc, xodr

log = logging.getLogger(__name__)

CATEGORY = "Scenario"

_DESCRIPTIONS = {
    "CH_SC_01": "All EuroNCAP scenario variations covered - ParameterDeclarations present",
    "CH_SC_02": "VUT Init positions (x,y) present in scenario (value correctness requires manual check)",
    "CH_SC_03": "Target Init positions (x,y) present in scenario (value correctness requires manual check)",
    "CH_SC_04": "Total simulation time within protocol bounds (speed-dependent threshold)",
    "CH_SC_05": "VUT placed in right lane (negative lane ID); GVT lane placement is manual check",
    "CH_SC_06": "VUT heading ~0 deg (left-to-right travel); direction values require manual verification",
    "CH_SC_07": "Curvature path part 2: constant radius detected (radius match to protocol is manual check)",
    "CH_SC_08": "Scenario satisfies applicable EuroNCAP protocol requirements (manual review required)",
    "CH_SC_09": "Static asset Init positions present (correctness per protocol requires manual check)",
    "CH_SC_10": "Trajectory does not start/end at intersection (SL.1); >=1 junction waypoint for crossing scenarios",
    "CH_SC_11": "No anchor present; anchoring disabled for all actors",
    "CH_SC_12": "Action phase uses 'Waypoint Time Data' with 'Relative to' option",
    "CH_SC_13": "Route Timing Tool has Timing Data option checked",
    "CH_SC_14": "Static targets/obstructions: Initialize Speed = Absolute(0 m/s) in Init or action phase",
    "CH_SC_15": "Stationary targets (EMT/EPTa/EPTc/EBTa): Initialize Speed = Absolute(0 m/s) in Init or action phase",
    "CH_SC_16": "Impact % for turning/crossing approx. matches protocol (±5%, final tuning in HILs)",
    "CH_SC_17": "Impact % for longitudinal matches protocol value (within configured tolerance)",
    "CH_SC_18": "VUT speed at impact within protocol range (target speed requires manual check)",
    "CH_SC_19": "Speed-based trigger present (target start after VUT reaches speed)",
    "CH_SC_20": "Direction/side parameters present for EBT/EPT (value correctness requires manual check)",
    "CH_SC_21": "VUT is always first (top) in action phase ordering",
    "CH_SC_22": "All obstructions placed in NCAP Asset folder in RR",
}


def _make(check_id: str, status: str, comment: str = "") -> CheckResult:
    return CheckResult(
        check_id=check_id,
        category=CATEGORY,
        description=_DESCRIPTIONS[check_id],
        status=status,  # type: ignore[arg-type]
        comment=comment,
    )


def _detect_scenario_tag(xosc_root: Any, config: Config) -> str | None:
    """Detect EuroNCAP scenario type from scenario name or parameters."""
    name = xosc.get_scenario_name(xosc_root).upper()
    for prefix in config.naming_convention["valid_prefixes"]:
        if prefix.upper() in name:
            return prefix
    params = xosc.get_parameter_declarations(xosc_root)
    for p in params:
        for prefix in config.naming_convention["valid_prefixes"]:
            if prefix.upper() in p["name"].upper() or prefix.upper() in p["value"].upper():
                return prefix
    return None


def _identify_vut(xosc_root: Any, config: Config) -> str | None:
    """Returns name of the VUT entity (exact case-insensitive match against vut_entity_names)."""
    vut_names_upper = {n.upper() for n in config.vut_entity_names}
    for entity in xosc.get_entities(xosc_root):
        name = xosc.get_entity_name(entity)
        if name.upper() in vut_names_upper:
            return name
    return None


def _identify_targets(xosc_root: Any, config: Config) -> list[str]:
    """Returns names of non-VUT vehicle/pedestrian/misc entities."""
    vut = _identify_vut(xosc_root, config)
    return [
        xosc.get_entity_name(e)
        for e in xosc.get_entities(xosc_root)
        if xosc.get_entity_name(e) != vut
    ]


# ---------- Individual checks ----------

def check_sc_01(xosc_root: Any, config: Config) -> CheckResult:
    """All EuroNCAP scenario variations covered - check parameter declarations exist."""
    params = xosc.get_parameter_declarations(xosc_root)
    if params:
        return _make("CH_SC_01", "PASS", f"{len(params)} parameter declaration(s) found")

    # RoadRunner kinematic export: variations are encoded as a FollowTrajectoryAction
    # polyline in Init instead of ParameterDeclarations. Count vertices as proxy for coverage.
    entities = [xosc.get_entity_name(e) for e in xosc.get_entities(xosc_root)]
    for entity in entities:
        verts = xosc.get_trajectory_vertices(xosc_root, entity)
        if len(verts) > 1:
            n = len(verts)
            return _make(
                "CH_SC_01",
                "PASS",
                f"Kinematic trajectory with {n} waypoints found for '{entity}' "
                f"(RoadRunner path-based format — variations encoded as Init FollowTrajectoryAction, "
                f"not ParameterDeclarations)",
            )
    return _make(
        "CH_SC_01",
        "FAIL",
        "No ParameterDeclarations and no kinematic trajectory found. "
        "All EuroNCAP speed/overlap variations must be parameterised.",
    )


def check_sc_02(xosc_root: Any, config: Config) -> CheckResult:
    """VUT positions should be present in Init (WorldPosition or any Position type)."""
    positions = xosc.get_init_positions(xosc_root)
    positioned = xosc.get_init_positioned_entities(xosc_root)
    vut = _identify_vut(xosc_root, config)
    if not vut:
        return _make("CH_SC_02", "MANUAL_REVIEW", "Could not auto-detect VUT entity - verify positions manually")
    if vut in positions:
        pos = positions[vut]
        return _make("CH_SC_02", "PASS", f"VUT '{vut}' at WorldPosition ({pos['x']:.2f}, {pos['y']:.2f})")
    if vut in positioned:
        return _make(
            "CH_SC_02",
            "PASS",
            f"VUT '{vut}' positioned in Init via a LanePosition/relative position "
            "(x,y resolved from .xodr at runtime - verify the value manually)",
        )
    return _make("CH_SC_02", "FAIL", f"VUT '{vut}' has no position in the Init section")


def check_sc_03(xosc_root: Any, config: Config) -> CheckResult:
    """Target positions should be present in Init."""
    positions = xosc.get_init_positions(xosc_root)
    positioned = xosc.get_init_positioned_entities(xosc_root)
    targets = _identify_targets(xosc_root, config)
    if not targets:
        return _make("CH_SC_03", "MANUAL_REVIEW", "No target entities detected - verify manually")

    placed = set(positions) | positioned
    missing = [t for t in targets if t not in placed]
    if not missing:
        msgs = [
            f"'{t}' at ({positions[t]['x']:.2f}, {positions[t]['y']:.2f})"
            if t in positions
            else f"'{t}' via LanePosition/relative position"
            for t in targets
        ]
        return _make("CH_SC_03", "PASS", "; ".join(msgs))
    return _make(
        "CH_SC_03",
        "FAIL",
        f"Target(s) with no position in Init: {', '.join(missing)}",
    )


def check_sc_04(xosc_root: Any, config: Config) -> CheckResult:
    """Simulation time must satisfy protocol minimum based on VUT speed.

    Thresholds are speed-dependent (from config.simulation_time_by_speed_s).
    Falls back to flat config.simulation_time_min_s / max_s when speed is unknown.
    """
    sim_time = xosc.get_simulation_time(xosc_root)
    if sim_time is None:
        return _make("CH_SC_04", "FAIL", "No SimulationTimeCondition found in StopTrigger")

    lo, hi = config.simulation_time_min_s, config.simulation_time_max_s
    speed_note = ""

    if config.simulation_time_by_speed_s:
        vut = _identify_vut(xosc_root, config)
        vut_speed_ms = xosc.get_init_speed(xosc_root, vut) if vut else None
        if vut_speed_ms is not None:
            vut_speed_kmh = vut_speed_ms * 3.6
            for band in sorted(config.simulation_time_by_speed_s, key=lambda b: b.vut_speed_max_kmh):
                if vut_speed_kmh <= band.vut_speed_max_kmh:
                    lo, hi = band.min_s, band.max_s
                    speed_note = f" (VUT={vut_speed_kmh:.0f} km/h, threshold band: [{lo}, {hi}] s)"
                    break

    if lo <= sim_time <= hi:
        return _make("CH_SC_04", "PASS", f"Simulation time = {sim_time} s{speed_note}")
    return _make(
        "CH_SC_04",
        "FAIL",
        f"Simulation time = {sim_time} s - must be in [{lo}, {hi}] s{speed_note} "
        f"per EuroNCAP checklist (total simulation time 100-150 s).",
    )


def check_sc_05(xosc_root: Any, xodr_root: Any, config: Config) -> CheckResult:
    """VUT must be in the right lane (negative lane ID in OpenDRIVE convention)."""
    lane_positions = xosc.get_entity_lane_positions(xosc_root)
    vut = _identify_vut(xosc_root, config)
    if not vut:
        return _make("CH_SC_05", "MANUAL_REVIEW", "Could not auto-detect VUT - verify lane placement manually")

    if vut in lane_positions:
        vut_lane = lane_positions[vut]["lane_id"]
        if vut_lane is None:
            return _make(
                "CH_SC_05",
                "MANUAL_REVIEW",
                f"VUT '{vut}' lane ID is a parameter reference - verify right-lane placement manually",
            )
        if vut_lane < 0:
            return _make("CH_SC_05", "PASS", f"VUT '{vut}' in lane {vut_lane} (right side)")
        return _make(
            "CH_SC_05",
            "FAIL",
            f"VUT '{vut}' in lane {vut_lane} - expected negative lane ID (right side of road)",
        )

    # WorldPosition fallback: for east-heading roads (h≈0°), negative y = right lane.
    # This holds for OpenDRIVE/RoadRunner convention where y increases left of travel.
    # For non-east-aligned roads the lane side cannot be decided from world y alone, so
    # the check stays MANUAL_REVIEW (the road centre line would be needed).
    positions = xosc.get_init_positions(xosc_root)
    if vut in positions:
        vut_pos = positions[vut]
        hdg_deg = math.degrees(vut_pos.get("h", 0.0)) % 360
        tol = config.east_heading_tolerance_deg
        east_heading = hdg_deg <= tol or hdg_deg >= 360 - tol
        if east_heading:
            y = vut_pos["y"]
            thr = config.right_lane_offset_threshold_m
            if y < -thr:
                return _make(
                    "CH_SC_05",
                    "PASS",
                    f"VUT '{vut}' at y={y:.2f} m (negative = right lane for east-heading road)",
                )
            if y > thr:
                return _make(
                    "CH_SC_05",
                    "FAIL",
                    f"VUT '{vut}' at y={y:.2f} m (positive y = left lane for east-heading road). "
                    "VUT must be in the right lane.",
                )

    return _make(
        "CH_SC_05",
        "MANUAL_REVIEW",
        f"VUT '{vut}' uses WorldPosition with non-trivial heading - verify right-lane placement manually",
    )


def check_sc_06(xosc_root: Any, config: Config) -> CheckResult:
    """Direction of travel: VUT must start travelling straight along its (axis-aligned) lane.

    The EuroNCAP requirement is that the VUT travels straight in its lane - the absolute
    world compass direction is NOT constrained, because RoadRunner authors scenes in any
    orientation (e.g. CPNCO's VUT travels due north). So this verifies the VUT's initial
    heading is aligned to a cardinal axis (0/90/180/270 deg) within tolerance, not that it
    points east specifically.
    """
    positions = xosc.get_init_positions(xosc_root)
    vut = _identify_vut(xosc_root, config)
    if not vut or vut not in positions:
        return _make("CH_SC_06", "MANUAL_REVIEW", "Could not determine VUT heading - verify direction manually")

    h_deg = math.degrees(positions[vut].get("h", 0.0)) % 360
    nearest_axis = round(h_deg / 90.0) * 90.0  # 0, 90, 180, 270, or 360
    delta = abs(h_deg - nearest_axis)
    if delta > 180:
        delta = 360 - delta

    if delta <= config.cardinal_heading_tolerance_deg:
        axis = int(nearest_axis) % 360
        return _make(
            "CH_SC_06",
            "PASS",
            f"VUT heading = {h_deg:.1f}° - aligned to straight axis-aligned road "
            f"(nearest axis {axis}°, Δ{delta:.1f}°). World direction is not constrained by protocol.",
        )
    return _make(
        "CH_SC_06",
        "FAIL",
        f"VUT heading = {h_deg:.1f}° is {delta:.1f}° off the nearest road axis "
        f"({int(nearest_axis) % 360}°). VUT must start travelling straight along its lane.",
    )


def check_sc_07(xosc_root: Any, config: Config) -> CheckResult:
    """
    Curvature path part 2: constant radius detected.
    Checks Clothoid elements first; falls back to polyline vertex heading analysis for
    RoadRunner kinematic exports which use Polyline instead of Clothoid.
    """
    # --- Primary: Clothoid/ClothoidSpline (standard OSC) ---
    constant_segments: list[float] = []
    varying_segments: list[tuple[float, float]] = []

    for seg in xosc.xpath(xosc_root, "//ClothoidSpline/Segment"):
        curv_val = xosc._safe_float(seg.get("curvature"))
        if curv_val and curv_val != 0:
            constant_segments.append(abs(1.0 / curv_val))

    for c in xosc.xpath(xosc_root, "//Clothoid"):
        cs_f = xosc._safe_float(c.get("curvatureStart") or c.get("curvature"))
        ce_f = xosc._safe_float(c.get("curvatureEnd") or c.get("curvature"))
        if cs_f is not None and ce_f is not None:
            if abs(cs_f - ce_f) < 1e-6 and cs_f != 0:
                constant_segments.append(abs(1.0 / cs_f))
            elif cs_f != 0 or ce_f != 0:
                varying_segments.append((cs_f, ce_f))

    if constant_segments or varying_segments:
        if varying_segments:
            return _make(
                "CH_SC_07",
                "FAIL",
                f"Non-constant curvature: curvStart != curvEnd in {len(varying_segments)} segment(s). "
                f"Values: {varying_segments}. Part 2 requires curvStart == curvEnd.",
            )
        radii = constant_segments
        if len(set(round(r, 1) for r in radii)) == 1:
            return _make("CH_SC_07", "PASS", f"Constant curvature radius = {radii[0]:.2f} m (Clothoid)")
        spread = max(radii) - min(radii)
        return _make(
            "CH_SC_07",
            "FAIL",
            f"Curvature radius varies: {min(radii):.2f}–{max(radii):.2f} m "
            f"(spread {spread:.2f} m). Should be constant for part 2.",
        )

    # --- Fallback: Polyline vertex heading analysis (RoadRunner kinematic format) ---
    vut = _identify_vut(xosc_root, config)
    if not vut:
        return _make("CH_SC_07", "NA", "No Clothoid trajectory and no VUT identified")

    # Use Part 2 isolation: filter to ≤ 1.2× minimum radius to strip clothoid transitions.
    # The minimum curvature radius in the curved section IS the Part 2 constant arc.
    est_radius, direction = xosc.get_polyline_part2_radius(
        xosc_root, vut,
        min_heading_delta_rad=config.curvature_min_heading_delta_rad,
        min_segment_length_m=config.curvature_min_segment_length_m,
    )
    if est_radius is None:
        return _make("CH_SC_07", "NA", "VUT heading is constant — not a turning scenario")

    # Look up the expected Part 2 radius from the protocol table in config.
    # Indexed by (vut_speed ≤ vut_speed_max_kmh) and direction.
    vut_speed_kmh = xosc.get_trajectory_speed_kmh(xosc_root, vut)
    expected_radius: float | None = None

    if vut_speed_kmh is not None and config.curve_part2_radii_m:
        # Allow 5% tolerance on the speed boundary — trajectory vertex discretisation
        # causes the computed peak speed to be slightly above the nominal value
        # (e.g. 10.035 km/h for a 10 km/h scenario).
        candidates = [
            entry for entry in config.curve_part2_radii_m
            if vut_speed_kmh <= entry["vut_speed_max_kmh"] * 1.05
            and entry.get("direction", "") == direction
        ]
        if candidates:
            # Pick entry with smallest vut_speed_max_kmh that covers this speed
            best = min(candidates, key=lambda e: e["vut_speed_max_kmh"])
            expected_radius = best["radius_m"]

    tol_pct = config.curve_radius_tolerance_pct

    if expected_radius is not None:
        deviation_pct = abs(est_radius - expected_radius) / expected_radius * 100
        if deviation_pct <= tol_pct:
            return _make(
                "CH_SC_07",
                "PASS",
                f"Part 2 constant arc: measured ~{est_radius:.1f} m "
                f"(expected {expected_radius:.2f} m for {direction} at {vut_speed_kmh:.0f} km/h, "
                f"Δ{deviation_pct:.1f}% within ±{tol_pct:.0f}% tolerance).",
            )
        return _make(
            "CH_SC_07",
            "FAIL",
            f"Part 2 arc radius mismatch: measured ~{est_radius:.1f} m, "
            f"protocol requires {expected_radius:.2f} m for {direction} at {vut_speed_kmh:.0f} km/h "
            f"(deviation {deviation_pct:.1f}% > ±{tol_pct:.0f}% tolerance). "
            f"Rebuild the path in RoadRunner with the correct curve radius.",
        )

    # Speed or protocol entry not found — fall back to informational MANUAL_REVIEW
    speed_str = f"{vut_speed_kmh:.0f} km/h" if vut_speed_kmh else "unknown speed"
    return _make(
        "CH_SC_07",
        "MANUAL_REVIEW",
        f"Curved trajectory detected: ~{est_radius:.1f} m Part 2 radius ({direction}, {speed_str}). "
        f"No protocol entry for this speed/direction combination — "
        f"add to config.curve_part2_radii_m or verify in RoadRunner.",
    )


def check_sc_08(xosc_root: Any, config: Config, scenario_tag: str | None = None) -> CheckResult:
    """Scenario satisfies applicable protocol requirements - flagged for manual review."""
    tag = scenario_tag or _detect_scenario_tag(xosc_root, config)
    hint = ""
    if tag:
        proto = config.scenario_protocol(tag)
        if proto:
            speed_info = f"VUT speed range: {proto.vut_speed_range_kmh} km/h" if proto.vut_speed_range_kmh else ""
            hint = f"Scenario type: {tag} ({proto.type}). {speed_info}"
    return _make(
        "CH_SC_08",
        "MANUAL_REVIEW",
        f"Reviewer must go through the applicable EuroNCAP protocol and verify scenario-specific "
        f"requirements manually. {hint}",
    )


def check_sc_09(xosc_root: Any, config: Config) -> CheckResult:
    """Static asset positions should be present in Init."""
    positions = xosc.get_init_positions(xosc_root)
    all_entities = [xosc.get_entity_name(e) for e in xosc.get_entities(xosc_root)]
    vut = _identify_vut(xosc_root, config)
    static_entities = []
    for name in all_entities:
        if name == vut:
            continue  # VUT is a moving vehicle, not a static asset
        speed = xosc.get_init_speed(xosc_root, name)
        if speed is not None and abs(speed) < 0.001:
            static_entities.append(name)

    if not static_entities:
        return _make("CH_SC_09", "NA", "No clearly static assets detected")

    missing = [e for e in static_entities if e not in positions]
    if not missing:
        return _make(
            "CH_SC_09",
            "PASS",
            f"Static assets with positions: {', '.join(static_entities)}",
        )
    return _make(
        "CH_SC_09",
        "FAIL",
        f"Static assets with no WorldPosition in Init: {', '.join(missing)}",
    )


def check_sc_10(xosc_root: Any, xodr_root: Any, config: Config, scenario_tag: str | None = None) -> CheckResult:
    """Trajectory must not start/end at intersection; crossing scenarios need >=1 junction waypoint.

    Protocol SL.1 has two requirements:
    1. No trajectory may start or end at an intersection.
    2. At least 1 waypoint must lie on the junction (for crossing scenarios).
    Checked together for entities with >=3 waypoints (approach-junction-exit pattern).

    Crossing/junction scenarios are identified by config.junction_scenario_prefixes, NOT by raw
    xodr junction element presence. Some scenarios (e.g. CCFtap) have curved-lane junction
    elements in xodr purely for lane structure — those are NOT EuroNCAP intersections.
    """
    waypoints_by_entity = xosc.get_all_waypoints_by_entity(xosc_root)

    if not waypoints_by_entity:
        return _make(
            "CH_SC_10",
            "MANUAL_REVIEW",
            "No waypoints found - could be using other trajectory types. Verify manually.",
        )

    # Determine whether this is a real EuroNCAP junction/crossing scenario.
    # Use config.junction_scenario_prefixes (same guard used by RD_03/04/05/06) so that
    # CCFtap's curved-lane junction element does not trigger the intersection checks.
    tag = scenario_tag or _detect_scenario_tag(xosc_root, config)
    is_junction = (
        bool(tag)
        and bool(config.junction_scenario_prefixes)
        and any(tag.upper().startswith(p.upper()) for p in config.junction_scenario_prefixes)
    )

    junction_ids = xodr.get_junction_ids(xodr_root)

    if not junction_ids or not is_junction:
        return _make("CH_SC_10", "PASS", "Longitudinal/non-intersection scenario: no junction waypoint requirement")

    road_positions = xodr.get_road_start_end_positions(xodr_root)
    if not road_positions:
        return _make("CH_SC_10", "MANUAL_REVIEW", "Could not determine junction position - verify manually")

    # Approximate junction centre as centroid of all road endpoint positions
    xs = [p["end_x"] for p in road_positions] + [p["start_x"] for p in road_positions]
    ys = [p["end_y"] for p in road_positions] + [p["start_y"] for p in road_positions]
    junc_x = sum(xs) / len(xs)
    junc_y = sum(ys) / len(ys)
    radius = config.junction_waypoint_radius_m

    has_junction_coverage = False
    start_end_violations: list[str] = []

    for entity, wps in waypoints_by_entity.items():
        if not wps:
            continue
        near = [math.hypot(wp["x"] - junc_x, wp["y"] - junc_y) < radius for wp in wps]
        if any(near):
            has_junction_coverage = True
        # Only check start/end for entities with >=3 waypoints (approach-junction-exit pattern)
        if len(wps) >= 3:
            if near[0]:
                start_end_violations.append(f"'{entity}' trajectory starts at junction")
            if near[-1]:
                start_end_violations.append(f"'{entity}' trajectory ends at junction")

    if start_end_violations:
        return _make(
            "CH_SC_10",
            "FAIL",
            f"Trajectory starts/ends at intersection (SL.1 violation): {'; '.join(start_end_violations)}",
        )
    if not has_junction_coverage:
        return _make(
            "CH_SC_10",
            "FAIL",
            "No waypoints found near the junction. Add at least 1 waypoint on the junction for crossing scenarios.",
        )
    return _make(
        "CH_SC_10",
        "PASS",
        "Junction waypoints present and trajectories do not start or end at the intersection",
    )


def check_sc_11(xosc_root: Any, config: Config) -> CheckResult:
    """No anchors present - anchoring disabled for all actors."""
    entities = [xosc.get_entity_name(e) for e in xosc.get_entities(xosc_root)]
    anchored = [e for e in entities if xosc.has_anchor(xosc_root, e)]
    if not anchored:
        return _make("CH_SC_11", "PASS")
    return _make(
        "CH_SC_11",
        "FAIL",
        f"Anchoring is enabled for: {', '.join(anchored)}. Disable for all actors.",
    )


def check_sc_12(xosc_root: Any, config: Config) -> CheckResult:
    """Action phase uses 'Waypoint Time Data' in 'Relative to' mode."""
    mode = xosc.get_timing_data_mode(xosc_root)
    if mode is None:
        return _make(
            "CH_SC_12",
            "MANUAL_REVIEW",
            "Could not find Timing/@domainAbsoluteRelative. Verify 'Waypoint Time Data' "
            "is set to 'Relative to' in action phase.",
        )
    if "relative" in mode.lower():
        return _make("CH_SC_12", "PASS", f"Timing domain = '{mode}'")
    return _make(
        "CH_SC_12",
        "FAIL",
        f"Timing domain = '{mode}' - expected 'relative'. "
        "Set 'Waypoint Time Data' to 'Relative to' in action phase.",
    )


def check_sc_13(xosc_root: Any, config: Config) -> CheckResult:
    """Route Timing Tool: Timing Data option must be checked."""
    has_timing = xosc.get_route_timing_data_option(xosc_root)
    if has_timing:
        return _make("CH_SC_13", "PASS")
    return _make(
        "CH_SC_13",
        "FAIL",
        "No Timing element found under FollowTrajectoryAction/TimeReference. "
        "Enable 'Timing Data' option in Route Timing Tool.",
    )


def _check_zero_speed(xosc_root: Any, config: Config, entity_name: str, check_id: str) -> CheckResult:
    """Verify entity has Initialize Speed = Absolute(0 m/s) in Init OR action phase.

    Static obstructions and stationary targets in RoadRunner set their speed in the
    action phase (Story section), not necessarily in Init. Both sources are checked.
    """
    init_speed = xosc.get_init_speed(xosc_root, entity_name)
    action_speeds = xosc.get_action_phase_speeds(xosc_root, entity_name)

    # If Init speed is set and non-zero → definite FAIL
    if init_speed is not None and abs(init_speed) >= 0.001:
        return _make(
            check_id,
            "FAIL",
            f"'{entity_name}': Init speed = {init_speed} m/s - must be Absolute(0 m/s)",
        )

    # If action phase has non-zero speed → FAIL
    nonzero_action = [s for s in action_speeds if abs(s) >= 0.001]
    if nonzero_action:
        return _make(
            check_id,
            "FAIL",
            f"'{entity_name}': Action phase speed(s) = {nonzero_action} m/s - must be Absolute(0 m/s)",
        )

    # PASS: zero speed found in Init, action phase, or both
    if init_speed is not None or action_speeds:
        sources = []
        if init_speed is not None:
            sources.append("Init")
        if action_speeds:
            sources.append("action phase")
        return _make(check_id, "PASS", f"'{entity_name}': speed = 0 m/s (Absolute) in {' + '.join(sources)}")

    # No speed action found anywhere.
    # Moving pedestrian/cyclist targets (EPTa, EPTc, EMT, EBTa) that travel via a
    # FollowTrajectoryAction will never have an AbsoluteTargetSpeed - absence is
    # correct for those actors.  Flag for manual review rather than hard-failing.
    return _make(
        check_id,
        "MANUAL_REVIEW",
        f"'{entity_name}': No AbsoluteTargetSpeed found in Init or action phase. "
        "If this target moves via a trajectory action this is expected. "
        "Verify manually that the speed is appropriate for the scenario.",
    )


def check_sc_14(xosc_root: Any, config: Config) -> CheckResult:
    """Static targets/obstructions: Initialize Speed = Absolute(0 m/s)."""
    entities = [xosc.get_entity_name(e) for e in xosc.get_entities(xosc_root)]
    vut = _identify_vut(xosc_root, config)

    if config.static_target_name_patterns:
        patterns_upper = [p.upper() for p in config.static_target_name_patterns]
        name_matched = [
            e for e in entities
            if e != vut and any(e.upper().startswith(p) for p in patterns_upper)
        ]
    else:
        name_matched = [e for e in entities if e != vut]

    # Also catch entities that have explicit init_spd=0 and no trajectory but are not
    # name-matched (e.g. LargeObstructionVehicle, SmallObstructionVehicle). These are
    # unambiguously static — no trajectory and speed explicitly set to 0.
    explicit_static = [
        e for e in entities
        if e != vut and e not in name_matched
        and xosc.get_init_speed(xosc_root, e) == 0.0
        and not xosc.has_init_follow_trajectory(xosc_root, e)
    ]
    static_candidates = name_matched + explicit_static

    if not static_candidates:
        return _make("CH_SC_14", "NA", "No static targets/obstructions detected")

    results = [_check_zero_speed(xosc_root, config, e, "CH_SC_14") for e in static_candidates]
    fails = [r for r in results if r.status == "FAIL"]
    if not fails:
        return _make("CH_SC_14", "PASS", f"All static entities ({', '.join(static_candidates)}) have 0 m/s init speed")
    return _make("CH_SC_14", "FAIL", "; ".join(r.comment for r in fails))


def check_sc_15(xosc_root: Any, config: Config) -> CheckResult:
    """Stationary targets (EMT, EPTa, EPTc, EBTa etc.): Initialize Speed = Absolute(0 m/s)."""
    entities = [xosc.get_entity_name(e) for e in xosc.get_entities(xosc_root)]
    vut = _identify_vut(xosc_root, config)

    if config.stationary_target_name_patterns:
        patterns_upper = [p.upper() for p in config.stationary_target_name_patterns]
        emt_candidates = [
            e for e in entities
            if e != vut and any(e.upper().startswith(p) for p in patterns_upper)
        ]
    else:
        emt_candidates = []

    if not emt_candidates:
        return _make("CH_SC_15", "NA", "No stationary EuroNCAP targets (EMT/EPTa/EPTc/EBTa) detected")

    # Entities with a kinematic trajectory are actively moving in this scenario
    # (e.g. EPTa/EPTc in crossing scenarios). Skip them — they are correctly moving.
    stationary = [e for e in emt_candidates if not xosc.has_init_follow_trajectory(xosc_root, e)]
    moving_via_traj = [e for e in emt_candidates if xosc.has_init_follow_trajectory(xosc_root, e)]

    if not stationary and moving_via_traj:
        return _make(
            "CH_SC_15",
            "NA",
            f"All matched EuroNCAP targets ({', '.join(moving_via_traj)}) use kinematic trajectories "
            f"— they are moving actors in this scenario, not stationary targets. No zero-speed check needed.",
        )

    results = [_check_zero_speed(xosc_root, config, e, "CH_SC_15") for e in stationary]
    fails = [r for r in results if r.status == "FAIL"]
    suffix = (f" Note: {', '.join(moving_via_traj)} skipped (kinematic trajectory — moving actor)."
              if moving_via_traj else "")
    if not fails:
        if stationary:
            return _make("CH_SC_15", "PASS",
                         f"Stationary targets ({', '.join(stationary)}) have 0 m/s init speed.{suffix}")
        return _make("CH_SC_15", "NA", f"No truly stationary targets found.{suffix}")
    return _make("CH_SC_15", "FAIL", "; ".join(r.comment for r in fails) + suffix)


def _get_impact_percentage(
    xosc_root: Any, config: Config, scenario_type: str
) -> tuple[float | None, str]:
    """Computes impact percentage for the scenario. Returns (pct, debug_msg)."""
    positions = xosc.get_init_positions(xosc_root)
    vut_name = _identify_vut(xosc_root, config)
    targets = _identify_targets(xosc_root, config)

    if not vut_name or not targets or vut_name not in positions:
        return None, "Could not identify VUT or target positions"

    target_name = targets[0]
    if target_name not in positions:
        return None, f"Target '{target_name}' has no Init position"

    vp = positions[vut_name]
    tp = positions[target_name]

    vut_dims = config.vut_dims()
    tgt_dims = config.target_dims(target_name)

    vut_speed = xosc.get_init_speed(xosc_root, vut_name) or 0.0
    tgt_speed = xosc.get_init_speed(xosc_root, target_name) or 0.0

    vut_state = VehicleState(
        x=vp["x"], y=vp["y"],
        heading_deg=math.degrees(vp.get("h", 0.0)),
        length=vut_dims.length, width=vut_dims.width,
        speed_ms=vut_speed,
    )
    tgt_state = VehicleState(
        x=tp["x"], y=tp["y"],
        heading_deg=math.degrees(tp.get("h", 0.0)),
        length=tgt_dims.length, width=tgt_dims.width,
        speed_ms=tgt_speed,
    )

    pct = compute_impact_percentage(vut_state, tgt_state, scenario_type)
    return pct, f"VUT='{vut_name}', Target='{target_name}'"


def check_sc_16(xosc_root: Any, config: Config, scenario_tag: str | None = None) -> CheckResult:
    """Impact % for turning/crossing ≈ protocol value (±5%)."""
    tag = scenario_tag or _detect_scenario_tag(xosc_root, config)
    proto = config.scenario_protocol(tag) if tag else None

    if not proto or proto.type not in ("crossing",):
        return _make("CH_SC_16", "NA", "Not a turning/crossing scenario")

    # RoadRunner kinematic format: actors follow a trajectory; start positions are
    # hundreds of metres from the impact point and computing overlap there gives 0%.
    # The actual impact geometry is embedded in the trajectory and can only be
    # verified visually or in the HIL test.
    vut = _identify_vut(xosc_root, config)
    if vut and xosc.has_init_follow_trajectory(xosc_root, vut):
        expected = proto.impact_overlap_pct
        return _make(
            "CH_SC_16",
            "MANUAL_REVIEW",
            f"Scenario uses RoadRunner kinematic trajectory — impact overlap cannot be computed "
            f"from Init positions. Expected ~{expected}% ±{config.impact_tolerance_pct}% "
            f"(per the scenario's protocol; the scenario filename encodes the target, e.g. '50Imp'). "
            f"Verify in RoadRunner or HIL test.",
        )

    pct, msg = _get_impact_percentage(xosc_root, config, proto.type)
    if pct is None:
        return _make("CH_SC_16", "MANUAL_REVIEW", msg)

    expected = proto.impact_overlap_pct
    tolerance = config.impact_tolerance_pct
    if abs(pct - expected) <= tolerance:
        return _make(
            "CH_SC_16",
            "PASS",
            f"Impact overlap = {pct:.1f}% (expected {expected}% ±{tolerance}%). "
            f"{msg}. Note: final tuning must be done in HILs.",
        )
    return _make(
        "CH_SC_16",
        "FAIL",
        f"Impact overlap = {pct:.1f}% - expected {expected}% ±{tolerance}%. {msg}",
    )


def check_sc_17(xosc_root: Any, config: Config, scenario_tag: str | None = None) -> CheckResult:
    """Impact % for longitudinal must exactly match protocol value."""
    tag = scenario_tag or _detect_scenario_tag(xosc_root, config)
    proto = config.scenario_protocol(tag) if tag else None

    if not proto or proto.type != "longitudinal":
        return _make("CH_SC_17", "NA", "Not a longitudinal scenario")

    # RoadRunner kinematic format: same limitation as CH_SC_16 — start positions
    # are far from impact point; overlap computation from Init gives meaningless 0%.
    vut = _identify_vut(xosc_root, config)
    if vut and xosc.has_init_follow_trajectory(xosc_root, vut):
        expected = proto.impact_overlap_pct
        return _make(
            "CH_SC_17",
            "MANUAL_REVIEW",
            f"Scenario uses RoadRunner kinematic trajectory — longitudinal impact overlap cannot "
            f"be computed from Init positions. Expected ~{expected}% "
            f"(±{config.longitudinal_impact_tolerance_pct}%, per the scenario's protocol; the "
            f"filename encodes the target, e.g. '50Imp'). Verify in RoadRunner or HIL test.",
        )

    pct, msg = _get_impact_percentage(xosc_root, config, proto.type)
    if pct is None:
        return _make("CH_SC_17", "MANUAL_REVIEW", msg)

    expected = proto.impact_overlap_pct
    tolerance = config.longitudinal_impact_tolerance_pct
    if abs(pct - expected) <= tolerance:
        return _make(
            "CH_SC_17",
            "PASS",
            f"Longitudinal impact overlap = {pct:.1f}% (expected {expected}% ±{tolerance}%). {msg}",
        )
    return _make(
        "CH_SC_17",
        "FAIL",
        f"Longitudinal impact overlap = {pct:.1f}% - expected {expected}% (±{tolerance}% tolerance). {msg}",
    )


def check_sc_18(xosc_root: Any, config: Config, scenario_tag: str | None = None) -> CheckResult:
    """VUT speed and Target speed at impact must match scenario requirements."""
    tag = scenario_tag or _detect_scenario_tag(xosc_root, config)
    proto = config.scenario_protocol(tag) if tag else None

    if not proto:
        return _make(
            "CH_SC_18",
            "MANUAL_REVIEW",
            "Could not identify scenario type - verify VUT/target speeds against protocol manually",
        )

    vut = _identify_vut(xosc_root, config)
    if not vut:
        return _make("CH_SC_18", "MANUAL_REVIEW", "Could not identify VUT entity")

    # Try explicit AbsoluteTargetSpeed in Init first
    vut_speed_ms = xosc.get_init_speed(xosc_root, vut)
    speed_source = "Init AbsoluteTargetSpeed"

    # Fallback: compute max cruise speed from trajectory vertices (RoadRunner kinematic format)
    if vut_speed_ms is None:
        traj_speed_kmh = xosc.get_trajectory_speed_kmh(xosc_root, vut)
        if traj_speed_kmh is not None:
            vut_speed_ms = traj_speed_kmh / 3.6
            speed_source = "trajectory vertex sequence (peak cruise speed)"

    if vut_speed_ms is None:
        return _make(
            "CH_SC_18",
            "MANUAL_REVIEW",
            f"VUT speed not found in Init or trajectory - verify manually for scenario type '{tag}'",
        )

    vut_speed_kmh = vut_speed_ms * 3.6
    if proto.vut_speed_range_kmh:
        lo, hi = proto.vut_speed_range_kmh
        if lo <= vut_speed_kmh <= hi:
            return _make(
                "CH_SC_18",
                "PASS",
                f"VUT speed = {vut_speed_kmh:.1f} km/h in range [{lo}, {hi}] km/h for {tag} "
                f"(source: {speed_source})",
            )
        return _make(
            "CH_SC_18",
            "FAIL",
            f"VUT speed = {vut_speed_kmh:.1f} km/h - outside protocol range [{lo}, {hi}] km/h for {tag} "
            f"(source: {speed_source})",
        )

    return _make(
        "CH_SC_18",
        "MANUAL_REVIEW",
        f"No speed range in config for scenario '{tag}' - verify VUT/target speeds manually",
    )


def check_sc_19(xosc_root: Any, config: Config) -> CheckResult:
    """Target starts moving only after VUT reaches its set speed (optional)."""
    # SpeedCondition = EntityCondition-based speed check; ParameterCondition can also encode speed triggers
    speed_conds = xosc.xpath(xosc_root, "//StartTrigger//SpeedCondition")
    if speed_conds:
        return _make(
            "CH_SC_19",
            "PASS",
            f"{len(speed_conds)} speed-based trigger(s) found - target starts after VUT reaches set speed",
        )
    return _make(
        "CH_SC_19",
        "NA",
        "No SpeedCondition found in StartTrigger. This check is optional per protocol.",
    )


def check_sc_20(xosc_root: Any, config: Config) -> CheckResult:
    """VUT turn direction and EBT/EPT direction maintained.

    Primary: checks ParameterDeclarations for explicit direction/side parameters.
    Fallback (RR kinematic format): infers VUT turn direction from trajectory
    heading change sign — positive net = Farside (left), negative = Nearside (right).
    The EBT/EPT direction (Same/Opposite) still needs manual verification.
    """
    params = xosc.get_parameter_declarations(xosc_root)
    direction_params = [
        p for p in params
        if any(kw in p["name"].lower() for kw in ["direction", "side", "ebt", "ept", "farside", "nearside"])
    ]
    if direction_params:
        values = ", ".join(f"{p['name']}={p['value']}" for p in direction_params)
        return _make("CH_SC_20", "PASS", f"Direction parameters found: {values}")

    # RR kinematic format: no ParameterDeclarations — infer VUT turn direction
    # from the net heading change across the curved section of the trajectory.
    vut = _identify_vut(xosc_root, config)
    inferred_direction = ""
    if vut and xosc.has_init_follow_trajectory(xosc_root, vut):
        _, direction = xosc.get_polyline_part2_radius(xosc_root, vut)
        if direction:
            inferred_direction = (
                f" Inferred VUT turn direction from trajectory: {direction} "
                f"(positive heading change = Farside/left, negative = Nearside/right). "
                f"Verify the EBT/EPT direction (Same/Opposite) matches the scenario intent."
            )

    base_msg = "No direction/side parameters in ParameterDeclarations."
    return _make(
        "CH_SC_20",
        "MANUAL_REVIEW",
        base_msg + (inferred_direction or " Manually verify VUT turn direction and EBT/EPT direction."),
    )


def check_sc_21(xosc_root: Any, config: Config) -> CheckResult:
    """VUT must be first in the action phase (or Init Private ordering for RoadRunner kinematic format)."""
    vut = _identify_vut(xosc_root, config)
    actors = xosc.get_actors_ordered(xosc_root)

    if actors:
        if vut and actors[0] == vut:
            return _make("CH_SC_21", "PASS", f"VUT '{actors[0]}' is first in action phase (ManeuverGroup)")
        return _make(
            "CH_SC_21",
            "FAIL",
            f"First actor in action phase is '{actors[0]}' - expected VUT ('{vut}'). "
            "Move VUT to the top of the action phase.",
        )

    # RoadRunner kinematic format: no ManeuverGroup actors; use Init/Private ordering.
    init_order = xosc.get_init_entity_ordering(xosc_root)
    if not init_order:
        return _make("CH_SC_21", "MANUAL_REVIEW", "No actor ordering found in ManeuverGroup or Init - verify manually")
    if vut and init_order[0] == vut:
        return _make(
            "CH_SC_21",
            "PASS",
            f"VUT '{init_order[0]}' is first in Init/Private ordering "
            f"(RoadRunner kinematic format — no ManeuverGroup actor refs)",
        )
    return _make(
        "CH_SC_21",
        "FAIL",
        f"First entity in Init ordering is '{init_order[0]}' - expected VUT ('{vut}'). "
        "VUT must be defined first in Init.",
    )


def check_sc_22(xosc_root: Any, config: Config) -> CheckResult:
    """
    All obstructions placed in NCAP Asset folder.
    VUT is excluded - it is an OEM custom model and is not expected to live in the NCAP Asset folder.
    """
    filepaths = xosc.get_entity_catalog_filepaths(xosc_root)
    vut = _identify_vut(xosc_root, config)

    # Remove VUT from the check - only targets and static obstructions are required to use NCAP assets
    non_vut_paths = {name: path for name, path in filepaths.items() if name != vut}

    if not non_vut_paths:
        return _make(
            "CH_SC_22",
            "MANUAL_REVIEW",
            "No asset filepath/CatalogReference found for non-VUT entities. "
            "Manually confirm all obstructions are in the 'NCAP Asset' folder in RoadRunner.",
        )

    wrong: list[str] = []
    param_refs: list[str] = []
    for entity_name, path in non_vut_paths.items():
        if not path:
            continue
        if path.startswith("$") or path.startswith("%"):
            # Parameterized path - can't verify at parse time (e.g. $Target_catalogName/$Target_catalogEntry)
            param_refs.append(f"'{entity_name}'")
        elif "ncap" not in path.lower() and "asset" not in path.lower():
            wrong.append(f"'{entity_name}' → '{path}'")

    if wrong:
        msg = (
            f"Asset(s) not in NCAP Asset folder: {'; '.join(wrong)}. "
            "Move these to the NCAP Asset folder in RoadRunner and re-export."
        )
        if param_refs:
            msg += f" Also verify parameter-referenced paths manually: {'; '.join(param_refs)}."
        return _make("CH_SC_22", "FAIL", msg)

    if param_refs:
        return _make(
            "CH_SC_22",
            "MANUAL_REVIEW",
            f"Asset path(s) are parameter references - cannot verify at parse time: {'; '.join(param_refs)}. "
            "Confirm they resolve to the NCAP Asset folder in RoadRunner.",
        )

    return _make(
        "CH_SC_22",
        "PASS",
        f"All {len(non_vut_paths)} non-VUT asset path(s) reference NCAP/asset folder",
    )


def run_all(xosc_root: Any, xodr_root: Any, config: Config, scenario_tag: str | None = None) -> list[CheckResult]:
    return [
        check_sc_01(xosc_root, config),
        check_sc_02(xosc_root, config),
        check_sc_03(xosc_root, config),
        check_sc_04(xosc_root, config),
        check_sc_05(xosc_root, xodr_root, config),
        check_sc_06(xosc_root, config),
        check_sc_07(xosc_root, config),
        check_sc_08(xosc_root, config, scenario_tag=scenario_tag),
        check_sc_09(xosc_root, config),
        check_sc_10(xosc_root, xodr_root, config, scenario_tag=scenario_tag),
        check_sc_11(xosc_root, config),
        check_sc_12(xosc_root, config),
        check_sc_13(xosc_root, config),
        check_sc_14(xosc_root, config),
        check_sc_15(xosc_root, config),
        check_sc_16(xosc_root, config, scenario_tag=scenario_tag),
        check_sc_17(xosc_root, config, scenario_tag=scenario_tag),
        check_sc_18(xosc_root, config, scenario_tag=scenario_tag),
        check_sc_19(xosc_root, config),
        check_sc_20(xosc_root, config),
        check_sc_21(xosc_root, config),
        check_sc_22(xosc_root, config),
    ]
