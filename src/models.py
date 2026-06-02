from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class CheckResult(BaseModel):
    check_id: str
    category: str
    description: str
    status: Literal["PASS", "FAIL", "NA", "MANUAL_REVIEW"]
    comment: str = ""
    source_file: str = ""
    severity: str = "Medium"
    automatable_or_manual: Literal["Automatable", "Manual"] = "Automatable"
    timestamp: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    suggested_fix: str = ""

    @model_validator(mode="after")
    def normalize_review_fields(self) -> CheckResult:
        if self.status == "MANUAL_REVIEW":
            self.automatable_or_manual = "Manual"
            if not self.severity:
                self.severity = "Low"
        elif not self.severity:
            self.severity = "High" if self.status == "FAIL" else "Medium"
        if self.status == "FAIL" and not self.suggested_fix:
            self.suggested_fix = self.comment or "Review the failing check and correct the source data."
        return self

    @property
    def result(self) -> Literal["Yes", "No", "NA", "Manual"]:
        status_map = {"PASS": "Yes", "FAIL": "No", "NA": "NA", "MANUAL_REVIEW": "Manual"}
        return status_map[self.status]  # type: ignore[return-value]

    def as_row(self) -> tuple[str, str, str, str, str]:
        return (
            self.category,
            self.check_id,
            self.description,
            self.result,
            self.comment,
        )

    def as_validation_row(self) -> list[str]:
        return [
            self.check_id,
            self.category,
            self.description,
            self.result,
            self.comment,
            self.source_file,
            self.severity,
            self.automatable_or_manual,
            self.timestamp,
        ]


class SummaryStats(BaseModel):
    scenario_name: str
    run_timestamp: str
    protocol_version: str
    total: int
    passed: int
    failed: int
    manual: int
    na: int
    pass_rate: float
    critical_failures: list[str]
    scenario_dir: str = ""
    config_path: str = ""
    template_path: str = ""
    cli_command: str = ""
    final_status: str = ""
    automatable_total: int = 0
    automatable_passed: int = 0
    automatable_failed: int = 0

    @classmethod
    def from_results(
        cls,
        results: list[CheckResult],
        scenario_name: str,
        run_timestamp: str,
        protocol_version: str,
        scenario_dir: str = "",
        config_path: str = "",
        template_path: str = "",
        cli_command: str = "",
    ) -> SummaryStats:
        passed = sum(1 for r in results if r.status == "PASS")
        failed = sum(1 for r in results if r.status == "FAIL")
        manual = sum(1 for r in results if r.status == "MANUAL_REVIEW")
        na = sum(1 for r in results if r.status == "NA")
        total = len(results)
        automatable_results = [
            r for r in results
            if r.automatable_or_manual == "Automatable" and r.status in ("PASS", "FAIL")
        ]
        automatable_passed = sum(1 for r in automatable_results if r.status == "PASS")
        automatable_failed = sum(1 for r in automatable_results if r.status == "FAIL")
        automatable_total = len(automatable_results)
        rate = round((automatable_passed / automatable_total * 100) if automatable_total else 0, 1)
        critical = [r.check_id for r in results if r.status == "FAIL"]
        return cls(
            scenario_name=scenario_name,
            run_timestamp=run_timestamp,
            protocol_version=protocol_version,
            total=total,
            passed=passed,
            failed=failed,
            manual=manual,
            na=na,
            pass_rate=rate,
            critical_failures=critical,
            scenario_dir=scenario_dir,
            config_path=config_path,
            template_path=template_path,
            cli_command=cli_command,
            final_status="FAIL" if failed else "PASS",
            automatable_total=automatable_total,
            automatable_passed=automatable_passed,
            automatable_failed=automatable_failed,
        )


class VehicleDimensions(BaseModel):
    length: float
    width: float


class SimTimeThreshold(BaseModel):
    vut_speed_max_kmh: float
    min_s: float
    max_s: float


class ScenarioProtocol(BaseModel):
    type: Literal["longitudinal", "crossing", "head-on"] = "longitudinal"
    vut_speed_range_kmh: list[float] | None = None
    target_speed_kmh: float | None = None
    impact_overlap_pct: float = 50.0
    direction: str = "left-to-right"

    @field_validator("vut_speed_range_kmh")
    @classmethod
    def two_elements(cls, v):
        if v is not None and len(v) != 2:
            raise ValueError("vut_speed_range_kmh must have exactly 2 elements [min, max]")
        return v


