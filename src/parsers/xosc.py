"""OpenSCENARIO (.xosc) secure parser with XPath helpers."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from lxml import etree  # type: ignore[import-untyped]

# Secure lxml parser: no network, no external entity resolution
_SECURE_PARSER = etree.XMLParser(
    no_network=True,
    resolve_entities=False,
    load_dtd=False,
)


def load(path: Path) -> Any:
    with path.open("rb") as fh:
        tree = etree.parse(fh, _SECURE_PARSER)
    return tree.getroot()


def _safe_float(value: str | None) -> float | None:
    """Convert a string to float, returning None for parameter references (e.g. '$speed')."""
    if value is None:
        return None
    value = value.strip()
    if value.startswith("$") or value.startswith("%"):
        return None  # parameter reference, not a literal value
    try:
        return float(value)
    except ValueError:
        return None


def xpath(root: Any, query: str, **kwargs: Any) -> list[Any]:
    """Execute an XPath query. Pass entity names as kwargs to avoid XPath injection.

    Example: xpath(root, "//Private[@entityRef=$name]", name=entity_name)
    lxml evaluates $variable references safely without string interpolation.
    """
    return root.xpath(query, **kwargs)


def xpath_one(root: Any, query: str, default: Any = None) -> Any:
    results = root.xpath(query)
    return results[0] if results else default


# ---------- high-level extractors ----------

def get_scenario_name(root: Any) -> str:
    return xpath_one(root, "//FileHeader/@description") or xpath_one(root, "//FileHeader/@author") or ""


def get_entities(root: Any) -> list[Any]:
    return xpath(root, "//Entities/ScenarioObject")


def get_entity_name(entity: Any) -> str:
    return entity.get("name", "")


def get_entity_bbox(root: Any, entity_name: str) -> tuple[float, float, float, float] | None:
    """Returns (center_x, center_y, length, width) from the entity's BoundingBox, or None.

    RoadRunner exports a BoundingBox per entity with Center x=0 y=0 - i.e. the
    WorldPosition IS the bounding-box centre. Values are parsed defensively;
    parameterized ($ref) values yield None.
    """
    for obj in xpath(root, "//ScenarioObject[@name=$name]", name=entity_name):
        for bb in obj.xpath(".//BoundingBox"):
            center = bb.xpath("Center")
            dims = bb.xpath("Dimensions")
            if not center or not dims:
                continue
            cx = _safe_float(center[0].get("x"))
            cy = _safe_float(center[0].get("y"))
            length = _safe_float(dims[0].get("length"))
            width = _safe_float(dims[0].get("width"))
            if length is not None and width is not None:
                return (cx or 0.0, cy or 0.0, length, width)
    return None


def get_entity_category(root: Any, entity_name: str) -> str:
    """Returns 'Vehicle', 'Pedestrian', 'MiscObject' or '' for a ScenarioObject."""
    for obj in xpath(root, "//ScenarioObject[@name=$name]", name=entity_name):
        for tag in ("Vehicle", "Pedestrian", "MiscObject"):
            if obj.xpath(f"./{tag}"):
                return tag
    return ""


def get_init_positions(root: Any) -> dict[str, dict[str, float]]:
    """Returns {entity_name: {x, y, z, h}} from Init section.
    Skips entities whose positions are parameter references.
    """
    positions: dict[str, dict[str, float]] = {}
    for action in xpath(root, "//Init//Private"):
        name = action.get("entityRef", "")
        wp = action.xpath(".//WorldPosition")
        if wp:
            w = wp[0]
            x = _safe_float(w.get("x", "0"))
            y = _safe_float(w.get("y", "0"))
            z = _safe_float(w.get("z", "0"))
            h = _safe_float(w.get("h", "0"))
            if x is not None and y is not None:
                positions[name] = {"x": x, "y": y, "z": z or 0.0, "h": h or 0.0}
    return positions


def get_init_positioned_entities(root: Any) -> set[str]:
    """Returns names of entities that have ANY Init position element.

    Covers WorldPosition, LanePosition, RelativeLanePosition, RoadPosition,
    RelativeRoadPosition, RelativeWorldPosition, RoutePosition, etc. - so an
    entity placed via a non-World position still counts as 'positioned'
    (presence check; exact x,y may need .xodr resolution).
    """
    named: set[str] = set()
    for priv in xpath(root, "//Init//Private"):
        name = priv.get("entityRef", "")
        if name and priv.xpath(".//*[contains(local-name(), 'Position')]"):
            named.add(name)
    return named


def get_init_speed(root: Any, entity_name: str) -> float | None:
    """Returns the initial speed set via AbsoluteTargetSpeed in Init for an entity.
    Returns None if value is a parameter reference (e.g. '$speed').
    """
    for priv in xpath(root, "//Init//Private[@entityRef=$name]", name=entity_name):
        speed_nodes = priv.xpath(".//AbsoluteTargetSpeed/@value")
        if speed_nodes:
            return _safe_float(speed_nodes[0])
    return None


def get_simulation_time(root: Any) -> float | None:
    """Looks for SimulationTimeCondition value used as a stop trigger."""
    vals = xpath(root, "//StopTrigger//SimulationTimeCondition/@value")
    if vals:
        return _safe_float(vals[0])
    # Fallback: look anywhere
    vals = xpath(root, "//SimulationTimeCondition/@value")
    return _safe_float(vals[0]) if vals else None


def get_parameter_declarations(root: Any) -> list[dict[str, str]]:
    params = []
    for p in xpath(root, "//ParameterDeclarations/ParameterDeclaration"):
        params.append({
            "name": p.get("name", ""),
            "type": p.get("parameterType", ""),
            "value": p.get("value", ""),
        })
    return params


def has_anchor(root: Any, entity_name: str) -> bool:
    """Returns True if entity has anchoring enabled."""
    for obj in xpath(root, "//ScenarioObject[@name=$name]", name=entity_name):
        controllers = obj.xpath(".//Controller//Properties//Property")
        for prop in controllers:
            if prop.get("name", "").lower() == "anchor" and prop.get("value", "false").lower() != "false":
                return True
    return False


def get_timing_data_mode(root: Any) -> str | None:
    """Returns the RelativeTo mode for Waypoint timing in action phase."""
    vals = xpath(root, "//Timing/@domainAbsoluteRelative")
    return vals[0] if vals else None


def get_route_timing_data_option(root: Any) -> bool:
    """True if timing data option is checked in RoutingAction."""
    # In OpenSCENARIO, the presence of Timing element under FollowTrajectoryAction
    return bool(xpath(root, "//FollowTrajectoryAction//TimeReference//Timing"))


def get_entity_lane_positions(root: Any) -> dict[str, dict]:
    """Returns lane position data for entities from Init LanePosition."""
    result = {}
    for priv in xpath(root, "//Init//Private"):
        name = priv.get("entityRef", "")
        lp = priv.xpath(".//LanePosition")
        if lp:
            el = lp[0]
            lane_id_raw = el.get("laneId", "0")
            if lane_id_raw and lane_id_raw.startswith("$"):
                lane_id = None  # parameterized - caller must handle as MANUAL_REVIEW
            else:
                lane_id = int(lane_id_raw) if lane_id_raw else 0
            result[name] = {
                "road_id": el.get("roadId", ""),
                "lane_id": lane_id,
                "s": _safe_float(el.get("s", "0")) or 0.0,
                "offset": _safe_float(el.get("offset", "0")) or 0.0,
            }
    return result


def get_actors_ordered(root: Any) -> list[str]:
    """Returns actor names in story/act order - VUT should be first."""
    seen: list[str] = []
    for ref in xpath(root, "//Story//Act//ManeuverGroup//EntityRef/@entityRef"):
        if ref not in seen:
            seen.append(ref)
    return seen


def get_entity_catalog_filepaths(root: Any) -> dict[str, tuple[str, str]]:
    """
    Returns {entity_name: (path_or_ref, source_type)} for all ScenarioObjects.

    source_type is "model3d" when the path is an inline asset reference, or "catalog"
    when it comes from a CatalogReference element. Used by CH_SC_22 to verify assets
    are in the NCAP Asset folder.

    RoadRunner exports model3d as a direct XML attribute on the entity element:
      <Vehicle model3d="NCAP Assets/..." ...>
    OpenSCENARIO also supports it via Properties/Property or CatalogReference.
    All three forms are checked in priority order.
    """
    result: dict[str, tuple[str, str]] = {}
    for obj in xpath(root, "//ScenarioObject"):
        name = obj.get("name", "")
        # 1. Direct model3d attribute on Vehicle/Pedestrian/MiscObject (RoadRunner exports)
        for entity in obj.xpath("./Vehicle | ./Pedestrian | ./MiscObject"):
            m3d = entity.get("model3d")
            if m3d:
                result[name] = (m3d, "model3d")
                break
        if name in result:
            continue
        # 2. Properties > Property filepath/model3d (parametric OpenSCENARIO format)
        for prop in obj.xpath(".//Properties/Property"):
            if prop.get("name", "").lower() in ("filepath", "model3d", "model", "resource"):
                result[name] = (prop.get("value", ""), "model3d")
                break
        if name in result:
            continue
        # 3. CatalogReference (OpenSCENARIO catalog lookup)
        for cat_ref in obj.xpath(".//CatalogReference"):
            catalog = cat_ref.get("catalogName", "")
            entry = cat_ref.get("entryName", "")
            if catalog or entry:
                result[name] = (f"{catalog}/{entry}", "catalog")
                break
    return result


def get_parameter_value(root: Any, param_name: str) -> str | None:
    """Returns the default value of a ParameterDeclaration by name, or None."""
    for p in xpath(root, "//ParameterDeclarations/ParameterDeclaration[@name=$name]", name=param_name):
        return p.get("value")
    return None


def get_braking_decel_actions(root: Any) -> list[dict]:
    """Finds all linear-rate SpeedAction deceleration events in the Story (action phase).

    Returns list of dicts with keys:
      entity_name: str
      rate_ms2: float | None  (None when value is a parameter reference)
      param_name: str | None  (name of $param if parameterized)
      shape: str
      target_speed: float | None
    """
    results = []
    for mg in xpath(root, "//Story//Act//ManeuverGroup"):
        refs = [e.get("entityRef", "") for e in mg.xpath(".//EntityRef")]
        for dyn in mg.xpath(".//SpeedActionDynamics[@dynamicsDimension='rate'][@dynamicsShape='linear']"):
            raw_val = dyn.get("value", "")
            rate = _safe_float(raw_val)
            param_name: str | None = None
            if rate is None and raw_val.startswith("$"):
                param_ref = raw_val.lstrip("$")
                param_name = param_ref
                resolved = get_parameter_value(root, param_ref)
                rate = _safe_float(resolved)

            parent = dyn.getparent()
            target_nodes = parent.xpath(".//AbsoluteTargetSpeed/@value") if parent is not None else []
            target = _safe_float(target_nodes[0]) if target_nodes else None

            for ref in refs:
                if ref:
                    results.append({
                        "entity_name": ref,
                        "rate_ms2": rate,
                        "param_name": param_name,
                        "shape": dyn.get("dynamicsShape", ""),
                        "target_speed": target,
                    })
    return results


def get_trajectory_vertices(root: Any, entity_name: str) -> list[dict[str, float]]:
    """Returns list of {time, x, y, h} from Init FollowTrajectoryAction polyline vertices.

    RoadRunner kinematic exports store the full trajectory as a Polyline inside
    Init//Private//FollowTrajectoryAction rather than as ParameterDeclarations.
    """
    vertices: list[dict[str, float]] = []
    for priv in xpath(root, "//Init//Private[@entityRef=$name]", name=entity_name):
        for vertex in priv.xpath(".//FollowTrajectoryAction//Trajectory//Shape//Polyline//Vertex"):
            t = _safe_float(vertex.get("time", "0"))
            wp = vertex.xpath(".//WorldPosition")
            if wp and t is not None:
                x = _safe_float(wp[0].get("x", "0"))
                y = _safe_float(wp[0].get("y", "0"))
                h = _safe_float(wp[0].get("h", "0"))
                if x is not None and y is not None:
                    vertices.append({"time": t, "x": x, "y": y, "h": h or 0.0})
    return vertices


def get_trajectory_speed_kmh(root: Any, entity_name: str) -> float | None:
    """Computes peak cruise speed in km/h from Init trajectory vertex sequence.

    Takes the maximum speed observed over consecutive Vertex pairs, which
    represents the constant-speed cruise phase for RoadRunner kinematic scenarios.
    Returns None if fewer than two vertices are present.
    """
    import math
    vertices = get_trajectory_vertices(root, entity_name)
    if len(vertices) < 2:
        return None
    speeds = []
    for i in range(1, len(vertices)):
        dt = vertices[i]["time"] - vertices[i - 1]["time"]
        if dt <= 0:
            continue
        dx = vertices[i]["x"] - vertices[i - 1]["x"]
        dy = vertices[i]["y"] - vertices[i - 1]["y"]
        speeds.append(math.hypot(dx, dy) / dt * 3.6)
    return max(speeds) if speeds else None


def get_polyline_curvature_radii(
    root: Any,
    entity_name: str,
    min_heading_delta_rad: float = 0.01,
    min_segment_length_m: float = 0.01,
) -> list[float]:
    """Compute turning radii (m) from vertex heading changes in a polyline trajectory.

    Returns radii only for sections where the heading is actively changing (curved part).
    Straight sections (|dh| < min_heading_delta_rad) are excluded. Used by CH_SC_07 to
    verify constant-radius turns from RoadRunner polyline trajectories.
    """
    import math
    vertices = get_trajectory_vertices(root, entity_name)
    radii: list[float] = []
    for i in range(1, len(vertices)):
        dh = vertices[i]["h"] - vertices[i - 1]["h"]
        # Normalise to [-π, π] to handle wrap-around (e.g. -π → +π)
        while dh > math.pi:
            dh -= 2 * math.pi
        while dh < -math.pi:
            dh += 2 * math.pi
        dl = math.hypot(
            vertices[i]["x"] - vertices[i - 1]["x"],
            vertices[i]["y"] - vertices[i - 1]["y"],
        )
        if abs(dh) > min_heading_delta_rad and dl > min_segment_length_m:
            radii.append(dl / abs(dh))
    return radii


def get_polyline_part2_radius(
    root: Any,
    entity_name: str,
    min_heading_delta_rad: float = 0.01,
    min_segment_length_m: float = 0.01,
    part2_window_factor: float = 1.2,
    handedness: str = "LHT",
) -> tuple[float | None, str]:
    """Estimate the Part 2 (constant-radius arc) radius of a turning trajectory.

    The Clothoid-Arc-Clothoid path (Part1-Part2-Part3) has its smallest radius in
    Part 2. Filtering to radii within part2_window_factor × minimum isolates the
    constant arc and excludes the transition clothoid sections which have large
    apparent radii.

    Returns (radius_m, direction) where direction is "Farside" or "Nearside".
    Returns (None, "") when the trajectory has no clear curved section.

    Handedness convention (EuroNCAP Frontal v1.1 + ISO 8855):
      LHT (left-hand traffic, drive on left - UK/Japan/India, EuroNCAP default):
        positive net heading change (CCW, left turn) = Farside (away from driver)
        negative net heading change (CW, right turn) = Nearside (towards driver)
      RHT (right-hand traffic, drive on right - US/mainland Europe):
        positive net heading change = Nearside (left turn goes to driver's near side)
        negative net heading change = Farside
    """
    import math
    radii = get_polyline_curvature_radii(root, entity_name, min_heading_delta_rad, min_segment_length_m)
    if not radii:
        return None, ""

    min_r = min(radii)
    # Part 2 radii are the tightest - keep only those within part2_window_factor of minimum
    part2_radii = [r for r in radii if r <= part2_window_factor * min_r]
    if not part2_radii:
        part2_radii = radii  # fallback

    est_radius = sum(part2_radii) / len(part2_radii)

    # Determine turn direction from net heading change over curved section
    vertices = get_trajectory_vertices(root, entity_name)
    net_dh = 0.0
    for i in range(1, len(vertices)):
        dh = vertices[i]["h"] - vertices[i - 1]["h"]
        while dh > math.pi:
            dh -= 2 * math.pi
        while dh < -math.pi:
            dh += 2 * math.pi
        dl = math.hypot(vertices[i]["x"] - vertices[i - 1]["x"],
                        vertices[i]["y"] - vertices[i - 1]["y"])
        if abs(dh) > min_heading_delta_rad and dl > min_segment_length_m:
            net_dh += dh

    if handedness == "LHT":
        direction = "Farside" if net_dh > 0 else "Nearside"
    else:  # RHT
        direction = "Nearside" if net_dh > 0 else "Farside"
    return round(est_radius, 2), direction


def has_init_follow_trajectory(root: Any, entity_name: str) -> bool:
    """True if the entity's Init section contains a FollowTrajectoryAction."""
    for priv in xpath(root, "//Init//Private[@entityRef=$name]", name=entity_name):
        if priv.xpath(".//FollowTrajectoryAction"):
            return True
    return False


def get_init_entity_ordering(root: Any) -> list[str]:
    """Returns entity names in the order their Init/Private blocks appear.

    RoadRunner places the VUT first; this is the ordering check used when
    ManeuverGroup actor refs are absent (CH_SC_21 fallback).
    """
    seen: list[str] = []
    for priv in xpath(root, "//Init//Private"):
        name = priv.get("entityRef", "")
        if name and name not in seen:
            seen.append(name)
    return seen


def get_all_waypoints_by_entity(root: Any) -> dict[str, list[dict[str, float]]]:
    result: dict[str, list[dict[str, float]]] = {}

    # Standard OSC: Waypoints in ManeuverGroup
    for mg in xpath(root, "//ManeuverGroup"):
        entity_refs = [e.get("entityRef", "") for e in mg.xpath(".//EntityRef")]
        wps = [
            {
                "x": _safe_float(wp.get("x", "0")) or 0.0,
                "y": _safe_float(wp.get("y", "0")) or 0.0,
                "z": _safe_float(wp.get("z", "0")) or 0.0,
                "h": _safe_float(wp.get("h", "0")) or 0.0,
            }
            for wp in mg.xpath(".//Waypoint//WorldPosition")
        ]
        for ref in entity_refs:
            if ref:
                result.setdefault(ref, []).extend(wps)

    # RoadRunner kinematic format: Vertex elements in Init FollowTrajectoryAction
    if not result:
        for priv in xpath(root, "//Init//Private"):
            entity_name = priv.get("entityRef", "")
            if not entity_name:
                continue
            for vertex in priv.xpath(".//FollowTrajectoryAction//Trajectory//Shape//Polyline//Vertex"):
                wp = vertex.xpath(".//WorldPosition")
                if wp:
                    x = _safe_float(wp[0].get("x", "0"))
                    y = _safe_float(wp[0].get("y", "0"))
                    if x is not None and y is not None:
                        result.setdefault(entity_name, []).append({
                            "x": x, "y": y,
                            "z": _safe_float(wp[0].get("z", "0")) or 0.0,
                            "h": _safe_float(wp[0].get("h", "0")) or 0.0,
                        })
    return result


def get_action_phase_speeds(root: Any, entity_name: str) -> list[float]:
    """Returns AbsoluteTargetSpeed values from the Story (action phase) for an entity.
    Used to verify static/stationary actors have Initialize Speed = Absolute(0) in action phase.
    """
    speeds = []
    for mg in xpath(root, "//Story//Act//ManeuverGroup"):
        refs = [e.get("entityRef", "") for e in mg.xpath(".//EntityRef")]
        if entity_name not in refs:
            continue
        for val in mg.xpath(".//SpeedAction//SpeedActionTarget//AbsoluteTargetSpeed/@value"):
            v = _safe_float(val)
            if v is not None:
                speeds.append(v)
    return speeds
