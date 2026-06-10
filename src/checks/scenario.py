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
        # SC_04 grades the .xosc StopTrigger SimulationTimeCondition — the full scene duration,
        # which the real RoadRunner exports set to 100-150 s regardless of VUT speed. The
        # simulation_time_by_speed_s bands (35-60 s) describe the protocol maneuver/approach
        # time, NOT the scene StopTrigger, so they are intentionally only consulted when an Init
        # AbsoluteTargetSpeed is present (non-kinematic authoring). Kinematic exports keep the
        # flat 100-150 s scene-duration range; do NOT fall back to the trajectory speed here, or
        # the scene duration gets graded against the maneuver-time band and every export FAILs.
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

    Scope note: the protocol turn is a 3-segment clothoid-arc-clothoid with entry/exit angles
    (alpha/beta, Frontal v1.1 Table 1.2.4). The validated, non-brittle check here is the Part-2
    constant-arc radius against the protocol table; the RR polyline export does not expose the
    clothoid transition parameters cleanly, so the entry/exit-angle check stays manual.
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
    """Scenario satisfies applicable protocol requirements.

    This is the catch-all "did we meet the protocol" item. Rather than a blind "go read the
    protocol", it reports the concrete, scenario-specific facts the tool already knows (the
    correct EuroNCAP motion class - NOT the internal tolerance-routing key - plus the speed
    range, impact axis and turn sub-variant) and names the individual checks that auto-verify
    each protocol requirement, so a reviewer who sees those pass can sign this off without a
    separate manual pass through the protocol.
    """
    tag = scenario_tag or _detect_scenario_tag(xosc_root, config)
    if not tag:
        return _make(
            "CH_SC_08", "MANUAL_REVIEW",
            "Scenario type could not be identified from the name or parameters - verify the "
            "applicable EuroNCAP protocol requirements manually.",
        )

    motion = scenario_motion_type(tag)
    family = {"CC": "Car-to-Car", "CP": "Car-to-Pedestrian",
              "CB": "Car-to-Bicyclist", "CM": "Car-to-Motorcyclist"}.get(tag[:2].upper(), "")
    proto = config.scenario_protocol(tag)

    facts: list[str] = []
    label = f"{family} " if family else ""
    facts.append(f"{tag} is a {label}{motion} scenario"
                 + (" (VUT approaches the target from behind)" if is_rear_approach(tag) else ""))
    if proto and proto.vut_speed_range_kmh:
        facts.append(f"VUT speed range {proto.vut_speed_range_kmh} km/h (graded by CH_SC_18)")
    if proto and proto.side_impact:
        facts.append("side-impact: impact location measured across the VUT length (CH_SC_16)")
    side, cross = turn_subvariant(tag)
    if side or cross:
        facts.append(f"turn sub-variant {side} turn / target {cross} direction (CH_SC_20)")

    covered = (
        "naming (CH_NM_01-05), road & junction layout (CH_RD), Init positions and timing "
        "(CH_SC_02-13), zero-speed targets (CH_SC_14/15), impact location (CH_SC_16/17), VUT & "
        "target speed (CH_SC_18), turn radius (CH_SC_07)"
    )
    return _make(
        "CH_SC_08", "MANUAL_REVIEW",
        ". ".join(facts) + ". Each protocol-specific requirement for this scenario is "
        f"individually auto-checked by: {covered}. If those checks pass, this catch-all review "
        "can be signed off without a separate pass through the protocol; otherwise address the "
        "flagged items above.",
    )


def check_sc_09(xosc_root: Any, config: Config) -> CheckResult:
    """Static asset positions should be present in Init.

    Scope note: this verifies the obstruction assets EXIST and are positioned. Whether an
    obstruction actually OCCLUDES the VUT-to-target sightline at the relevant instant
    (CPNCO/CBNAO/CMCscp line-of-sight) is time-dependent geometry that depends on the impact
    point and approach; it remains a manual HIL verification rather than a brittle static test.
    """
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


def _vut_heading(xosc_root: Any, vut: str | None) -> float | None:
    """VUT travel heading (rad): first trajectory vertex, else Init pose."""
    if not vut:
        return None
    verts = xosc.get_trajectory_vertices(xosc_root, vut)
    if verts:
        return verts[0]["h"]
    pos = xosc.get_init_positions(xosc_root)
    return pos[vut]["h"] if vut in pos else None