class Config(BaseModel):
    protocol_version: str
    lane_width_m: float
    lane_width_tolerance_m: float
    junction_radius_m: float
    junction_radius_tolerance_m: float
    simulation_time_min_s: float
    simulation_time_max_s: float
    impact_tolerance_pct: float
    required_file_extensions: list[str]
    required_standalone_files: list[str]
    vut_entity_names: list[str]
    vehicle_dimensions: dict[str, VehicleDimensions]
    naming_convention: dict
    scenarios: dict[str, ScenarioProtocol]
    # Actor naming registry (EuroNCAP standard names for non-VUT entities)
    encap_actor_names: list[str] = []
    # Config-driven entity detection for static/stationary checks
    static_target_name_patterns: list[str] = []
    stationary_target_name_patterns: list[str] = []
    # Speed-dependent simulation time thresholds (overrides flat min/max when VUT speed is known)
    simulation_time_by_speed_s: list[SimTimeThreshold] = []
    # Tighter tolerance for longitudinal impact checks (CH_SC_17)
    longitudinal_impact_tolerance_pct: float = 1.0
    # Radius around estimated junction centre used to detect crossing waypoints (CH_SC_10)
    junction_waypoint_radius_m: float = 20.0
    # Expected GVT/EMT deceleration rate for braking scenarios (CH_MR_02)
    expected_decel_ms2: float = 4.0
    decel_tolerance_ms2: float = 0.1
    # Upper bound for plausible entity speeds; speeds above this (or negative) are
    # flagged as garbage/incorrect by CH_MR_01.
    speed_sanity_max_kmh: float = 300.0
    # Scenario name prefixes that require EuroNCAP junction geometry (CH_RD_03/04/05/06).
    # Curved-following scenarios (CCF*) have junction elements in their xodr for lane
    # structure, not intersections - those checks must be skipped for them.
    junction_scenario_prefixes: list[str] = []
    # ---- Geometry tolerances (previously hardcoded in check logic) ----
    # CH_SC_05: how close to east (0 deg) a WorldPosition heading must be before the
    # negative-y = right-lane heuristic is applied.
    east_heading_tolerance_deg: float = 30.0
    # CH_SC_06 / CH_RD_04: how close the VUT/road heading must be to a cardinal axis
    # (0/90/180/270 deg) to count as straight, axis-aligned travel. World direction itself
    # is NOT constrained - RoadRunner authors scenes in any orientation.
    cardinal_heading_tolerance_deg: float = 5.0
    # CH_SC_05: lateral offset (m) from road centre beyond which the lane side is decided.
    right_lane_offset_threshold_m: float = 0.1
    # get_polyline_curvature_radii / CH_SC_07: minimum per-vertex heading change (rad) and
    # segment length (m) for a polyline section to count as "curving" rather than straight.
    curvature_min_heading_delta_rad: float = 0.01
    curvature_min_segment_length_m: float = 0.01
    # CH_SC_07: radii above this multiple of the median are treated as discretisation
    # outliers at the arc entry/exit and excluded from the estimated turn radius.
    curvature_outlier_factor: float = 2.5

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        config_path = path or Path(__file__).parent.parent / "config.json"
        raw = json.loads(config_path.read_text())
        # strip any top-level documentation keys (any key starting with "_"),
        # so config.json can carry inline guidance/comments for editors.
        for key in [k for k in raw if k.startswith("_")]:
            raw.pop(key)
        # coerce nested dicts
        raw["vehicle_dimensions"] = {
            k: VehicleDimensions(**v) for k, v in raw["vehicle_dimensions"].items()
        }
        raw["scenarios"] = {
            k: ScenarioProtocol(**v)
            for k, v in raw["scenarios"].items()
            if not k.startswith("_")
        }
        raw["simulation_time_by_speed_s"] = [
            SimTimeThreshold(**t) for t in raw.get("simulation_time_by_speed_s", [])
        ]
        cfg = cls(**raw)
        # One-place editing: adding a scenario under "scenarios" auto-registers its
        # tag for detection - no need to also edit naming_convention.valid_prefixes.
        # The scenario key's prefix (text before any "-") is unioned into valid_prefixes.
        prefixes = list(cfg.naming_convention.get("valid_prefixes", []))
        for key in cfg.scenarios:
            prefix = key.split("-")[0]
            if prefix and prefix not in prefixes:
                prefixes.append(prefix)
        cfg.naming_convention["valid_prefixes"] = prefixes
        return cfg

    def scenario_protocol(self, scenario_tag: str) -> ScenarioProtocol | None:
        for key, proto in self.scenarios.items():
            if scenario_tag.upper().startswith(key.upper()):
                return proto
        return None

    def vut_dims(self) -> VehicleDimensions:
        return self.vehicle_dimensions.get("VUT", self.vehicle_dimensions["default_car"])

    def target_dims(self, entity_name: str = "GVT") -> VehicleDimensions:
        for key in self.vehicle_dimensions:
            if key.lower() in entity_name.lower():
                return self.vehicle_dimensions[key]
        return self.vehicle_dimensions["default_car"]
