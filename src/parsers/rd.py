"""Model Desk route (.rd) file parser.

The .rd file format is proprietary to MathWorks Model Desk. It is typically XML
(or a ZIP containing XML). This parser tries XML-first, then falls back to
line-based text matching for key-value extraction.
"""
from __future__ import annotations

import logging
import zipfile
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def _try_xml(data: bytes) -> dict[str, Any] | None:
    try:
        from lxml import etree as _etree  # type: ignore[import-untyped]
        import io
        _parser = _etree.XMLParser(no_network=True, resolve_entities=False, load_dtd=False)
        root = _etree.parse(io.BytesIO(data), _parser).getroot()
        routes = []
        for route_el in root.xpath("//Route") or root.xpath("//route") or root.xpath("//*[local-name()='Route']"):
            roads_in_route = (
                route_el.xpath(".//Road/@id")
                or route_el.xpath(".//road/@id")
                or route_el.xpath(".//*[local-name()='Road']/@id")
            )
            route_name = route_el.get("name", route_el.get("id", ""))
            roads_in_route = [str(r) for r in roads_in_route]
            warnings = route_el.xpath(".//Warning") or route_el.xpath(".//warning")
            errors_el = route_el.xpath(".//Error") or route_el.xpath(".//error")
            routes.append({
                "name": route_name,
                "roads": roads_in_route,
                "warnings": len(warnings),
                "errors": len(errors_el),
            })
        if routes:
            return {"format": "xml", "routes": routes}
    except Exception as exc:
        log.debug("XML parse attempt failed for .rd file: %s", exc)
    return None


def _try_text(data: bytes) -> dict[str, Any]:
    """Minimal text-based extraction for non-XML .rd files."""
    text = data.decode("utf-8", errors="replace")
    routes: list[dict] = []
    current: dict | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("route") or stripped.lower().startswith("[route"):
            if current:
                routes.append(current)
            current = {"name": stripped, "roads": [], "warnings": 0, "errors": 0}
        elif current and ("road" in stripped.lower()):
            current["roads"].append(stripped)
        elif current and "warning" in stripped.lower():
            current["warnings"] += 1
        elif current and "error" in stripped.lower():
            current["errors"] += 1
    if current:
        routes.append(current)
    return {"format": "text", "routes": routes}


def load(path: Path) -> dict[str, Any]:
    """Load .rd file. Returns dict with 'routes' list and 'format' key."""
    raw: bytes

    # Some .rd files might be ZIP archives
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path, "r") as zf:
            # Look for the main route file inside
            candidates = [n for n in zf.namelist() if n.endswith(".rd") or "route" in n.lower()]
            target = candidates[0] if candidates else zf.namelist()[0]
            raw = zf.read(target)
    else:
        raw = path.read_bytes()

    result = _try_xml(raw)
    if result:
        return result
    return _try_text(raw)


def get_route_count(data: dict) -> int:
    return len(data.get("routes", []))


def get_roads_per_route(data: dict) -> list[list[str]]:
    return [r["roads"] for r in data.get("routes", [])]


def route_has_warnings(data: dict) -> list[bool]:
    return [r["warnings"] > 0 for r in data.get("routes", [])]


def route_has_errors(data: dict) -> list[bool]:
    return [r["errors"] > 0 for r in data.get("routes", [])]