def _obstruction_layout_note(
    xosc_root: Any, config: Config, vut: str | None, obstructions: list[str]
) -> tuple[bool, str]:
    """Measure the parked-obstruction layout against Frontal v1.1 TEST PROCEDURE 3.2.3:
    vehicles 1 m apart bumper-to-bumper, lateral edge offset 2 m (nearside) / 5.5 m (farside)
    to the VUT trajectory. Returns (ok, human note). ok is False only on a clear deviation;
    geometry that cannot be measured returns (True, '') so it never hard-fails the 0-speed check.
    """
    if len(obstructions) < 2:
        return True, ""
    heading = _vut_heading(xosc_root, vut)
    pos = xosc.get_init_positions(xosc_root)
    pts = [(o, pos[o]) for o in obstructions if o in pos]
    if heading is None or vut not in pos or len(pts) < 2:
        return True, ""

    cos_h, sin_h = math.cos(heading), math.sin(heading)
    vx, vy = pos[vut]["x"], pos[vut]["y"]
    # project each obstruction onto the VUT travel axis (along) and the lateral axis
    along = {o: (p["x"] - vx) * cos_h + (p["y"] - vy) * sin_h for o, p in pts}
    lateral = {o: abs(-(p["x"] - vx) * sin_h + (p["y"] - vy) * cos_h) for o, p in pts}
    ordered = sorted(along, key=lambda o: along[o])

    veh_len = config.vehicle_dimensions.get("GVT", config.vehicle_dimensions["default_car"]).length
    veh_half_w = config.vehicle_dimensions.get("GVT", config.vehicle_dimensions["default_car"]).width / 2.0
    expected_spacing = veh_len + config.obstruction_gap_m
    tol = config.obstruction_layout_tolerance_m

    spacings = [along[ordered[i + 1]] - along[ordered[i]] for i in range(len(ordered) - 1)]
    spacing_ok = all(abs(s - expected_spacing) <= tol for s in spacings)

    edge_offset = min(lateral.values()) - veh_half_w
    near, far = config.obstruction_offset_nearside_m, config.obstruction_offset_farside_m
    side = "nearside" if abs(edge_offset - near) <= abs(edge_offset - far) else "farside"
    expected_offset = near if side == "nearside" else far
    offset_ok = abs(edge_offset - expected_offset) <= tol

    note = (
        f"Obstruction layout: {len(pts)} vehicles, spacing {', '.join(f'{s:.1f}' for s in spacings)} m "
        f"(expect ~{expected_spacing:.1f} m = {veh_len:.1f} m vehicle + {config.obstruction_gap_m:.1f} m gap), "
        f"lateral edge offset ~{edge_offset:.1f} m ({side}, expect {expected_offset:.1f} m)."
    )
    return (spacing_ok and offset_ok), note


def check_sc_14(xosc_root: Any, config: Config) -> CheckResult:
    """Static targets/obstructions: Initialize Speed = Absolute(0 m/s).

    For obstruction scenarios (>=2 obstruction vehicles) the parked layout is also measured
    against the protocol (1 m bumper gap, 2 m nearside / 5.5 m farside lateral offset) and a
    clear deviation downgrades the PASS to MANUAL_REVIEW.
    """
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
    if fails:
        return _make("CH_SC_14", "FAIL", "; ".join(r.comment for r in fails))

    obstructions = [e for e in static_candidates if "OBSTRUCTION" in e.upper()]
    layout_ok, layout_note = _obstruction_layout_note(xosc_root, config, vut, obstructions)
    base = f"All static entities ({', '.join(static_candidates)}) have 0 m/s init speed"
    if not layout_note:
        return _make("CH_SC_14", "PASS", base)
    if layout_ok:
        return _make("CH_SC_14", "PASS", f"{base}. {layout_note}")
    return _make(
        "CH_SC_14",
        "MANUAL_REVIEW",
        f"{base}, but the obstruction layout deviates from the protocol - verify. {layout_note}",
    )


