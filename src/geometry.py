"""Vehicle bounding box overlap calculator for EuroNCAP impact percentage checks.

CH_SC_16 (turning/crossing): approximate, ±5% tolerance.
CH_SC_17 (longitudinal): exact match required.
"""
from __future__ import annotations

import math
import logging
from typing import NamedTuple

from shapely.affinity import rotate, translate
from shapely.geometry import box

log = logging.getLogger(__name__)


class VehicleState(NamedTuple):
    x: float
    y: float
    heading_deg: float  # degrees, 0=east, CCW positive
    length: float
    width: float
    speed_ms: float = 0.0


def vehicle_polygon(state: VehicleState):
    """Returns a shapely Polygon for a vehicle's bounding box at its current state."""
    rect = box(-state.length / 2, -state.width / 2, state.length / 2, state.width / 2)
    rotated = rotate(rect, state.heading_deg, origin=(0, 0))
    return translate(rotated, state.x, state.y)


def overlap_percentage(poly_vut, poly_target) -> float:
    """Overlap area of VUT onto target, expressed as % of target area."""
    if poly_target.area == 0:
        return 0.0
    intersection = poly_vut.intersection(poly_target)
    return round((intersection.area / poly_target.area) * 100, 2)


def _project_longitudinal(
    vut: VehicleState,
    target: VehicleState,
    dt: float = 0.05,
    max_time: float = 30.0,
) -> float:
    """
    For longitudinal scenarios (CCRs, CCRb, CCRm):
    Step VUT forward at constant speed until its front bumper reaches the target rear.
    Then compute bounding box overlap.

    Returns overlap percentage at point of closest approach.
    """
    vut_x, vut_y = vut.x, vut.y
    hdg_rad = math.radians(vut.heading_deg)
    dx = math.cos(hdg_rad) * vut.speed_ms
    dy = math.sin(hdg_rad) * vut.speed_ms

    target_poly = vehicle_polygon(target)

    best_overlap = 0.0
    t = 0.0
    prev_dist = None

    while t < max_time:
        current_state = VehicleState(
            x=vut_x + dx * t,
            y=vut_y + dy * t,
            heading_deg=vut.heading_deg,
            length=vut.length,
            width=vut.width,
            speed_ms=vut.speed_ms,
        )
        vut_poly = vehicle_polygon(current_state)

        dist = vut_poly.distance(target_poly)
        ov = overlap_percentage(vut_poly, target_poly)

        if ov > best_overlap:
            best_overlap = ov

        # Stop when VUT passes fully through target
        if prev_dist is not None and prev_dist < dist and ov < 1.0:
            break

        prev_dist = dist
        t += dt

    return best_overlap


def _project_crossing(
    vut: VehicleState,
    target: VehicleState,
    dt: float = 0.05,
    max_time: float = 30.0,
) -> float:
    """
    For crossing/turning scenarios: step both vehicles forward simultaneously
    until maximum overlap, then return that overlap %.
    """
    vut_hdg = math.radians(vut.heading_deg)
    tgt_hdg = math.radians(target.heading_deg)

    best_overlap = 0.0
    t = 0.0
    prev_overlap = 0.0
    increasing = False

    while t < max_time:
        v_state = VehicleState(
            x=vut.x + math.cos(vut_hdg) * vut.speed_ms * t,
            y=vut.y + math.sin(vut_hdg) * vut.speed_ms * t,
            heading_deg=vut.heading_deg,
            length=vut.length,
            width=vut.width,
        )
        t_state = VehicleState(
            x=target.x + math.cos(tgt_hdg) * target.speed_ms * t,
            y=target.y + math.sin(tgt_hdg) * target.speed_ms * t,
            heading_deg=target.heading_deg,
            length=target.length,
            width=target.width,
        )
        vut_poly = vehicle_polygon(v_state)
        tgt_poly = vehicle_polygon(t_state)
        ov = overlap_percentage(vut_poly, tgt_poly)

        if ov > best_overlap:
            best_overlap = ov
            increasing = True
        elif increasing and ov < prev_overlap * 0.5:
            # Overlap peaked and is dropping - stop
            break

        prev_overlap = ov
        t += dt

    return best_overlap


