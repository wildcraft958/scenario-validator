"""CH_MR_01, CH_MR_02 - Model Review checks (speed sanity + braking deceleration)."""
from __future__ import annotations

from typing import Any

from ..models import CheckResult, CheckStatus, Config
from ..parsers import xosc

CATEGORY = "ModelReview"

_DESCRIPTIONS = {
    "CH_MR_01": "No garbage/incorrect speed values for VUT and Asset (no negative or implausibly high speeds)",
    "CH_MR_02": "GVT/EMT deceleration rate = protocol value (-4 m/s²) for braking scenarios",
}


def _make(check_id: str, status: CheckStatus, comment: str = "") -> CheckResult:
    return CheckResult(
        check_id=check_id,
        category=CATEGORY,
        description=_DESCRIPTIONS[check_id],
        status=status,
        comment=comment,
    )


def _entity_current_speed_ms(xosc_root: Any, name: str) -> float | None:
    """Best estimate of an entity's speed (m/s) before a story action: Init speed first,
    else the kinematic trajectory cruise speed. Used to tell deceleration from acceleration."""
    init = xosc.get_init_speed(xosc_root, name)
    if init is not None:
        return init
    traj_kmh = xosc.get_trajectory_speed_kmh(xosc_root, name)
    return traj_kmh / 3.6 if traj_kmh is not None else None


def check_mr_01(xosc_root: Any, config: Config) -> CheckResult:
    """No garbage/incorrect speed values for the VUT and any asset.

    Checks explicit AbsoluteTargetSpeed values in Init and action phase, plus
    peak cruise speeds derived from kinematic trajectory vertices (RoadRunner format).
    A speed is flagged when it is negative or above config.speed_sanity_max_kmh.

    Scope note: this is a GARBAGE/sanity filter (negative or implausibly high values), not a
    protocol-range check. Whether a plausible speed is correct FOR THE SCENARIO (e.g. 90 km/h
    in a turning scenario) is owned by CH_SC_18, which grades the VUT/target speeds against the
    per-scenario range + the filename tokens - so a per-motion ceiling here would just duplicate it.
    """
    max_kmh = config.speed_sanity_max_kmh
    max_ms = max_kmh / 3.6

    bad: list[str] = []
    checked = 0
    sources: list[str] = []

    for entity in xosc.get_entities(xosc_root):
        name = xosc.get_entity_name(entity)

        # Explicit speeds: Init AbsoluteTargetSpeed + action-phase speeds
        explicit: list[float] = []
        init_speed = xosc.get_init_speed(xosc_root, name)
        if init_speed is not None:
            explicit.append(init_speed)
        explicit.extend(xosc.get_action_phase_speeds(xosc_root, name))

        for s in explicit:
            checked += 1
            if s < 0:
                bad.append(f"'{name}': {s:.2f} m/s (negative)")
            elif s > max_ms:
                bad.append(f"'{name}': {s * 3.6:.0f} km/h > {max_kmh:.0f} km/h")

        # Trajectory-derived speed (RoadRunner kinematic format)
        traj_kmh = xosc.get_trajectory_speed_kmh(xosc_root, name)
        if traj_kmh is not None:
            checked += 1
            sources.append(f"'{name}' {traj_kmh:.1f} km/h")
            if traj_kmh < 0:
                bad.append(f"'{name}' trajectory: {traj_kmh:.1f} km/h (negative)")
            elif traj_kmh > max_kmh:
                bad.append(f"'{name}' trajectory: {traj_kmh:.1f} km/h > {max_kmh:.0f} km/h")

    if checked == 0:
        return _make("CH_MR_01", "NA", "No numeric speed values found to validate")

    if bad:
        return _make("CH_MR_01", "FAIL", "Garbage/incorrect speed value(s): " + "; ".join(bad))

    detail = f" Trajectory speeds: {', '.join(sources)}." if sources else ""
    return _make(
        "CH_MR_01",
        "PASS",
        f"All {checked} speed value(s) within [0, {max_kmh:.0f}] km/h.{detail}",
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

    # The -4 m/s2 rule applies only to genuine DECELERATIONS. A linear-rate SpeedAction can
    # also be an ACCELERATION (e.g. the target speeding up in CPLA/CBLA), which is not a
    # braking event and must not be force-checked against the braking rate. An action is a
    # deceleration when it targets a full stop (target 0) or a speed below the actor's
    # current speed - derived from the action, no per-scenario config needed.
    braking_actions = []
    for action in target_actions:
        target = action.get("target_speed")
        if target is not None and target > 0.001:
            current = _entity_current_speed_ms(xosc_root, action["entity_name"])
            if current is not None and target >= current - 1e-6:
                continue  # acceleration or speed-hold -> not a braking action
        braking_actions.append(action)

    if not braking_actions:
        return _make(
            "CH_MR_02",
            "NA",
            "Linear-rate speed action(s) present but none reduce the target's speed "
            "(target speed >= current) - this is acceleration/speed-hold, not braking",
        )
    target_actions = braking_actions

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
