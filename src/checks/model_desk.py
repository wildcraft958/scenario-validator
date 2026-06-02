"""CH_MD_01 through CH_MD_05 - Model Desk checks (from .rd + .xosc)."""
from __future__ import annotations

import logging
from typing import Any

from ..models import CheckResult, Config
from ..parsers import rd, xosc

log = logging.getLogger(__name__)

CATEGORY = "ModelDesk"

_DESCRIPTIONS = {
    "CH_MD_01": "No disconnected roads (blue dots) in imported road network - auto-detected via link topology",
    "CH_MD_02": "Number of routes equals number of fellows (actors) in scenario",
    "CH_MD_03": "All routes have at least 2 roads",
    "CH_MD_04": "Junction road direction matches RoadRunner orientation",
    "CH_MD_05": "Routes free of errors; warnings acceptable only for junctions",
}


def _make(check_id: str, status: str, comment: str = "") -> CheckResult:
    return CheckResult(
        check_id=check_id,
        category=CATEGORY,
        description=_DESCRIPTIONS[check_id],
        status=status,  # type: ignore[arg-type]
        comment=comment,
    )


def check_md_01(xodr_root: Any) -> CheckResult:
    """
    Blue dots = disconnected roads in the network topology.
    Detectable by scanning road <link> successor/predecessor references in .xodr.
    """
    from ..parsers import xodr
    disconnected = xodr.find_disconnected_roads(xodr_root)
    if not disconnected:
        return _make(
            "CH_MD_01",
            "PASS",
            "All road link connections are valid - no disconnected roads (blue dots) detected",
        )
    return _make(
        "CH_MD_01",
        "FAIL",
        f"Disconnected road IDs (blue dots): {', '.join(disconnected)}. "
        "Fix broken successor/predecessor links in RoadRunner before re-exporting.",
    )


def check_md_02(rd_data: dict, xosc_root: Any, config: Config) -> CheckResult:
    """Number of routes must equal number of fellow actors."""
    route_count = rd.get_route_count(rd_data)
    entities = xosc.get_entities(xosc_root)
    entity_names = [xosc.get_entity_name(e) for e in entities]

    # Total actors include VUT + targets - all need routes
    actor_count = len(entity_names)

    if route_count == 0:
        return _make(
            "CH_MD_02",
            "FAIL" if rd_data.get("format") != "text" else "MANUAL_REVIEW",
            f"No routes parsed from .rd file (format: {rd_data.get('format', 'unknown')}). "
            f"Expected {actor_count} routes for actors: {', '.join(entity_names)}",
        )

    if route_count == actor_count:
        return _make(
            "CH_MD_02",
            "PASS",
            f"{route_count} routes == {actor_count} actors ({', '.join(entity_names)})",
        )
    return _make(
        "CH_MD_02",
        "FAIL",
        f"{route_count} routes found but {actor_count} actors exist "
        f"({', '.join(entity_names)}). Add missing routes.",
    )


def check_md_03(rd_data: dict) -> CheckResult:
    """All routes must have at least 2 roads."""
    roads_per_route = rd.get_roads_per_route(rd_data)
    if not roads_per_route:
        return _make(
            "CH_MD_03",
            "MANUAL_REVIEW",
            "Could not parse route road lists from .rd file - verify manually",
        )

    short_routes = [
        f"Route {i+1} ({len(r)} road{'s' if len(r) != 1 else ''})"
        for i, r in enumerate(roads_per_route)
        if len(r) < 2
    ]
    if not short_routes:
        return _make(
            "CH_MD_03",
            "PASS",
            f"All {len(roads_per_route)} routes have >= 2 roads",
        )
    return _make(
        "CH_MD_03",
        "FAIL",
        f"Route(s) with < 2 roads: {', '.join(short_routes)}",
    )


def check_md_04(rd_data: dict, xodr_root: Any, config: Config) -> CheckResult:
    """Junction road direction in .rd must match RoadRunner (.xodr) orientation.

    This is a cross-file consistency check: the rd file should reference roads
    that are oriented the same way as in the xodr.
    """
    from ..parsers import xodr
    has_junctions = xodr.has_junctions(xodr_root)
    if not has_junctions:
        return _make("CH_MD_04", "NA", "No junctions in .xodr - check not applicable")

    if rd_data.get("format") == "xml":
        # If we can parse route data, check road IDs referenced exist in xodr
        roads_per_route = rd.get_roads_per_route(rd_data)
        xodr_road_ids = {r.get("id", "") for r in xodr.get_roads(xodr_root)}
        rd_road_ids = {road_id for route in roads_per_route for road_id in route}

        unknown = rd_road_ids - xodr_road_ids - {""}
        if unknown:
            return _make(
                "CH_MD_04",
                "FAIL",
                f"Road IDs in .rd not found in .xodr: {', '.join(unknown)}. "
                "Ensure road IDs are consistent between files.",
            )
        return _make("CH_MD_04", "PASS", "All .rd road IDs found in .xodr")

    return _make(
        "CH_MD_04",
        "MANUAL_REVIEW",
        "Cannot cross-validate road directions from non-XML .rd format. "
        "Manually verify junction road directions match RoadRunner orientation.",
    )


def check_md_05(rd_data: dict, is_junction_scenario: bool) -> CheckResult:
    """Routes should be free of errors; warnings acceptable for junctions."""
    has_warnings = rd.route_has_warnings(rd_data)
    has_errors = rd.route_has_errors(rd_data)

    if not any(has_warnings) and not any(has_errors):
        return _make("CH_MD_05", "PASS", "No warnings or errors in any route")

    if not any(has_errors):
        if is_junction_scenario:
            return _make(
                "CH_MD_05",
                "PASS",
                "Junction scenario: warnings present but acceptable. "
                "Verify warnings disappear when junction path set to default, then revert.",
            )
        routes_with_warnings = [i + 1 for i, w in enumerate(has_warnings) if w]
        return _make(
            "CH_MD_05",
            "FAIL",
            f"Non-junction scenario with warnings in route(s): {routes_with_warnings}. "
            "Fix warnings or change the junction path to default and revert.",
        )

    error_routes = [i + 1 for i, e in enumerate(has_errors) if e]
    return _make(
        "CH_MD_05",
        "FAIL",
        f"Route errors found in route(s): {error_routes}. Errors must be resolved.",
    )


def run_all(rd_data: dict, xosc_root: Any, xodr_root: Any, config: Config) -> list[CheckResult]:
    from ..parsers import xodr as xodr_mod
    is_junction = xodr_mod.has_junctions(xodr_root)
    return [
        check_md_01(xodr_root),
        check_md_02(rd_data, xosc_root, config),
        check_md_03(rd_data),
        check_md_04(rd_data, xodr_root, config),
        check_md_05(rd_data, is_junction),
    ]
