"""Scenario-folder discovery shared by the batch runners.

A scenario is identified purely by its files, so the same call works no matter how
deeply the team nests batches (Batch > Category > scenario) or whether the tree is
flat (e.g. examples/). Hand it the root, it finds every runnable scenario folder.
"""
from __future__ import annotations

from pathlib import Path


def discover_scenarios(root: Path) -> tuple[list[Path], list[Path]]:
    """Return (scenario_dirs, incompatible_dirs).

    A scenario dir directly contains >=1 .xosc. An incompatible dir has a
    RoadRunner-native export (.rrscene/.rrscenario) but no .xosc, so the full
    OpenSCENARIO/OpenDRIVE export the validator needs is absent.

    The root itself is considered, so pointing the tool straight at one scenario
    folder works as well as handing it a whole nested tree.
    """
    scenario_dirs: list[Path] = []
    incompatible: list[Path] = []
    for path in [root, *sorted(root.rglob("*"))]:
        if not path.is_dir():
            continue
        has_xosc = any(p.suffix == ".xosc" for p in path.iterdir() if p.is_file())
        if has_xosc:
            scenario_dirs.append(path)
            continue
        has_rr = any(
            p.suffix in (".rrscene", ".rrscenario") for p in path.iterdir() if p.is_file()
        )
        if has_rr:
            incompatible.append(path)
    return scenario_dirs, incompatible
