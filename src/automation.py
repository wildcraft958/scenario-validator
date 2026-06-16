"""Automation level (trust) registry for every check.

Each check carries an intrinsic automation level that says how far its verdict can
be trusted on its own, based on how robustly it is derived from the exported files:

  * "Fully Automated"     - the PASS/FAIL is computed deterministically from the
                            files (counts, IDs, exact values, required structures);
                            no human confirmation is needed for what it asserts.
  * "Partially Automated" - the verdict relies on a geometric estimate, a proxy, or a
                            measurement that needs HIL / GUI / visual confirmation
                            (impact %, turn radius, kerb radius, heading-as-direction).
  * "Manual"              - the tool can only confirm presence/format or genuinely
                            cannot decide correctness; a human makes the call.

This level is a property of the check, not of one run, so it lives here keyed by
check id rather than being set per result. The reference-only checks the reviewer
checklist carries but this validator does not compute (MD_06-11, FB_02) are included
so the reference-format export can show their level too.
"""
from __future__ import annotations

from typing import Literal

AutomationLevel = Literal["Fully Automated", "Partially Automated", "Manual"]

_FULL: AutomationLevel = "Fully Automated"
_PARTIAL: AutomationLevel = "Partially Automated"
_MANUAL: AutomationLevel = "Manual"

# check_id -> (level, one-line reason)
AUTOMATION_LEVEL: dict[str, tuple[AutomationLevel, str]] = {
    # ---- Naming ----
    "CH_NM_01": (_FULL, "Reads actor/asset names from the .xosc and matches the EuroNCAP name registry."),
    "CH_NM_02": (_FULL, "Compares the .rrscene and .rrscenario base names directly."),
    "CH_NM_03": (_FULL, "Checks each required file exists by base name and extension."),
    "CH_NM_04": (_FULL, "Parses the filename grammar and cross-checks the tokens against the protocol config."),
    "CH_NM_05": (_FULL, "Detects multiple base names and duplicate/case-colliding filenames."),
    "CH_NM_06": (_FULL, "Allowlists file extensions against the configured set."),
    # ---- Road ----
    "CH_RD_01": (_PARTIAL, "Lane width is measured from the .xodr; road markings and straight alignment are a visual confirm."),
    "CH_RD_02": (_FULL, "Counts road segments in the .xodr."),
    "CH_RD_03": (_PARTIAL, "RoadRunner does not export the kerb radius, so the connecting-road radii are reported for GUI confirmation."),
    "CH_RD_04": (_FULL, "Reads the leftmost junction road's start point from the .xodr."),
    "CH_RD_05": (_PARTIAL, "Road heading vs the cardinal axes is computed from the .xodr; VUT entry/exit alignment is a manual confirm."),
    "CH_RD_06": (_FULL, "Checks junction lanes sit on the main driving lane using .xodr lane data."),
    # ---- Scenario ----
    "CH_SC_01": (_FULL, "Confirms the ParameterDeclarations block is present in the .xosc."),
    "CH_SC_02": (_MANUAL, "Confirms VUT x/y are present; their correctness against the protocol is a manual check."),
    "CH_SC_03": (_MANUAL, "Confirms target x/y are present; their correctness against the protocol is a manual check."),
    "CH_SC_04": (_FULL, "Computes total simulation time and compares it to the speed-dependent bound."),
    "CH_SC_05": (_FULL, "Reads the VUT lane side from the lane ID; GVT placement is a manual check."),
    "CH_SC_06": (_FULL, "Computes VUT heading from the trajectory; the travel direction value is a manual confirm."),
    "CH_SC_07": (_PARTIAL, "Turn radius is estimated from the trajectory polyline within a tolerance; confirm in HIL."),
    "CH_SC_08": (_MANUAL, "Whether the scenario satisfies the full protocol is a reviewer judgement."),
    "CH_SC_09": (_MANUAL, "Confirms static-asset positions are present; their correctness is a manual check."),
    "CH_SC_10": (_PARTIAL, "Checks trajectory endpoints against an estimated junction centre within a radius."),
    "CH_SC_11": (_FULL, "Confirms anchoring is disabled for every actor in the .xosc."),
    "CH_SC_12": (_FULL, "Confirms the action phase uses Waypoint Time Data with a Relative-to option."),
    "CH_SC_13": (_FULL, "Confirms the Route Timing Tool Timing Data option is set."),
    "CH_SC_14": (_FULL, "Reads the initialize speed of static targets/obstructions (must be 0)."),
    "CH_SC_15": (_FULL, "Reads the initialize speed of stationary VRU targets (must be 0)."),
    "CH_SC_16": (_PARTIAL, "Impact % for turning/crossing is a geometric estimate (+/-5%); final tuning is done in HIL."),
    "CH_SC_17": (_PARTIAL, "Impact % for longitudinal is a geometric estimate against the filename token; confirm in HIL."),
    "CH_SC_18": (_PARTIAL, "VUT speed is measured from the trajectory and range-checked; the target-speed token is cross-checked, confirm in HIL."),
    "CH_SC_19": (_FULL, "Confirms a speed-based trigger gates the target start."),
    "CH_SC_20": (_PARTIAL, "Direction/side parameters are detected and RAG-matched; their correctness is confirmed manually."),
    "CH_SC_21": (_FULL, "Confirms the VUT is first in the action-phase ordering."),
    "CH_SC_22": (_FULL, "Checks obstruction asset paths resolve to the NCAP asset folder."),
    # ---- Model Desk ----
    "CH_MD_01": (_FULL, "Detects disconnected roads via .xodr link topology."),
    "CH_MD_02": (_FULL, "Counts routes in the .rd and compares to the actor count."),
    "CH_MD_03": (_FULL, "Counts the road segments in each route from the .rd."),
    "CH_MD_04": (_PARTIAL, "Cross-checks .rd road references against the .xodr; junction direction is confirmed in the tool."),
    "CH_MD_05": (_PARTIAL, "Reads route warnings/errors from the .rd where present; ModelDesk runtime warnings are confirmed in the tool."),
    "CH_MD_06": (_MANUAL, "Routes correctly linked to VUT and assets - confirmed in ModelDesk."),
    "CH_MD_07": (_MANUAL, "Initial positions/directions in the interpreter - confirmed in ModelDesk."),
    "CH_MD_08": (_MANUAL, "No warnings/cautions in the interpreter - confirmed in ModelDesk."),
    "CH_MD_09": (_MANUAL, "Fellow duration endless and VUT duration set - confirmed in ModelDesk."),
    "CH_MD_10": (_MANUAL, "Junction obstructions created correctly - confirmed in ModelDesk."),
    "CH_MD_11": (_MANUAL, "Road-segment obstructions created correctly - confirmed in ModelDesk."),
    # ---- Model Review / Excel Macro ----
    "CH_MR_01": (_FULL, "Sanity-checks VUT/asset speed values from the .xosc for garbage/negative/implausible values."),
    "CH_MR_02": (_PARTIAL, "Measures GVT/EMT deceleration from the trajectory for braking scenarios; confirm in the macro."),
    # ---- Functional block ----
    "CH_FB_01": (_FULL, "Confirms the ENCAP functional workbook is present and is a valid workbook (OOXML)."),
    "CH_FB_02": (_PARTIAL, "Reads the TA workbook Set_initial_position row and checks the object display-switches/positions match the fellow count."),
}


def automation_for(check_id: str) -> tuple[AutomationLevel, str]:
    """Return (level, reason) for a check id, defaulting to Manual if unregistered."""
    return AUTOMATION_LEVEL.get(check_id, (_MANUAL, "Unclassified check - review manually."))