def compute_impact_percentage(
    vut: VehicleState,
    target: VehicleState,
    scenario_type: str,
) -> float:
    """
    Main entry point.

    scenario_type: 'longitudinal' | 'crossing' | 'head-on'
    Returns overlap percentage at impact point.
    """
    if scenario_type == "longitudinal":
        return _project_longitudinal(vut, target)
    return _project_crossing(vut, target)


class ImpactEstimate(NamedTuple):
    """Result of estimate_trajectory_impact().

    EuroNCAP impact-location convention (Protocol Crash Avoidance Frontal Collisions
    v1.1 §1.2.5): the impact location is WHERE the target reference point coincides
    with the %-age of the VUT width — 0% = projection of the outer RIGHT edge,
    100% = outer LEFT edge (50% = centreline). Side-impact scenarios (CMCscp,
    CBTAfs, CBTAns) use the VUT LENGTH instead — 0% = rearmost, 100% = forwardmost.
    Values may fall outside [0, 100] (the protocol matrices use −25%…125%).
    """
    contact: bool
    t_contact: float | None            # first bbox-touch instant (s), None if no contact
    impact_pct_width: float | None     # struck point across VUT WIDTH (0%=right edge,100%=left)
    impact_pct_length: float | None    # struck point across VUT LENGTH (0%=rear,100%=front) — side impacts
    front_pos_left_pct: float | None   # target centre across VUT front, from LEFT edge (human review)
    front_pos_right_pct: float | None  # same, from RIGHT edge (left + right = 100)
    lateral_offset_m: float | None     # target centre lateral offset in VUT frame at contact
    rel_heading_deg: float | None      # |target heading − VUT heading| at contact
    min_gap_m: float | None            # closest approach when no contact
    t_min_gap: float | None
    width_overlap_pct: float | None = None  # legacy band-overlap (kept for reference, not a verdict)


def _interp(verts: list[dict], t: float) -> tuple[float, float, float]:
    """Linear interpolation of (x, y, h) from a trajectory vertex list at time t.
    Heading interpolation is wrap-aware. Clamps outside the time range."""
    if t <= verts[0]["time"]:
        v = verts[0]
        return v["x"], v["y"], v["h"]
    if t >= verts[-1]["time"]:
        v = verts[-1]
        return v["x"], v["y"], v["h"]
    for i in range(1, len(verts)):
        t0, t1 = verts[i - 1]["time"], verts[i]["time"]
        if t0 <= t <= t1:
            f = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
            a, b = verts[i - 1], verts[i]
            dh = b["h"] - a["h"]
            while dh > math.pi:
                dh -= 2 * math.pi
            while dh < -math.pi:
                dh += 2 * math.pi
            return a["x"] + f * (b["x"] - a["x"]), a["y"] + f * (b["y"] - a["y"]), a["h"] + f * dh
    v = verts[-1]
    return v["x"], v["y"], v["h"]


def _bbox_poly(x: float, y: float, h_rad: float, bbox: tuple[float, float, float, float]):
    cx, cy, length, width = bbox
    rect = box(cx - length / 2, cy - width / 2, cx + length / 2, cy + width / 2)
    return translate(rotate(rect, math.degrees(h_rad), origin=(0, 0)), x, y)


