"""CH_MR_01, CH_MR_02 - Model Review checks (speed sanity + braking deceleration)."""
from __future__ import annotations

import logging
from typing import Any

from ..models import CheckResult, Config
from ..parsers import xosc

log = logging.getLogger(__name__)

CATEGORY = "ModelReview"

_DESCRIPTIONS = {
    "CH_MR_01": "No garbage/incorrect speed values for VUT and Asset (no negative or implausibly high speeds)",
    "CH_MR_02": "GVT/EMT deceleration rate = protocol value (-4 m/s²) for braking scenarios",
}


def _make(check_id: str, status: str, comment: str = "") -> CheckResult:
    return CheckResult(
        check_id=check_id,
        category=CATEGORY,
        description=_DESCRIPTIONS[check_id],
        status=status,  # type: ignore[arg-type]
        comment=comment,
    )


def check_mr_01(xosc_root: Any, config: Config) -> CheckResult:
    """No garbage/incorrect speed values for the VUT and any asset.

    Scans every entity's Init speed and action-phase speeds. A speed is "garbage" when
    it is negative or above config.speed_sanity_max_kmh. Parameter references (e.g.
    '$speed') return None and are skipped - they cannot be evaluated at parse time.
    """
    max_ms = config.speed_sanity_max_kmh / 3.6

    bad: list[str] = []
    checked = 0
    for entity in xosc.get_entities(xosc_root):
        name = xosc.get_entity_name(entity)
        speeds: list[float] = []
        init_speed = xosc.get_init_speed(xosc_root, name)
        if init_speed is not None:
            speeds.append(init_speed)
        speeds.extend(xosc.get_action_phase_speeds(xosc_root, name))

        for s in speeds:
            checked += 1
            if s < 0:
                bad.append(f"'{name}': {s} m/s (negative)")
            elif s > max_ms:
                bad.append(f"'{name}': {s} m/s ({s * 3.6:.0f} km/h > {config.speed_sanity_max_kmh:.0f} km/h)")

    if checked == 0:
        return _make("CH_MR_01", "NA", "No numeric speed values found to validate")

    if bad:
        return _make(
            "CH_MR_01",
            "FAIL",
            "Garbage/incorrect speed value(s): " + "; ".join(bad),
        )
    return _make(
        "CH_MR_01",
        "PASS",
        f"All {checked} speed value(s) are within [0, {config.speed_sanity_max_kmh:.0f}] km/h",
    )


def check_mr_02(xosc_root: Any, config: Config) -> CheckResult:
    """For braking scenarios (e.g. CCRb), GVT deceleration rate must match protocol.

    Looks for SpeedActionDynamics[@dynamicsDimension='rate'][@dynamicsShape='linear']
    in any actor's story action. If found: this IS a braking scenario and the rate
    must match config.expected_decel_ms2 (default 4.0) within config.decel_tolerance_ms2.
    If no linear-rate decel action found: scenario is not a braking type -> NA.
    """
    decel_actions = xosc.get_braking_decel_actions(xosc_root)

    if not decel_actions:
        return _make(
            "CH_MR_02",
            "NA",
            "No linear-rate deceleration actions found - not a braking scenario",
        )

    expected = config.expected_decel_ms2
    tolerance = config.decel_tolerance_ms2

    vut_names_upper = [n.upper() for n in config.vut_entity_names]
    # Only check non-VUT actors (GVT, EMT, etc.)
    target_actions = [
        a for a in decel_actions
        if a["entity_name"].upper() not in vut_names_upper
    ]

    if not target_actions:
        return _make(
            "CH_MR_02",
            "NA",
            "Linear-rate decel found only on VUT - braking check only applies to GVT/EMT targets",
        )

    wrong: list[str] = []
    manual: list[str] = []

    for action in target_actions:
        name = action["entity_name"]
        rate = action["rate_ms2"]
        if rate is None:
            manual.append(
                f"'{name}': decel rate is parameterized"
                + (f" (${action['param_name']})" if action["param_name"] else "")
            )
        elif abs(rate - expected) > tolerance:
            wrong.append(f"'{name}': {rate:.2f} m/s² (expected {expected} ±{tolerance})")

    if wrong:
        comment = f"Incorrect deceleration rate: {'; '.join(wrong)}."
        if manual:
            comment += f" Parameterized (verify manually): {'; '.join(manual)}."
        return _make("CH_MR_02", "FAIL", comment)

    if manual:
        return _make(
            "CH_MR_02",
            "MANUAL_REVIEW",
            f"Deceleration rate is parameterized - cannot verify at parse time: {'; '.join(manual)}. "
            f"Confirm the resolved value equals {expected} m/s².",
        )

    passing = [f"'{a['entity_name']}': {a['rate_ms2']:.2f} m/s²" for a in target_actions]
    return _make(
        "CH_MR_02",
        "PASS",
        f"Deceleration rate = {expected} m/s² for: {', '.join(passing)}",
    )


def run_all(xosc_root: Any, config: Config) -> list[CheckResult]:
    return [
        check_mr_01(xosc_root, config),
        check_mr_02(xosc_root, config),
    ]
