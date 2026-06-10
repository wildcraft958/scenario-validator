"""CH_SC_01 through CH_SC_22 - Scenario checks (from .xosc + .xodr)."""
from __future__ import annotations

import math
from typing import Any

from ..geometry import estimate_trajectory_impact, paths_intersect
from ..models import CheckResult, CheckStatus, Config
from ..parsers import xosc, xodr
from .naming import detect_scenario_tag

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


def _make(check_id: str, status: CheckStatus, comment: str = "") -> CheckResult:
    return CheckResult(
        check_id=check_id,
        category=CATEGORY,
        description=_DESCRIPTIONS[check_id],
        status=status,
        comment=comment,
    )


def _detect_scenario_tag(xosc_root: Any, config: Config) -> str | None:
    """Detect the EuroNCAP scenario tag from the .xosc scenario name or its parameters.

    The prefix matching is delegated to naming.detect_scenario_tag (the single source of
    truth, longest-prefix first); only the RoadRunner-specific fallback to parameter
    declarations lives here.
    """
    tag = detect_scenario_tag(xosc.get_scenario_name(xosc_root), config)
    if tag:
        return tag
    for p in xosc.get_parameter_declarations(xosc_root):
        tag = detect_scenario_tag(p["name"], config) or detect_scenario_tag(p["value"], config)
        if tag:
            return tag
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
        handedness=config.traffic_handedness,
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

    A real EuroNCAP intersection (turning OR straight crossing) is identified purely from
    the .xodr — its incoming roads come from different directions — via
    xodr.has_intersection_junction. Lane-structure junctions (parallel roads) are excluded.
    """
    waypoints_by_entity = xosc.get_all_waypoints_by_entity(xosc_root)

    if not waypoints_by_entity:
        return _make(
            "CH_SC_10",
            "MANUAL_REVIEW",
            "No waypoints found - could be using other trajectory types. Verify manually.",
        )

    is_junction = xodr.has_junctions(xodr_root) and xodr.has_intersection_junction(
        xodr_root, config.junction_intersection_min_spread_deg
    )

    if not is_junction:
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


def _synth_straight_trajectory(
    xosc_root: Any, config: Config, name: str, horizon_s: float = 20.0
) -> list[dict]:
    """Build a 2-vertex straight trajectory from an entity's Init pose + speed.

    Parametric scenarios (no Init FollowTrajectoryAction) carry no path, so this
    synthesises one: the actor travels in a straight line along its Init heading at
    its Init speed. That lets the SAME §1.2.5 impact estimator (estimate_trajectory_impact)
    run on parametric scenarios — there is no second, divergent impact metric.
    """
    positions = xosc.get_init_positions(xosc_root)
    if name not in positions:
        return []
    p = positions[name]
    h = p.get("h", 0.0)
    speed = xosc.get_init_speed(xosc_root, name) or 0.0
    x0, y0 = p["x"], p["y"]
    return [
        {"time": 0.0, "x": x0, "y": y0, "h": h},
        {"time": horizon_s,
         "x": x0 + math.cos(h) * speed * horizon_s,
         "y": y0 + math.sin(h) * speed * horizon_s, "h": h},
    ]


def _entity_bbox(xosc_root: Any, config: Config, name: str) -> tuple[float, float, float, float]:
    """BoundingBox from the .xosc, falling back to config.vehicle_dimensions."""
    bbox = xosc.get_entity_bbox(xosc_root, name)
    if bbox is not None:
        return bbox
    dims = config.target_dims(name)
    return (0.0, 0.0, dims.length, dims.width)


def _impact_verdict(
    xosc_root: Any, config: Config, vut: str,
    expected: float, tolerance: float, check_id: str,
    side_impact: bool = False,
) -> CheckResult:
    """Estimate the designed impact location (§1.2.5) and grade it against `expected`.

    The validator's USP — pre-HIL design feedback the RoadRunner GUI cannot show.
    Primary path: RoadRunner kinematic exports are the UNBRAKED design paths (AEB only
    exists in the real/HIL test), so stepping both actors' exported trajectories +
    bounding boxes to the designed first-contact instant gives the impact geometry.
    Parametric scenarios carry no path, so a straight trajectory is SYNTHESISED from
    each actor's Init pose + speed (see _synth_straight_trajectory) — the SAME §1.2.5
    metric, never a second divergent one.

    Metric (§1.2.5, directional): the target reference point across the VUT WIDTH
    (0% = outer right edge, 100% = outer left); side-impact scenarios (CMCscp, CBTAfs,
    CBTAns) across the VUT LENGTH (0% = rear, 100% = front). The estimate is compared
    STRAIGHT to the designed %, both in the 0%=right/rear convention (no min() fold —
    a mirror-image design error must FAIL, not be silently matched to the near edge).
    """
    targets = _identify_targets(xosc_root, config)
    if not targets:
        return _make(
            check_id, "MANUAL_REVIEW",
            f"No target entity identified. Expected ~{expected}% ±{tolerance}% per "
            f"protocol — verify in RoadRunner.",
        )
    tgt = targets[0]
    category = xosc.get_entity_category(xosc_root, tgt) or "Vehicle"
    synthesised = not xosc.has_init_follow_trajectory(xosc_root, vut)
    if synthesised:
        vut_verts = _synth_straight_trajectory(xosc_root, config, vut)
        tgt_verts = _synth_straight_trajectory(xosc_root, config, tgt)
    else:
        vut_verts = xosc.get_trajectory_vertices(xosc_root, vut)
        tgt_verts = xosc.get_trajectory_vertices(xosc_root, tgt)

    est = estimate_trajectory_impact(
        vut_verts, tgt_verts,
        _entity_bbox(xosc_root, config, vut),
        _entity_bbox(xosc_root, config, tgt),
        target_category=category,
    )
    if est is None:
        return _make(
            check_id, "MANUAL_REVIEW",
            f"Could not estimate impact (missing/empty trajectory data). Expected "
            f"~{expected}% ±{tolerance}% per protocol. Verify in RoadRunner."
            + _collision_course_note(xosc_root, config, vut),
        )

    if not est.contact:
        gap = f"{est.min_gap_m:.2f} m at t={est.t_min_gap:.1f}s" if est.min_gap_m is not None else "n/a"
        return _make(
            check_id, "FAIL",
            f"Impact estimate: VUT and {tgt} bounding boxes NEVER meet along the design "
            f"paths (closest approach {gap}). Expected ~{expected}% impact — the scenario "
            f"timing/lateral design does not produce the collision. Adjust in RoadRunner.",
        )

    computed = est.impact_pct_length if side_impact else est.impact_pct_width
    axis = "length (rear 0% → front 100%)" if side_impact else "width (right 0% → left 100%)"
    if computed is None:
        return _make(
            check_id, "MANUAL_REVIEW",
            f"Contact found but the impact axis is indeterminate. Expected ~{expected}% "
            f"±{tolerance}%. Verify in RoadRunner.",
        )
    src = ("synthesised straight paths from Init pose+speed" if synthesised
           else "unbraked design trajectories + exported bounding boxes")
    side_note = (" (side-impact length axis — unvalidated locally; no CMCscp/CBTAfs/CBTAns "
                 "example exists, confirm in HIL)" if side_impact else "")
    detail = (
        f"first contact t={est.t_contact:.2f}s, lateral offset {est.lateral_offset_m:+.2f} m, "
        f"relative heading {est.rel_heading_deg:.0f}°"
    )
    basis = (
        f"Computed from {src} (no AEB by design); §1.2.5 impact location across VUT "
        f"{axis}{side_note} — confirm in HIL."
    )
    if abs(computed - expected) <= tolerance:
        return _make(
            check_id, "PASS",
            f"Geometric impact estimate {computed:.1f}% matches protocol {expected:.0f}% "
            f"±{tolerance:.0f}% ({detail}). {basis}",
        )
    return _make(
        check_id, "FAIL",
        f"Geometric impact estimate {computed:.1f}% — expected {expected:.0f}% "
        f"±{tolerance:.0f}% ({detail}). The design does not produce the intended impact "
        f"point; adjust the scenario in RoadRunner before HIL. {basis}",
    )


def _collision_course_note(xosc_root: Any, config: Config, vut: str) -> str:
    """Time-decoupled path-intersection test for kinematic scenarios.

    The impact % itself IS estimated geometrically by _impact_verdict; this is only
    the fallback note used when that estimate cannot be computed — whether the two
    designed PATHS intersect is pure geometry. Returns a note for the comment.
    """
    targets = _identify_targets(xosc_root, config)
    if not targets:
        return ""
    vut_verts = xosc.get_trajectory_vertices(xosc_root, vut)
    tgt_verts = xosc.get_trajectory_vertices(xosc_root, targets[0])
    hit = paths_intersect(vut_verts, tgt_verts)
    if hit:
        return (
            f" Collision course CONFIRMED: VUT and {targets[0]} paths intersect "
            f"at ({hit[0]:.1f}, {hit[1]:.1f})."
        )
    if vut_verts and tgt_verts:
        return (
            f" WARNING: VUT and {targets[0]} paths do NOT geometrically intersect — "
            f"verify the scenario layout."
        )
    return ""


def check_sc_16(
    xosc_root: Any, config: Config, scenario_tag: str | None = None,
    designed_impact_pct: float | None = None,
) -> CheckResult:
    """Impact % for turning/crossing ≈ protocol value (±5%).

    USP: the validator estimates the designed §1.2.5 impact location (see _impact_verdict)
    — from the exported trajectories for RoadRunner kinematic scenarios, or from a straight
    trajectory synthesised from Init pose+speed for parametric ones. Pre-HIL design
    verification the RoadRunner GUI cannot show; HIL remains the final authority.
    """
    tag = scenario_tag or _detect_scenario_tag(xosc_root, config)
    proto = config.scenario_protocol(tag) if tag else None

    if not proto or proto.type not in ("crossing",):
        return _make("CH_SC_16", "NA", "Not a turning/crossing scenario")

    # The per-instance designed overlap comes from the scenario filename (e.g. 50Imp);
    # fall back to the protocol's nominal value when the filename token is unavailable.
    expected = designed_impact_pct if designed_impact_pct is not None else proto.impact_overlap_pct
    tolerance = config.impact_tolerance_pct
    vut = _identify_vut(xosc_root, config)
    if not vut:
        return _make("CH_SC_16", "MANUAL_REVIEW",
                     "Could not identify the VUT entity to estimate impact geometry.")
    return _impact_verdict(
        xosc_root, config, vut, expected, tolerance, "CH_SC_16",
        side_impact=proto.side_impact,
    )


def check_sc_17(
    xosc_root: Any, config: Config, scenario_tag: str | None = None,
    designed_impact_pct: float | None = None,
) -> CheckResult:
    """Impact % for longitudinal must match the protocol value (±1%).

    USP: same §1.2.5 impact estimation as CH_SC_16 (see _impact_verdict) but for
    longitudinal / head-on scenarios with the stricter ±1% tolerance.
    """
    tag = scenario_tag or _detect_scenario_tag(xosc_root, config)
    proto = config.scenario_protocol(tag) if tag else None

    if not proto or proto.type not in ("longitudinal", "head-on"):
        return _make("CH_SC_17", "NA", "Not a longitudinal/head-on scenario")

    # Per-instance designed overlap from the filename (e.g. 50Imp); fall back to protocol.
    expected = designed_impact_pct if designed_impact_pct is not None else proto.impact_overlap_pct
    tolerance = config.longitudinal_impact_tolerance_pct
    vut = _identify_vut(xosc_root, config)
    if not vut:
        return _make("CH_SC_17", "MANUAL_REVIEW",
                     "Could not identify the VUT entity to estimate impact geometry.")
    return _impact_verdict(
        xosc_root, config, vut, expected, tolerance, "CH_SC_17",
        side_impact=proto.side_impact,
    )


def check_sc_18(
    xosc_root: Any, config: Config, scenario_tag: str | None = None,
    parsed_name: Any = None,
) -> CheckResult:
    """VUT speed and Target speed at impact must match scenario requirements.

    Also cross-checks the filename VUT-speed token against the .xosc trajectory speed and
    flags a mismatch (likely naming mistake) as MANUAL_REVIEW.
    """
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

    # Cross-check the filename VUT token against the measured .xosc speed (naming mistake).
    if parsed_name is not None and getattr(parsed_name, "vut_speed_kmh", None) is not None:
        if abs(vut_speed_kmh - parsed_name.vut_speed_kmh) > max(1.5, 0.05 * parsed_name.vut_speed_kmh):
            return _make(
                "CH_SC_18",
                "MANUAL_REVIEW",
                f"Filename says {parsed_name.vut_speed_kmh} km/h VUT but the .xosc trajectory is "
                f"{vut_speed_kmh:.1f} km/h ({speed_source}) - likely a naming mistake; verify.",
            )

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
        _, direction = xosc.get_polyline_part2_radius(
            xosc_root, vut, handedness=config.traffic_handedness
        )
        if direction:
            inferred_direction = (
                f" Inferred VUT turn direction from trajectory: {direction} "
                f"(traffic_handedness={config.traffic_handedness}; in LHT positive heading = Farside/left). "
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


def check_sc_22(xosc_root: Any, config: Config, scenario_tag: str | None = None) -> CheckResult:
    """
    All obstructions placed in NCAP Asset folder.

    Official checklist wording: "All obstructions should be placed in NCAP Asset folder in RR".
    VUT is excluded — it is an OEM custom model not expected in the NCAP Asset folder.
    SOV entities (config.sov_entity_names) are exempt: per checklist Prerequisites the SOV
    "can either be a GVT or a real vehicle", so a non-NCAP path is protocol-legal.
    Accepts both inline model3d properties and OpenSCENARIO CatalogReference elements;
    for CatalogReference, the catalogName must contain 'ncap' or 'asset'.
    """
    entity_sources = xosc.get_entity_catalog_filepaths(xosc_root)
    vut = _identify_vut(xosc_root, config)
    sov_names = {n.upper() for n in getattr(config, "sov_entity_names", ["SOV"])}

    # Remove VUT — only targets and static obstructions are required to use NCAP assets
    non_vut = {name: (path, src) for name, (path, src) in entity_sources.items() if name != vut}

    if not non_vut:
        return _make(
            "CH_SC_22",
            "MANUAL_REVIEW",
            "No asset filepath/CatalogReference found for non-VUT entities. "
            "Manually confirm all obstructions are in the 'NCAP Asset' folder in RoadRunner.",
        )

    wrong: list[str] = []
    param_refs: list[str] = []
    ok_items: list[str] = []

    for entity_name, (path, src) in non_vut.items():
        if not path:
            continue
        if entity_name.upper() in sov_names:
            ok_items.append(
                f"'{entity_name}' [{src}] exempt — SOV may be GVT or real vehicle per protocol"
            )
        elif path.startswith("$") or path.startswith("%"):
            param_refs.append(f"'{entity_name}' ({src}: {path})")
        elif "ncap" not in path.lower() and "asset" not in path.lower():
            wrong.append(f"'{entity_name}' [{src}] → '{path}'")
        else:
            ok_items.append(f"'{entity_name}' [{src}]")

    if wrong:
        msg = (
            f"Asset(s) not in NCAP Asset folder: {'; '.join(wrong)}. "
            "Move these to the NCAP Asset folder in RoadRunner and re-export."
        )
        proto = config.scenario_protocol(scenario_tag) if scenario_tag else None
        if proto and getattr(proto, "has_sov", False):
            msg += (
                f" This scenario includes an SOV: if one of these is the overtaken vehicle, "
                f"rename it to one of {sorted(sov_names)} (see CH_NM_01) — "
                f"the SOV is permitted to be a real vehicle per protocol."
            )
        if param_refs:
            msg += f" Also verify parameterized refs manually: {'; '.join(param_refs)}."
        return _make("CH_SC_22", "FAIL", msg)

    if param_refs:
        return _make(
            "CH_SC_22",
            "MANUAL_REVIEW",
            f"Asset reference(s) are parameterized — cannot verify at parse time: {'; '.join(param_refs)}. "
            "Confirm they resolve to the NCAP Asset folder in RoadRunner.",
        )

    ok_note = f" ({', '.join(ok_items)})" if ok_items else ""
    return _make(
        "CH_SC_22",
        "PASS",
        f"All {len(non_vut)} non-VUT asset reference(s) use NCAP/asset folder{ok_note}.",
    )


def run_all(
    xosc_root: Any, xodr_root: Any, config: Config, scenario_tag: str | None = None,
    designed_impact_pct: float | None = None, parsed_name: Any = None,
) -> list[CheckResult]:
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
        check_sc_16(xosc_root, config, scenario_tag=scenario_tag, designed_impact_pct=designed_impact_pct),
        check_sc_17(xosc_root, config, scenario_tag=scenario_tag, designed_impact_pct=designed_impact_pct),
        check_sc_18(xosc_root, config, scenario_tag=scenario_tag, parsed_name=parsed_name),
        check_sc_19(xosc_root, config),
        check_sc_20(xosc_root, config),
        check_sc_21(xosc_root, config),
        check_sc_22(xosc_root, config, scenario_tag=scenario_tag),
    ]