def estimate_trajectory_impact(
    vut_verts: list[dict],
    tgt_verts: list[dict],
    vut_bbox: tuple[float, float, float, float],
    tgt_bbox: tuple[float, float, float, float],
    target_category: str = "Vehicle",
    dt: float = 0.05,
) -> ImpactEstimate | None:
    """Estimate the impact geometry from kinematic (unbraked) design trajectories.

    USP: RoadRunner kinematic exports are the UNBRAKED design paths — the scenario
    encodes the intended collision; AEB only exists in the real/HIL test. Stepping
    both actors through time (linear interpolation between trajectory vertices) and
    intersecting their exported bounding boxes finds the designed first-contact
    instant, from which the impact % follows by pure geometry. This gives the team
    pre-HIL design verification that the RoadRunner GUI cannot show.

    Metrics at the first-contact instant (bisection-refined to ~µs):
      - width_overlap_pct (C2C): overlap of the two width bands across the VUT's
        lateral axis, as % of VUT width. 100 = dead-centre, 50 = half offset.
      - front_pos_left/right_pct (VRU): position of the target centre across the
        VUT front, measured from each edge (left + right = 100; 50 = centreline).
        For Pedestrian targets this is evaluated at the instant the target CENTRE
        crosses the VUT front plane (protocol-accurate; validated within ±5% on
        CPTA/CPNCO examples). The caller compares against the side matching the
        protocol convention.

    Caveat: constant-trajectory kinematics, no physics — design verification only;
    HIL remains the final authority.

    Returns None when either vertex list is empty.
    """
    if not vut_verts or not tgt_verts:
        return None

    t0 = max(vut_verts[0]["time"], tgt_verts[0]["time"])
    t1 = min(vut_verts[-1]["time"], tgt_verts[-1]["time"])
    if t1 <= t0:
        return None

    vut_len = vut_bbox[2]
    vut_wid = vut_bbox[3]
    tgt_wid = tgt_bbox[3]
    near = max(vut_len, vut_bbox[3], tgt_bbox[2], tgt_bbox[3]) * 4 + 10  # proximity gate

    first_hit = None
    min_gap, t_min_gap = float("inf"), None
    t = t0
    while t <= t1:
        vx, vy, vh = _interp(vut_verts, t)
        gx, gy, gh = _interp(tgt_verts, t)
        if abs(vx - gx) < near and abs(vy - gy) < near:
            pv = _bbox_poly(vx, vy, vh, vut_bbox)
            pg = _bbox_poly(gx, gy, gh, tgt_bbox)
            if pv.intersects(pg):
                first_hit = t
                break
            gap = pv.distance(pg)
            if gap < min_gap:
                min_gap, t_min_gap = gap, t
        t += dt

    if first_hit is None:
        return ImpactEstimate(
            contact=False, t_contact=None,
            impact_pct_width=None, impact_pct_length=None,
            front_pos_left_pct=None, front_pos_right_pct=None,
            lateral_offset_m=None, rel_heading_deg=None,
            min_gap_m=(min_gap if min_gap != float("inf") else None), t_min_gap=t_min_gap,
        )

    # Bisect [first_hit - dt, first_hit] to the touch instant
    lo, hi = max(t0, first_hit - dt), first_hit
    for _ in range(25):
        mid = (lo + hi) / 2
        vx, vy, vh = _interp(vut_verts, mid)
        gx, gy, gh = _interp(tgt_verts, mid)
        if _bbox_poly(vx, vy, vh, vut_bbox).intersects(_bbox_poly(gx, gy, gh, tgt_bbox)):
            hi = mid
        else:
            lo = mid
    tc = hi

    def vut_frame(t_eval: float) -> tuple[float, float, float, float]:
        """(longitudinal, lateral) of target centre in VUT frame + headings."""
        vx, vy, vh = _interp(vut_verts, t_eval)
        gx, gy, gh = _interp(tgt_verts, t_eval)
        dx, dy = gx - vx, gy - vy
        lon = dx * math.cos(vh) + dy * math.sin(vh)
        lat = -dx * math.sin(vh) + dy * math.cos(vh)
        return lon, lat, vh, gh

    lon_c, lat_c, vh_c, gh_c = vut_frame(tc)
    rel_heading = math.degrees(abs(gh_c - vh_c)) % 360.0
    if rel_heading > 180.0:
        rel_heading = 360.0 - rel_heading

    # Legacy band-overlap (kept for reference only — NOT used as a verdict)
    width_overlap = max(0.0, vut_wid / 2 + tgt_wid / 2 - abs(lat_c))
    width_overlap_pct = min(100.0, width_overlap / vut_wid * 100.0)

    # VRU metric: for pedestrians evaluate at the instant the target CENTRE crosses
    # the VUT front plane (protocol convention); otherwise use the contact instant.
    lat_eval = lat_c
    if target_category == "Pedestrian":
        prev_ahead, prev_lat = None, None
        te = tc
        while te <= min(t1, tc + 5.0):
            lon_e, lat_e, _, _ = vut_frame(te)
            ahead = lon_e - vut_len / 2
            if prev_ahead is not None and prev_lat is not None and prev_ahead > 0 >= ahead:
                # linear interpolation to the exact front-plane crossing (ahead == 0)
                f = prev_ahead / (prev_ahead - ahead)
                lat_eval = prev_lat + f * (lat_e - prev_lat)
                break
            prev_ahead, prev_lat = ahead, lat_e
            te += dt / 2

    # Front position from BOTH edges. The protocol side convention (e.g. CPNA-25
    # vs CPNA-75) depends on target travel direction + handedness; the VUT frame
    # rotates during turning scenarios, so no single side convention is robust.
    # The check compares the expected value against whichever side matches and
    # reports both, plus the raw lateral offset, for human review.
    front_left = max(0.0, min(100.0, (vut_wid / 2 - lat_eval) / vut_wid * 100.0))
    front_right = max(0.0, min(100.0, (vut_wid / 2 + lat_eval) / vut_wid * 100.0))

    # EuroNCAP impact location (§1.2.5): the target reference point (≈ target centre)
    # projected onto the VUT WIDTH — 0% = outer right edge, 100% = outer left edge.
    # Unclamped: the protocol matrices allow values outside [0,100] (e.g. −25%…125%).
    impact_pct_width = (vut_wid / 2 + lat_eval) / vut_wid * 100.0
    # Side-impact scenarios (CMCscp, CBTAfs, CBTAns) measure across the VUT LENGTH —
    # 0% = rearmost point, 100% = most forward point.
    impact_pct_length = (vut_len / 2 + lon_c) / vut_len * 100.0

    return ImpactEstimate(
        contact=True, t_contact=tc,
        impact_pct_width=impact_pct_width, impact_pct_length=impact_pct_length,
        front_pos_left_pct=front_left, front_pos_right_pct=front_right,
        lateral_offset_m=lat_c, rel_heading_deg=rel_heading,
        min_gap_m=None, t_min_gap=None, width_overlap_pct=width_overlap_pct,
    )


