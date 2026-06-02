"""OpenDRIVE (.xodr) secure parser with XPath helpers."""
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

from lxml import etree  # type: ignore[import-untyped]

log = logging.getLogger(__name__)

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
    """Returns curvature values of roads that are part of a junction connection."""
    curv_values: list[float] = []
    junction_roads: set[str] = set()
    for conn in xpath(root, "//junction/connection"):
        connecting_road = conn.get("connectingRoad")
        if connecting_road:
            junction_roads.add(connecting_road)

    for road in get_roads(root):
        if road.get("id") not in junction_roads:
            continue
        for geom in road.xpath(".//planView/geometry"):
            arc = geom.xpath("arc")
            spiral = geom.xpath("spiral")
            if arc:
                k = arc[0].get("curvature")
                if k:
                    curv_values.append(abs(float(k)))
            elif spiral:
                ks = spiral[0].get("curvStart")
                ke = spiral[0].get("curvEnd")
                for k in [ks, ke]:
                    if k and float(k) != 0:
                        curv_values.append(abs(float(k)))
    return curv_values


def junction_curvature_radii(root: Any) -> list[float]:
    radii = []
    for k in get_junction_connection_curvatures(root):
        if k != 0:
            radii.append(1.0 / k)
    return radii


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
