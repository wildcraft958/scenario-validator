"""Geometric impact-location estimation for EuroNCAP impact-percentage checks.

The validator's USP: RoadRunner kinematic exports are the UNBRAKED design paths,
so stepping both actors through their exported trajectories and intersecting their
bounding boxes finds the designed first-contact geometry — pre-HIL design feedback
the RoadRunner GUI cannot show.

Impact location follows EuroNCAP Protocol Crash Avoidance Frontal Collisions v1.1
§1.2.5: the position of the target reference point across the VUT WIDTH (0% = outer
right edge, 100% = outer left edge); side-impact scenarios (CMCscp, CBTAfs, CBTAns)
use the VUT LENGTH (0% = rearmost, 100% = forwardmost).

CH_SC_16 (turning/crossing): ±5% tolerance.  CH_SC_17 (longitudinal/head-on): ±1%.
"""
from __future__ import annotations

import math
from typing import NamedTuple

from shapely.affinity import rotate, translate
from shapely.geometry import box


class ImpactEstimate(NamedTuple):
    """Result of estimate_trajectory_impact().

    EuroNCAP impact-location convention (§1.2.5): the impact location is WHERE the
    target reference point coincides with the %-age of the VUT width — 0% = outer
    RIGHT edge, 100% = outer LEFT edge (50% = centreline). Side-impact scenarios
    (CMCscp, CBTAfs, CBTAns) use the VUT LENGTH instead — 0% = rearmost,
    100% = forwardmost. Values may fall outside [0, 100] (the protocol matrices use
    −25%…125%), so neither axis is clamped.
    """
    contact: bool
    t_contact: float | None            # first bbox-touch instant (s), None if no contact
    impact_pct_width: float | None     # struck point across VUT WIDTH (0%=right edge,100%=left)
    impact_pct_length: float | None    # struck point across VUT LENGTH (0%=rear,100%=front) — side impacts
    lateral_offset_m: float | None     # target centre lateral offset in VUT frame at contact
    rel_heading_deg: float | None      # |target heading − VUT heading| at contact
    min_gap_m: float | None            # closest approach when no contact
    t_min_gap: float | None


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

    Steps both actors through time (linear interpolation between trajectory vertices)
    and intersects their exported bounding boxes to find the designed first-contact
    instant, then computes the §1.2.5 impact location by pure geometry:
      - impact_pct_width  = position of the target reference point across the VUT
        WIDTH (0% = outer right edge, 100% = outer left edge). For Pedestrian targets
        the reference point is evaluated at the instant the target CENTRE crosses the
        VUT front plane (protocol convention); for other targets at the contact instant.
      - impact_pct_length = the same across the VUT LENGTH (0% = rear, 100% = front) —
        the side-impact axis (CMCscp, CBTAfs, CBTAns). The caller selects the axis.

    Neither axis is clamped (the protocol matrices allow values outside [0, 100]).

    Caveat: constant-trajectory kinematics, no physics — design verification only;
    HIL remains the final authority. Returns None when either vertex list is empty.
    """
    if not vut_verts or not tgt_verts:
        return None

    t0 = max(vut_verts[0]["time"], tgt_verts[0]["time"])
    t1 = min(vut_verts[-1]["time"], tgt_verts[-1]["time"])
    if t1 <= t0:
        return None

    vut_len = vut_bbox[2]
    vut_wid = vut_bbox[3]
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

    # EuroNCAP impact location (§1.2.5): the target reference point (≈ target centre)
    # projected onto the VUT WIDTH — 0% = outer right edge, 100% = outer left edge.
    # Side-impact scenarios measure across the VUT LENGTH — 0% = rearmost, 100% = front.
    # Unclamped: the protocol matrices allow values outside [0, 100].
    impact_pct_width = (vut_wid / 2 + lat_eval) / vut_wid * 100.0
    impact_pct_length = (vut_len / 2 + lon_c) / vut_len * 100.0

    return ImpactEstimate(
        contact=True, t_contact=tc,
        impact_pct_width=impact_pct_width, impact_pct_length=impact_pct_length,
        lateral_offset_m=lat_c, rel_heading_deg=rel_heading,
        min_gap_m=None, t_min_gap=None,
    )


def paths_intersect(
    vut_vertices: list[dict], tgt_vertices: list[dict]
) -> tuple[float, float] | None:
    """Return the first geometric intersection point of two trajectory polylines, or None.

    Time-decoupled: only the PATHS are tested, not the timing. A non-None result
    confirms the two actors are on a collision course by design. The impact location %
    itself IS estimated geometrically by estimate_trajectory_impact (design-time; HIL
    remains the final authority); this function is only the collision-course fallback
    note used when the impact estimate cannot be computed.
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