def check_sc_15(xosc_root: Any, config: Config, parsed_name: Any = None) -> CheckResult:
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

    # A target the filename DESIGNS to move (token speed > 0, e.g. '30EMT') is a moving actor
    # even when it is parametric (no FollowTrajectoryAction) - it must not be force-checked for
    # 0 m/s. This complements the trajectory heuristic so the design, not just the file shape,
    # decides stationary-vs-moving.
    designed_moving: set[str] = set()
    if parsed_name is not None:
        token_type = getattr(parsed_name, "target_type", None)
        token_kmh = getattr(parsed_name, "target_speed_kmh", None)
        if token_type and token_kmh and token_kmh > 0:
            designed_moving = {e for e in emt_candidates if token_type.upper() in e.upper()}

    # Entities with a kinematic trajectory are actively moving in this scenario
    # (e.g. EPTa/EPTc in crossing scenarios). Skip them — they are correctly moving.
    moving = {e for e in emt_candidates if xosc.has_init_follow_trajectory(xosc_root, e)} | designed_moving
    stationary = [e for e in emt_candidates if e not in moving]
    moving_via_traj = sorted(moving)

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


# ---------------------------------------------------------------------------
# EuroNCAP motion taxonomy + per-actor target reference points (§1.2.5 / §1.4.1)
# ---------------------------------------------------------------------------

def scenario_motion_type(tag: str | None) -> str:
    """EuroNCAP motion taxonomy (verification table pp60-61): 'longitudinal' / 'turning' /
    'crossing', derived from the scenario tag. A fixed protocol classification (not site
    config): Turning = turn-across-path (CCFtap/CMFtap) + pedestrian/cyclist turning
    (CPTA*/CBTA*); Crossing = straight-crossing-path (*scp) + the crossing VRU families;
    everything else (rear, head-on, longitudinal VRU) is Longitudinal."""
    t = (tag or "").upper()
    if "TAP" in t or t.startswith("CPTA") or t.startswith("CBTA"):
        return "turning"
    if "SCP" in t or t.startswith(("CPNA", "CPFA", "CPNCO", "CBNA", "CBNAO", "CBFA")):
        return "crossing"
    return "longitudinal"


def is_rear_approach(tag: str | None) -> bool:
    """True when the VUT approaches the target from behind, so the struck point is the
    target REAR: Car/Motorcyclist Rear (CCR*/CMR*) and longitudinal VRU following
    (CPLA/CBLA). Head-on (CCF*), turning and crossing strike the target FRONT."""
    return (tag or "").upper().startswith(("CCR", "CMR", "CPLA", "CBLA"))


def turn_subvariant(token: str | None) -> tuple[str, str]:
    """Decode the EuroNCAP turning sub-variant suffix for CPTA/CBTA tokens.

    Grounded in Frontal v1.1 §3.2.2.1 (Car-to-Pedestrian Turning): the 1st suffix letter is
    the VUT turn side (f=Farside, n=Nearside) and the 2nd is the target's travel relative to
    the VUT (s=Same direction, o=Opposite direction). So CPTAfs/CPTAns = Same, CPTAfo/CPTAno
    = Opposite. Returns ('Farside'|'Nearside'|'', 'Same'|'Opposite'|''); empty for any token
    that is not a CPTA/CBTA turning sub-variant."""
    t = (token or "").upper()
    if not t.startswith(("CPTA", "CBTA")):
        return "", ""
    table = {
        "FS": ("Farside", "Same"), "FO": ("Farside", "Opposite"),
        "NS": ("Nearside", "Same"), "NO": ("Nearside", "Opposite"),
    }
    return table.get(t[-2:], ("", ""))


def resolve_actor(
    entity_name: str, filename_token: str | None,
    bbox: tuple[float, float, float, float], osc_category: str,
) -> str:
    """Resolve the EuroNCAP target type {GVT, SOV, EPTa, EPTc, EBTa, EMT}.

    OSC category alone cannot distinguish GVT/EBTa/EMT (RoadRunner exports all three as
    <Vehicle>), so use the entity-name token first (authoritative — names carry the token,
    e.g. 'EPTc_Trajectory'), then the filename target token, then a bbox aspect-ratio
    fallback. EPTc is tested before EPTa (substring)."""
    tokens = ("EPTc", "EPTa", "EBTa", "EMT", "GVT", "SOV")
    name = (entity_name or "").upper().replace("_TRAJECTORY", "")
    for tok in tokens:
        if tok.upper() in name:
            return tok
    if filename_token:
        for tok in tokens:
            if tok.upper() == filename_token.upper():
                return tok
    if osc_category == "Pedestrian":
        return "EPTa"
    length, width = bbox[2], bbox[3]
    if 0 < width < 1.0 and length / width > 2.4:
        return "EBTa" if length <= 2.0 else "EMT"   # long & thin → two-wheeler
    return "GVT"


