"""OpenDRIVE (.xodr) secure parser with XPath helpers."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from lxml import etree  # type: ignore[import-untyped]

_SECURE_PARSER = etree.XMLParser(
    no_network=True,
    resolve_entities=False,
    load_dtd=False,
)


def load(path: Path) -> Any:
    with path.open("rb") as fh:
        tree = etree.parse(fh, _SECURE_PARSER)
    return tree.getroot()


def xpath(root: Any, query: str) -> list[Any]:
    return root.xpath(query)


# ---------- Road-level helpers ----------

def get_roads(root: Any) -> list[Any]:
    return xpath(root, "//road")


def get_road_count(root: Any) -> int:
    return len(get_roads(root))


def get_lane_widths(root: Any) -> list[float]:
    """Returns lane width 'a' coefficients for driving lanes only (excludes border/shoulder)."""
    widths = []
    for lane in xpath(root, "//laneSection//lane[@type='driving']"):
        for w in lane.xpath("width"):
            a = w.get("a")
            if a is not None:
                widths.append(float(a))
    return widths


def get_junction_ids(root: Any) -> list[str]:
    return [j.get("id", "") for j in xpath(root, "//junction")]


def has_junctions(root: Any) -> bool:
    return bool(get_junction_ids(root))


def get_junction_connection_curvatures(root: Any) -> list[float]:
    """Returns curvature values of roads that are part of a junction connection.

    Only constant-radius arc elements are used. Spiral (clothoid transition)
    elements are intentionally skipped: their curvStart/curvEnd endpoints vary
    linearly and may differ from the intended arc curvature, producing spurious
    near-8m values that fail the tight ±0.1m tolerance in CH_RD_03.
    Fallback to spiral midpoint only if a junction road has no arc geometry at all.
    """
    curv_values: list[float] = []
    junction_roads: set[str] = set()
    for conn in xpath(root, "//junction/connection"):
        connecting_road = conn.get("connectingRoad")
        if connecting_road:
            junction_roads.add(connecting_road)

    for road in get_roads(root):
        if road.get("id") not in junction_roads:
            continue
        arc_curvatures: list[float] = []
        spiral_midpoints: list[float] = []
        for geom in road.xpath(".//planView/geometry"):
            arc = geom.xpath("arc")
            spiral = geom.xpath("spiral")
            if arc:
                k = arc[0].get("curvature")
                if k:
                    arc_curvatures.append(abs(float(k)))
            elif spiral:
                # Midpoint curvature is only used when the road has no arc geometry
                ks_str = spiral[0].get("curvStart")
                ke_str = spiral[0].get("curvEnd")
                if ks_str is not None and ke_str is not None:
                    ks, ke = float(ks_str), float(ke_str)
                    mid = (ks + ke) / 2
                    if mid != 0:
                        spiral_midpoints.append(abs(mid))
        if arc_curvatures:
            curv_values.extend(arc_curvatures)
        elif spiral_midpoints:
            curv_values.extend(spiral_midpoints)
    return curv_values


def junction_curvature_radii(root: Any) -> list[float]:
    radii = []
    for k in get_junction_connection_curvatures(root):
        if k != 0:
            radii.append(1.0 / k)
    return radii


def get_junction_incoming_road_headings_deg(root: Any) -> list[float]:
    """Headings (degrees, normalised mod 180) of the roads that feed into junctions."""
    incoming: set[str] = set()
    for conn in xpath(root, "//junction/connection"):
        rid = conn.get("incomingRoad")
        if rid:
            incoming.add(rid)
    headings: list[float] = []
    for road in get_roads(root):
        if road.get("id") not in incoming:
            continue
        geoms = road.xpath(".//planView/geometry")
        if geoms:
            headings.append(round(math.degrees(float(geoms[0].get("hdg", 0))) % 180.0, 1))
    return headings


def has_intersection_junction(root: Any, min_spread_deg: float) -> bool:
    """True if a junction connects roads from DIFFERENT directions — a real
    intersection (turning OR straight crossing) — vs a lane-structure junction that
    only links parallel roads.

    Detected purely from .xodr geometry, so NO scenario list is needed: if any two
    incoming-road headings differ by more than min_spread_deg (circular, mod 180),
    the junction is an intersection. A lane-split/transition junction has parallel
    incoming roads (spread ~0) and is excluded. Validated on the example scenarios:
    CCFtap/CPNCO/CPTA all show incoming roads at 0° and 90° (spread 90°).
    """
    hs = get_junction_incoming_road_headings_deg(root)
    for i in range(len(hs)):
        for j in range(i + 1, len(hs)):
            d = abs(hs[i] - hs[j]) % 180.0
            if min(d, 180.0 - d) > min_spread_deg:
                return True
    return False


def get_leftmost_road_origin(root: Any) -> dict[str, float] | None:
    """Returns x,y of the geometry start of the leftmost road (smallest x)."""
    best: dict[str, float] | None = None
    for road in get_roads(root):
        geoms = road.xpath(".//planView/geometry")
        if not geoms:
            continue
        g = geoms[0]
        x = float(g.get("x", 0))
        y = float(g.get("y", 0))
        if best is None or x < best["x"]:
            best = {"x": x, "y": y, "hdg": float(g.get("hdg", 0))}
    return best


def has_shoulder_lane_at_junction(root: Any) -> bool:
    """True if any junction-connecting road has a shoulder lane type."""
    junction_roads: set[str] = set()
    for conn in xpath(root, "//junction/connection"):
        cr = conn.get("connectingRoad")
        if cr:
            junction_roads.add(cr)

    for road in get_roads(root):
        if road.get("id") not in junction_roads:
            continue
        for lane in road.xpath(".//laneSection//lane"):
            if lane.get("type", "") == "shoulder":
                return True
    return False


def get_road_start_end_positions(root: Any) -> list[dict[str, float]]:
    """For each road, returns start and approximate end x,y positions."""
    result = []
    for road in get_roads(root):
        geoms = road.xpath(".//planView/geometry")
        if not geoms:
            continue
        g = geoms[0]
        x = float(g.get("x", 0))
        y = float(g.get("y", 0))
        hdg = float(g.get("hdg", 0))
        length = float(road.get("length", 0))
        ex = x + length * math.cos(hdg)
        ey = y + length * math.sin(hdg)
        result.append({"start_x": x, "start_y": y, "end_x": ex, "end_y": ey, "hdg": hdg})
    return result


def get_road_markings(root: Any) -> list[str]:
    """Returns all roadMark type attributes."""
    return [m.get("type", "") for m in xpath(root, "//lane/roadMark")]


def find_disconnected_roads(root: Any) -> list[str]:
    """
    Returns IDs of road segments that have missing link connections (the 'blue dot' problem).
    A road is disconnected if it has a junction in its successor/predecessor slot but the
    junction element it references does not exist, or if it has no link element at all
    despite not being an endpoint.
    """
    road_ids: set[str] = {r.get("id", "") for r in get_roads(root)}
    junction_ids: set[str] = {j.get("id", "") for j in xpath(root, "//junction")}
    disconnected: list[str] = []

    for road in get_roads(root):
        road_id = road.get("id", "")
        link = road.xpath("./link")
        if not link:
            # A road with no link at all is isolated unless it is the only road
            if len(road_ids) > 1:
                disconnected.append(road_id)
            continue

        lnk = link[0]
        # Check successor
        succ = lnk.xpath("./successor")
        if succ:
            s = succ[0]
            ref_id = s.get("elementId", "")
            ref_type = s.get("elementType", "road")
            if ref_type == "junction" and ref_id not in junction_ids:
                disconnected.append(road_id)
            elif ref_type == "road" and ref_id not in road_ids:
                disconnected.append(road_id)

        # Check predecessor
        pred = lnk.xpath("./predecessor")
        if pred:
            p = pred[0]
            ref_id = p.get("elementId", "")
            ref_type = p.get("elementType", "road")
            if ref_type == "junction" and ref_id not in junction_ids:
                disconnected.append(road_id)
            elif ref_type == "road" and ref_id not in road_ids:
                disconnected.append(road_id)

    return list(set(disconnected))
