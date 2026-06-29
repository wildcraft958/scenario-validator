"""Tests for src/discovery.discover_scenarios."""
from __future__ import annotations

from pathlib import Path

from src.discovery import discover_scenarios


def _touch(folder: Path, name: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text("x")


def test_finds_nested_scenarios_any_depth(tmp_path: Path):
    _touch(tmp_path / "Batch 1" / "Car_to_Car" / "S1", "a.xosc")
    _touch(tmp_path / "Batch 1" / "Car_to_Car" / "S2", "a.xosc")
    scenarios, incompatible = discover_scenarios(tmp_path)
    names = sorted(p.name for p in scenarios)
    assert names == ["S1", "S2"]
    assert incompatible == []


def test_root_that_is_itself_a_scenario_is_found(tmp_path: Path):
    _touch(tmp_path, "only.xosc")
    scenarios, _ = discover_scenarios(tmp_path)
    assert scenarios == [tmp_path]


def test_roadrunner_native_only_is_incompatible_not_a_scenario(tmp_path: Path):
    _touch(tmp_path / "RR" / "native", "a.rrscene")
    (tmp_path / "RR" / "native" / "b.rrscenario").write_text("x")
    scenarios, incompatible = discover_scenarios(tmp_path)
    assert scenarios == []
    assert [p.name for p in incompatible] == ["native"]