def target_reference_offset(actor: str, motion: str, is_rear: bool) -> tuple[float, float]:
    """EuroNCAP target reference point as (f_lon, f_lat) fractions of the target
    (length, width) from the bbox centre, in the target body frame (§1.2.5 / §1.4.1).
    Box-relative approximations of the protocol points (exact hip/wheel offsets are not in
    the RR export): front = +front edge, rear = −rear edge, centre = 0."""
    a = (actor or "").upper()
    if a in ("EPTA", "EPTC"):                       # pedestrian
        # longitudinal (CPLA): VUT strikes the dummy's BACK (centreline-crosses-box point).
        # turning (hip) and crossing (struck mid-body) ≈ the dummy centre — the 0.5 m box
        # makes the exact point low-sensitivity anyway.
        return (-0.25, 0.0) if motion == "longitudinal" else (0.0, 0.0)
    if a == "EBTA":                                 # cyclist
        if motion == "turning":
            return (0.40, 0.0)                      # front wheel
        if motion == "crossing":
            return (0.0, 0.0)                       # crank shaft
        return (-0.40, 0.0)                         # rear wheel (longitudinal)
    if a == "EMT":                                  # motorcyclist
        if motion == "longitudinal" and is_rear:
            return (-0.40, 0.0)                     # rear wheel (CMRs/CMRb)
        return (0.40, 0.0)                          # front wheel (turning/crossing/long-front)
    # GVT / SOV (vehicle): rear for rear-approach (CCR), front for head-on/turning/crossing
    if motion == "longitudinal" and is_rear:
        return (-0.50, 0.0)
    return (0.50, 0.0)


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
    tag: str | None = None, side_impact: bool = False, parsed_name: Any = None,
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
    tgt_bbox = _entity_bbox(xosc_root, config, tgt)
    # EuroNCAP target reference point depends on the actor AND the motion type (§1.2.5/§1.4.1).
    osc_category = xosc.get_entity_category(xosc_root, tgt) or "Vehicle"
    filename_token = getattr(parsed_name, "target_type", None) if parsed_name is not None else None
    actor = resolve_actor(tgt, filename_token, tgt_bbox, osc_category)
    motion = scenario_motion_type(tag)
    ref_offset = target_reference_offset(actor, motion, is_rear_approach(tag))
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
        tgt_bbox,
        ref_offset=ref_offset, side_impact=side_impact,
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
    ref_desc = {(-0.5, 0.0): "rear", (0.5, 0.0): "front", (0.4, 0.0): "front wheel",
                (-0.4, 0.0): "rear wheel", (-0.25, 0.0): "back", (0.0, 0.0): "centre"}.get(
                    (round(ref_offset[0], 2), round(ref_offset[1], 2)), f"{ref_offset[0]:+.0%}L")
    sensitivity = est.eval_sensitivity_pct or 0.0

    # §1.2.5.2 rotation-robust estimate. When the VUT is mid-turn / closing fast (turn-across-
    # path), the impacting corner contacts BEFORE the target reference point reaches the impact
    # plane, so the single-point reference reading sweeps across the whole VUT width within the
    # ±0.1 s sync window (high sensitivity) and lands far from the designed location. In that
    # regime switch to the overlap-centre — the lateral midpoint of where the target footprint
    # covers the VUT, which is steady through the corner-first transient and recovers the
    # protocol overlap location (EuroNCAP AEB C2C: the front edges meet at the designed overlap
    # of the VUT width, reference line = VUT centreline). Only switch when the overlap metric is
    # actually steadier, so small/slow VRU targets keep the precise reference-point reading.
    overlap = est.impact_pct_length_overlap if side_impact else est.impact_pct_width_overlap
    overlap_sens = est.overlap_sensitivity_pct
    metric_note = ""
    if (sensitivity > config.impact_rotation_sensitivity_pct
            and overlap is not None and overlap_sens is not None
            and overlap_sens < sensitivity):
        computed = overlap
        sensitivity = overlap_sens
        metric_note = (
            " Uses the rotation-robust §1.2.5.2 overlap-centre estimate (the reference-point "
            "reading is unstable here — the impacting corner contacts before the reference "
            "point reaches the impact plane)."
        )

    detail = (
        f"{actor} {motion}, reference={ref_desc}, first contact t={est.t_contact:.2f}s, "
        f"relative heading {est.rel_heading_deg:.0f}°"
    )
    basis = (
        f"Computed from {src} (no AEB by design); §1.2.5 impact location across VUT "
        f"{axis}{side_note}.{metric_note} Confirm in HIL."
    )
    # Uncertainty-aware verdict (derived from geometry, not the scenario name). The estimate
    # carries a kinematic uncertainty = how far the impact % swings across the ±0.1 s SCP sync
    # window. PASS when it lands on the design within tolerance; MANUAL_REVIEW when the design
    # value still lies inside that uncertainty band (geometry the kinematics cannot pin down —
    # §1.2.5.2 — so we can neither confirm nor reject it); FAIL only when the estimate is
    # confidently off (far from the design AND the geometry is stable).
    miss = abs(computed - expected)
    if miss <= tolerance:
        return _make(
            check_id, "PASS",
            f"Geometric impact estimate {computed:.1f}% matches protocol {expected:.0f}% "
            f"±{tolerance:.0f}% ({detail}). {basis}",
        )
    if miss <= sensitivity:
        return _make(
            check_id, "MANUAL_REVIEW",
            f"Impact estimate {computed:.1f}% vs protocol {expected:.0f}% ±{tolerance:.0f}% "
            f"({detail}). The design value is within the estimate's kinematic uncertainty "
            f"(the impact % swings ±{sensitivity:.0f}% across the ±0.1 s sync window — "
            f"rotating/fast geometry), so design-time kinematics can neither confirm nor "
            f"reject it; verify the impact location in RoadRunner. {basis}",
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
    designed_impact_pct: float | None = None, parsed_name: Any = None,
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
        tag=tag, side_impact=proto.side_impact, parsed_name=parsed_name,
    )