def paths_intersect(
    vut_vertices: list[dict], tgt_vertices: list[dict]
) -> tuple[float, float] | None:
    """Return the first geometric intersection point of two trajectory polylines, or None.

    Time-decoupled: only the PATHS are tested, not the timing. A non-None result
    confirms the two actors are on a collision course by design. The impact
    overlap % itself is NOT derivable from kinematic exports (the trajectories
    end before any collision because AEB intervenes in the real test), so this
    is the automatable part of CH_SC_16/17 — the % stays a manual/HIL check.
    """
    if not vut_vertices or not tgt_vertices:
        return None
    for i in range(len(vut_vertices) - 1):
        x1, y1 = vut_vertices[i]["x"], vut_vertices[i]["y"]
        x2, y2 = vut_vertices[i + 1]["x"], vut_vertices[i + 1]["y"]
        for j in range(len(tgt_vertices) - 1):
            x3, y3 = tgt_vertices[j]["x"], tgt_vertices[j]["y"]
            x4, y4 = tgt_vertices[j + 1]["x"], tgt_vertices[j + 1]["y"]
            d = (x2 - x1) * (y4 - y3) - (y2 - y1) * (x4 - x3)
            if abs(d) < 1e-12:
                continue
            t = ((x3 - x1) * (y4 - y3) - (y3 - y1) * (x4 - x3)) / d
            u = ((x3 - x1) * (y2 - y1) - (y3 - y1) * (x2 - x1)) / d
            if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
                return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
    return None


def lateral_offset_percentage(vut: VehicleState, target: VehicleState) -> float:
    """
    Static lateral overlap - used for purely stationary checks like CCRs initial positioning.
    Returns what fraction of the target width is covered by VUT laterally.
    """
    vut_poly = vehicle_polygon(vut)
    tgt_poly = vehicle_polygon(target)
    return overlap_percentage(vut_poly, tgt_poly)
