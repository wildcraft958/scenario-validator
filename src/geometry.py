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


def _interp_vertex(vertices: list[dict], t: float) -> tuple[float, float, float]:
    """Linear interpolation of (x, y, h) from a trajectory vertex list at time t."""
    if not vertices:
        return 0.0, 0.0, 0.0
    if t <= vertices[0]["time"]:
        v = vertices[0]
        return v["x"], v["y"], v["h"]
    if t >= vertices[-1]["time"]:
        v = vertices[-1]
        return v["x"], v["y"], v["h"]
    for i in range(1, len(vertices)):
        t0, t1 = vertices[i - 1]["time"], vertices[i]["time"]
        if t0 <= t <= t1:
            if t1 == t0:
                v = vertices[i]
                return v["x"], v["y"], v["h"]
            frac = (t - t0) / (t1 - t0)
            v0, v1 = vertices[i - 1], vertices[i]
            # Heading interpolation: handle wrap-around
            dh = v1["h"] - v0["h"]
            while dh > math.pi:
                dh -= 2 * math.pi
            while dh < -math.pi:
                dh += 2 * math.pi
            return (
                v0["x"] + frac * (v1["x"] - v0["x"]),
                v0["y"] + frac * (v1["y"] - v0["y"]),
                v0["h"] + frac * dh,
            )
    v = vertices[-1]
    return v["x"], v["y"], v["h"]


def compute_kinematic_impact_pct(
    vut_vertices: list[dict],
    tgt_vertices: list[dict] | None,
    tgt_init: VehicleState | None,
    vut_dims: tuple[float, float],
    tgt_dims: tuple[float, float],
) -> float:
    """Compute max bounding-box overlap % using actual trajectory positions.

    This is the USP of the validator: no other RR-export tool reconstructs the
    physical impact geometry from kinematic vertex data without running a full
    simulation. Both VUT and target positions are stepped through their trajectory
    vertex timestamps; the maximum bounding-box overlap across all steps is returned.

    Algorithm:
      For each VUT trajectory timestep t:
        - VUT position: from vut_vertices (exact)
        - Target position: interpolated from tgt_vertices if available,
          else extrapolated as tgt_init + speed * t (constant heading)
      Build shapely bounding boxes for both; return max overlap_percentage().

    Args:
        vut_vertices:  [{time, x, y, h}, ...] from xosc Polyline
        tgt_vertices:  target trajectory or None
        tgt_init:      VehicleState for constant-speed extrapolation fallback
        vut_dims:      (length, width) in metres
        tgt_dims:      (length, width) in metres
    """
    if not vut_vertices:
        return 0.0

    vut_len, vut_wid = vut_dims
    tgt_len, tgt_wid = tgt_dims

    best_overlap = 0.0

    for v in vut_vertices:
        t = v["time"]
        vut_state = VehicleState(
            x=v["x"], y=v["y"],
            heading_deg=math.degrees(v["h"]),
            length=vut_len, width=vut_wid,
        )

        if tgt_vertices:
            tx, ty, th = _interp_vertex(tgt_vertices, t)
            tgt_state = VehicleState(
                x=tx, y=ty,
                heading_deg=math.degrees(th),
                length=tgt_len, width=tgt_wid,
            )
        elif tgt_init is not None:
            hdg_rad = math.radians(tgt_init.heading_deg)
            tgt_state = VehicleState(
                x=tgt_init.x + math.cos(hdg_rad) * tgt_init.speed_ms * t,
                y=tgt_init.y + math.sin(hdg_rad) * tgt_init.speed_ms * t,
                heading_deg=tgt_init.heading_deg,
                length=tgt_len, width=tgt_wid,
                speed_ms=tgt_init.speed_ms,
            )
        else:
            continue

        vut_poly = vehicle_polygon(vut_state)
        tgt_poly = vehicle_polygon(tgt_state)
        ov = overlap_percentage(vut_poly, tgt_poly)
        if ov > best_overlap:
            best_overlap = ov

    return best_overlap


def lateral_offset_percentage(vut: VehicleState, target: VehicleState) -> float:
    """
    Static lateral overlap - used for purely stationary checks like CCRs initial positioning.
    Returns what fraction of the target width is covered by VUT laterally.
    """
    vut_poly = vehicle_polygon(vut)
    tgt_poly = vehicle_polygon(target)
    return overlap_percentage(vut_poly, tgt_poly)
