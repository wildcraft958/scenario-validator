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
    lateral_offset_m: float | None     # target reference-point lateral offset in VUT frame at contact
    rel_heading_deg: float | None      # |target heading − VUT heading| at contact
    min_gap_m: float | None            # closest approach when no contact
    t_min_gap: float | None
    # How much the impact % moves between first bbox-contact and the impact-plane crossing.
    # High = the geometry is rotating/corner-first (§1.2.5.2) so the kinematic estimate
    # cannot pin the location precisely → the caller downgrades the verdict to MANUAL_REVIEW.
    eval_sensitivity_pct: float | None = None
    # Rotation-robust §1.2.5.2 fallback: the lateral centre of the TARGET footprint over the
    # VUT extent at first contact (width axis, or length axis for side impacts). When the
    # heading-rotation corner-first effect makes the reference-point reading sweep wildly, this
    # overlap-centre stays stable and recovers the protocol impact-location (the front edges
    # meeting with the designed overlap of the VUT width). overlap_sensitivity_pct is its own
    # ±0.1 s swing — the caller switches to it only when it is steadier than the reference point.
    impact_pct_width_overlap: float | None = None
    impact_pct_length_overlap: float | None = None
    overlap_sensitivity_pct: float | None = None


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
    ref_offset: tuple[float, float] = (0.0, 0.0),
    side_impact: bool = False,
    dt: float = 0.05,
) -> ImpactEstimate | None:
    """Estimate the impact geometry from kinematic (unbraked) design trajectories.

    Steps both actors through time (linear interpolation between trajectory vertices)
    and intersects their exported bounding boxes to find the designed first-contact
    instant, then computes the §1.2.5 impact location by pure geometry.

    `ref_offset` is the EuroNCAP TARGET REFERENCE POINT as a fraction of the target
    (length, width) measured from the bbox centre, in the target body frame. It differs
    by actor AND motion type (§1.2.5 / §1.4.1): e.g. GVT rear (−0.5, 0) for Car-to-Car
    Rear, cyclist front wheel (+0.4, 0) for turning, pedestrian hip (0, 0) for turning.
    The caller (resolve_actor + target_reference_offset) supplies it; the default (0, 0)
    is the bbox centre.

      - impact_pct_width  = the reference point across the VUT WIDTH (0% = outer right
        edge, 100% = outer left), read when the reference point reaches the VUT FRONT
        profile plane (reading at reference-point coincidence, not the first bbox-corner
        touch — §1.2.5.2).
      - impact_pct_length = the reference point across the VUT LENGTH (0% = rear,
        100% = front) when `side_impact` is set (CMCscp, CBTAfs, CBTAns), read when the
        reference point reaches the struck VUT SIDE plane.

    Neither axis is clamped (the protocol matrices allow −25%…125%). The % scale is the
    FULL vehicle width/length — §1.2.5 fixes 0%/100% at the vehicle edges; the §1.3.1
    50 mm profiled-line inset is contact geometry, not the % scale.

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
    # Target reference point in the target body frame (lon = +front, lat = +left).
    ref_lon = tgt_bbox[0] + ref_offset[0] * tgt_bbox[2]
    ref_lat = tgt_bbox[1] + ref_offset[1] * tgt_bbox[3]
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

    def ref_in_vut(t_eval: float) -> tuple[float, float, float, float]:
        """(longitudinal, lateral) of the TARGET REFERENCE POINT in the VUT frame + headings."""
        vx, vy, vh = _interp(vut_verts, t_eval)
        gx, gy, gh = _interp(tgt_verts, t_eval)
        # reference point in world: rotate the body-frame offset by the target heading
        rx = gx + ref_lon * math.cos(gh) - ref_lat * math.sin(gh)
        ry = gy + ref_lon * math.sin(gh) + ref_lat * math.cos(gh)
        dx, dy = rx - vx, ry - vy
        lon = dx * math.cos(vh) + dy * math.sin(vh)
        lat = -dx * math.sin(vh) + dy * math.cos(vh)
        return lon, lat, vh, gh

    lon_c, lat_c, vh_c, gh_c = ref_in_vut(tc)
    rel_heading = math.degrees(abs(gh_c - vh_c)) % 360.0
    if rel_heading > 180.0:
        rel_heading = 360.0 - rel_heading

    # EuroNCAP impact location (§1.2.5): the target reference point projected onto the VUT
    # WIDTH (0% = outer right edge, 100% = outer left) at the IMPACT (first-contact) instant;
    # for side impacts onto the VUT LENGTH (0% = rearmost, 100% = foremost). Scaled to the
    # FULL vehicle width/length (§1.2.5 fixes 0%/100% at the vehicle edges). For a
    # perpendicular crosser first contact ≈ the reference point reaching the VUT front, so a
    # single instant suffices; the sensitivity below guards the rotating/corner-first cases.
    impact_pct_width = (vut_wid / 2 + lat_c) / vut_wid * 100.0
    impact_pct_length = (vut_len / 2 + lon_c) / vut_len * 100.0

    # Reliability = how much the impact % moves across ±the protocol SCP sync tolerance
    # (±0.1 s, §1.2.3) around the contact instant. High = rotating / fast geometry where the
    # kinematics cannot pin the location within the sync window (§1.2.5.2 corner-first) → the
    # caller downgrades to MANUAL_REVIEW rather than trust the number.
    w = max(dt, 0.1)
    lon_a, lat_a, _, _ = ref_in_vut(max(t0, tc - w))
    lon_b, lat_b, _, _ = ref_in_vut(min(t1, tc + w))
    if side_impact:
        eval_sensitivity_pct = abs((lon_b - lon_a) / vut_len * 100.0)
    else:
        eval_sensitivity_pct = abs((lat_b - lat_a) / vut_wid * 100.0)

    # Rotation-robust §1.2.5.2 overlap-centre metric. In heading-rotation / high-closing-speed
    # impacts (turn-across-path) the corner edge contacts BEFORE the target reference point
    # reaches the impact location, so the single-point reference reading sweeps across the whole
    # VUT width in the sync window (high eval_sensitivity_pct above). The overlap CENTRE — the
    # lateral midpoint of where the target footprint covers the VUT extent — is stable through
    # that corner-first transient and recovers the protocol impact location (EuroNCAP AEB C2C:
    # "the front edges meet with a lateral position that gives the designed overlap of the VUT
    # width", reference line = VUT centreline). The caller uses it only when it is steadier than
    # the reference point (so small/slow VRU targets keep the precise reference-point reading).
    def overlap_centers(t_eval: float) -> tuple[float | None, float | None]:
        vx, vy, vh = _interp(vut_verts, t_eval)
        gx, gy, gh = _interp(tgt_verts, t_eval)
        cx, cy, tl, tw = tgt_bbox
        lons: list[float] = []
        lats: list[float] = []
        for sx in (-0.5, 0.5):
            for sy in (-0.5, 0.5):
                bx, by = cx + sx * tl, cy + sy * tw
                wx = gx + bx * math.cos(gh) - by * math.sin(gh)
                wy = gy + bx * math.sin(gh) + by * math.cos(gh)
                dx, dy = wx - vx, wy - vy
                lons.append(dx * math.cos(vh) + dy * math.sin(vh))
                lats.append(-dx * math.sin(vh) + dy * math.cos(vh))
        wlo, whi = max(min(lats), -vut_wid / 2), min(max(lats), vut_wid / 2)
        llo, lhi = max(min(lons), -vut_len / 2), min(max(lons), vut_len / 2)
        w_pct = (vut_wid / 2 + (wlo + whi) / 2) / vut_wid * 100.0 if whi > wlo else None
        l_pct = (vut_len / 2 + (llo + lhi) / 2) / vut_len * 100.0 if lhi > llo else None
        return w_pct, l_pct

    ow_c, ol_c = overlap_centers(tc)
    oa_w, oa_l = overlap_centers(max(t0, tc - w))
    ob_w, ob_l = overlap_centers(min(t1, tc + w))
    active = (ol_c, oa_l, ob_l) if side_impact else (ow_c, oa_w, ob_w)
    overlap_sensitivity_pct = (
        abs(active[2] - active[1]) if active[1] is not None and active[2] is not None else None
    )

    return ImpactEstimate(
        contact=True, t_contact=tc,
        impact_pct_width=impact_pct_width, impact_pct_length=impact_pct_length,
        lateral_offset_m=lat_c, rel_heading_deg=rel_heading,
        min_gap_m=None, t_min_gap=None,
        eval_sensitivity_pct=eval_sensitivity_pct,
        impact_pct_width_overlap=ow_c, impact_pct_length_overlap=ol_c,
        overlap_sensitivity_pct=overlap_sensitivity_pct,
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