def check_sc_17(
    xosc_root: Any, config: Config, scenario_tag: str | None = None,
    designed_impact_pct: float | None = None, parsed_name: Any = None,
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
        tag=tag, side_impact=proto.side_impact, parsed_name=parsed_name,
    )


def _resolve_primary_target(xosc_root: Any, config: Config, target_type: str) -> str | None:
    """The non-VUT, non-SOV entity that carries the filename target token in its name
    (e.g. 'GVT', 'EPTc') - the scenario's primary target, distinct from an SOV or an
    obstruction. Returns None when no entity matches."""
    vut_upper = {n.upper() for n in config.vut_entity_names}
    sov_upper = {n.upper() for n in config.sov_entity_names}
    tt = target_type.upper()
    for entity in xosc.get_entities(xosc_root):
        name = xosc.get_entity_name(entity)
        nu = name.upper()
        if nu in vut_upper or nu in sov_upper:
            continue
        if tt in nu:
            return name
    return None


def _entity_speed_kmh(xosc_root: Any, name: str) -> float | None:
    """Measured speed (km/h) of an entity: trajectory cruise speed first (actual motion),
    else the Init AbsoluteTargetSpeed. None when neither is present (parametric, unknown)."""
    traj_kmh = xosc.get_trajectory_speed_kmh(xosc_root, name)
    if traj_kmh is not None:
        return traj_kmh
    init = xosc.get_init_speed(xosc_root, name)
    return init * 3.6 if init is not None else None


def _target_speed_crosscheck(
    xosc_root: Any, config: Config, parsed_name: Any
) -> tuple[str | None, str | None]:
    """Cross-check the .xosc primary-target speed against the filename target-speed token.

    Returns (mismatch_msg, verified_msg). Both None when it cannot be evaluated (no parsed
    filename, no target token/speed, target entity not found, or no measurable speed). The
    designed target speed is encoded in the filename token (e.g. '5EPTa', '45GVT'), so this
    needs no per-scenario config - it verifies the built scene matches its own design.
    """
    if parsed_name is None:
        return None, None
    target_type = getattr(parsed_name, "target_type", None)
    token_kmh = getattr(parsed_name, "target_speed_kmh", None)
    if not target_type or token_kmh is None:
        return None, None
    name = _resolve_primary_target(xosc_root, config, target_type)
    if not name:
        return None, None
    measured = _entity_speed_kmh(xosc_root, name)
    if measured is None:
        return None, None
    if abs(measured - token_kmh) > max(1.5, 0.05 * token_kmh):
        return (
            f"filename target token says {token_kmh} km/h {target_type} but the .xosc "
            f"'{name}' speed is {measured:.1f} km/h - likely a naming mistake; verify."
        ), None
    return None, f"target '{name}' {measured:.1f} km/h matches the {token_kmh} km/h {target_type} token"


def check_sc_18(
    xosc_root: Any, config: Config, scenario_tag: str | None = None,
    parsed_name: Any = None,
) -> CheckResult:
    """VUT speed and Target speed at impact must match scenario requirements.

    Cross-checks the filename VUT-speed token against the .xosc trajectory speed (a mismatch
    is a likely naming mistake -> MANUAL_REVIEW), grades the VUT speed against the per-scenario
    protocol range, and cross-checks the primary-target speed against the filename target token.
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

    target_mismatch, target_verified = _target_speed_crosscheck(xosc_root, config, parsed_name)

    # Grade the DESIGNED VUT speed against the protocol range. The filename VUT token (e.g.
    # 10VUT = 10 km/h) is the exact design value; the measured trajectory peak carries
    # discretisation noise (a 10 km/h design can measure 9.98 km/h), which a strict comparison
    # would falsely fail at a band edge. So grade the token when present (already cross-checked
    # as consistent with the trajectory above), and fall back to the measured speed with a small
    # boundary tolerance when no token is available.
    token_kmh = getattr(parsed_name, "vut_speed_kmh", None) if parsed_name is not None else None
    if token_kmh is not None:
        graded_kmh = float(token_kmh)
        graded_src = f"filename design token {token_kmh:.0f} km/h, trajectory {vut_speed_kmh:.1f} km/h"
        edge_tol = 0.0
    else:
        graded_kmh = vut_speed_kmh
        graded_src = speed_source
        edge_tol = config.speed_range_tolerance_kmh

    if proto.vut_speed_range_kmh:
        lo, hi = proto.vut_speed_range_kmh
        if not (lo - edge_tol <= graded_kmh <= hi + edge_tol):
            comment = (
                f"VUT speed = {graded_kmh:.1f} km/h - outside protocol range [{lo}, {hi}] km/h "
                f"for {tag} (source: {graded_src})"
            )
            if target_mismatch:
                comment += f". Also: {target_mismatch}"
            return _make("CH_SC_18", "FAIL", comment)

        vut_msg = (
            f"VUT speed = {graded_kmh:.1f} km/h in range [{lo}, {hi}] km/h for {tag} "
            f"(source: {graded_src})"
        )
        if target_mismatch:
            return _make("CH_SC_18", "MANUAL_REVIEW", f"{vut_msg}, but {target_mismatch}")
        suffix = f"; {target_verified}" if target_verified else ""
        return _make("CH_SC_18", "PASS", vut_msg + suffix)

    # No VUT range configured - still report a target-speed disagreement if one exists.
    if target_mismatch:
        return _make("CH_SC_18", "MANUAL_REVIEW", target_mismatch)
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


def _infer_same_opposite(xosc_root: Any, config: Config, vut: str | None, parsed_name: Any) -> str:
    """Infer whether the primary target travels in the SAME or OPPOSITE direction to the VUT,
    from the angle between their headings (cos > 0 = Same, < 0 = Opposite). '' when ambiguous
    (perpendicular crossing) or the headings cannot be read."""
    if not vut:
        return ""
    vut_verts = xosc.get_trajectory_vertices(xosc_root, vut)
    if vut_verts:
        h_vut = vut_verts[0]["h"]
    else:
        pos = xosc.get_init_positions(xosc_root)
        if vut not in pos:
            return ""
        h_vut = pos[vut]["h"]

    target = None
    if parsed_name is not None and getattr(parsed_name, "target_type", None):
        target = _resolve_primary_target(xosc_root, config, parsed_name.target_type)
    if not target:
        return ""
    tgt_verts = xosc.get_trajectory_vertices(xosc_root, target)
    if tgt_verts:
        sx = sum(math.cos(v["h"]) for v in tgt_verts)
        sy = sum(math.sin(v["h"]) for v in tgt_verts)
        h_tgt = math.atan2(sy, sx)
    else:
        pos = xosc.get_init_positions(xosc_root)
        if target not in pos:
            return ""
        h_tgt = pos[target]["h"]

    dot = math.cos(h_tgt - h_vut)
    if dot > 0.2:
        return "Same"
    if dot < -0.2:
        return "Opposite"
    return ""


def check_sc_20(xosc_root: Any, config: Config, parsed_name: Any = None) -> CheckResult:
    """VUT turn direction (Farside/Nearside) and target direction (Same/Opposite) maintained.

    Primary: explicit direction/side ParameterDeclarations. Otherwise (RR kinematic format)
    the intended sub-variant is decoded from the filename suffix (CPTA/CBTA fo/fs/no/ns, per
    Frontal v1.1 §3.2.2.1) and confirmed against the geometry: the VUT turn side from its
    trajectory curvature, and Same/Opposite from the target-vs-VUT heading. A geometry that
    contradicts the name is flagged for review.
    """
    params = xosc.get_parameter_declarations(xosc_root)
    direction_params = [
        p for p in params
        if any(kw in p["name"].lower() for kw in ["direction", "side", "ebt", "ept", "farside", "nearside"])
    ]
    if direction_params:
        values = ", ".join(f"{p['name']}={p['value']}" for p in direction_params)
        return _make("CH_SC_20", "PASS", f"Direction parameters found: {values}")

    vut = _identify_vut(xosc_root, config)
    inferred_side = ""
    if vut and xosc.has_init_follow_trajectory(xosc_root, vut):
        _, inferred_side = xosc.get_polyline_part2_radius(
            xosc_root, vut, handedness=config.traffic_handedness
        )
    inferred_cross = _infer_same_opposite(xosc_root, config, vut, parsed_name)

    token = getattr(parsed_name, "type_token", None) if parsed_name is not None else None
    intended_side, intended_cross = turn_subvariant(token)

    if intended_side or intended_cross:
        discrepancies: list[str] = []
        if intended_side and inferred_side and inferred_side != intended_side:
            discrepancies.append(f"name says {intended_side} turn but the trajectory turns {inferred_side}")
        if intended_cross and inferred_cross and inferred_cross != intended_cross:
            discrepancies.append(f"name says target {intended_cross} direction but the geometry shows {inferred_cross}")

        side_ok = bool(intended_side and inferred_side == intended_side)
        cross_ok = bool(intended_cross and inferred_cross == intended_cross)
        sub = (
            f"{token}: VUT {intended_side} turn"
            + (" (trajectory confirms)" if side_ok else "")
            + f", target {intended_cross} direction"
            + (" (geometry confirms)" if cross_ok else "")
        )
        if discrepancies:
            return _make("CH_SC_20", "MANUAL_REVIEW", f"{sub}. Discrepancy: {'; '.join(discrepancies)} - verify.")
        if side_ok or cross_ok:
            return _make("CH_SC_20", "PASS", f"Sub-variant {sub}.")
        return _make(
            "CH_SC_20",
            "MANUAL_REVIEW",
            f"Sub-variant from filename {sub}, but the geometry could not confirm it - verify manually.",
        )

    inferred_direction = ""
    if inferred_side:
        inferred_direction = (
            f" Inferred VUT turn direction from trajectory: {inferred_side} "
            f"(traffic_handedness={config.traffic_handedness}; in LHT positive heading = Farside/left). "
            f"Verify the target direction (Same/Opposite) matches the scenario intent."
        )
    base_msg = "No direction/side parameters in ParameterDeclarations."
    return _make(
        "CH_SC_20",
        "MANUAL_REVIEW",
        base_msg + (inferred_direction or " Manually verify VUT turn direction and target direction."),
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
        check_sc_15(xosc_root, config, parsed_name=parsed_name),
        check_sc_16(xosc_root, config, scenario_tag=scenario_tag, designed_impact_pct=designed_impact_pct, parsed_name=parsed_name),
        check_sc_17(xosc_root, config, scenario_tag=scenario_tag, designed_impact_pct=designed_impact_pct, parsed_name=parsed_name),
        check_sc_18(xosc_root, config, scenario_tag=scenario_tag, parsed_name=parsed_name),
        check_sc_19(xosc_root, config),
        check_sc_20(xosc_root, config, parsed_name=parsed_name),
        check_sc_21(xosc_root, config),
        check_sc_22(xosc_root, config, scenario_tag=scenario_tag),
    ]
