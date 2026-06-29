"""Static content for the reviewer-checklist export (Review_Checklist_*.xlsx).

The team reviews scenarios against an Excel checklist with three sheets - Summary,
ChecklistFinal and Prequisites. The `--checklist` export reproduces that exact layout
(same sheets, columns and colours) so an automated run is an exact replica of the
reviewer file and drops straight into the existing review flow: our verdict fills the
Self Review column and Review1/Review2 stay blank for human reviewers. The Issues Log
table on ChecklistFinal is filled from the run (one row per failed or manual check).
The automation trust level is NOT shown here - it ships in the native Validation report.

MASTER_CHECKLIST is the ordered checkpoint list from the reference workbook, with two
deliberate edits agreed with the team:
  * our extra naming checks (NM_04-06) are appended after the reviewer's NM_01-03 so
    the first three NM numbers keep matching the reviewer checklist exactly;
  * for any checkpoint the validator computes, the writer shows OUR check description
    (our wording/logic wins); the reference text here is the fallback for the
    checkpoints we do not automate (MD_06-11, FB_02), which export as Manual rows.

Text is normalised to ASCII (curly quotes -> straight) to keep the codebase free of
special characters.
"""
from __future__ import annotations

# Summary sheet identity block (label, value), mirroring the reference document.
SUMMARY_META = [
    ("Document Name", "Review checklist to Review ENCAP Scenario in Road Runner"),
    ("Project", "ENCAP Virtual Validation"),
    ("Created by", "Suresh Surve"),
    ("DGM", "Arjun Kushwah"),
]

# ChecklistFinal header block (label, value). Responsible/Reviewer/Date are left blank
# for the team to fill; Protocol Name / Date are filled from the run at write time.
CHECKLIST_HEADER_LABELS = ["Release", "Protocol Name", "Responsible", "Reviewer", "Date"]

# ChecklistFinal main table headers - exactly the reference six (no automation columns,
# so the file is a true replica of the reviewer checklist).
CHECKLIST_COLUMNS = [
    "Category",
    "CheckPoint Number",
    "Check Points",
    "Self Review",
    "Review1",
    "Review2",
]

# Issues Log table headers, verbatim from the reference (the trailing space on "Sr No "
# is intentional - it matches the reviewer file).
ISSUES_LOG_COLUMNS = [
    "Sr No ",
    "Severity",
    "Details",
    "Status",
    "SelfReview Comment",
    "R1 Comment",
    "R2 Comment",
]

# Dropdown lists for the reviewer-facing controls (generic workflow options, cleaned of
# the reference file's typos). These are inputs a reviewer picks, not values we compute.
SELF_REVIEW_OPTIONS = "Yes,No"
RELEASE_OPTIONS = "PriorityA,PriorityB,PriorityD"
SEVERITY_OPTIONS = "Major,Minor,Documentation"
STATUS_OPTIONS = "Accepted,Rejected"

# Ordered (category, check_id, reference_text). Category repeats per row; the writer
# renders it only when it changes, like the reference. NM_04-06 are our additions.
MASTER_CHECKLIST = [
    ("Naming", "CH_NM_01", "Scenario naming conventions as per new names (VUT) and asset name as per ENCAP protocol. Refer snippet attached in prerequisite."),
    ("Naming", "CH_NM_02", "Name of .rrscene should be same as .rrscenario"),
    ("Naming", "CH_NM_03", "Every scenario should have 9 files of same names and different extension (xyz.rrscene, xyz.rrscenario, xyz.xosc, xyz.xodr, xyz.rd, xyz.xml, Model Desk Interpreter xyz.txt, TA.xml)"),
    ("Naming", "CH_NM_04", "Scenario name follows program_type_<n>VUT_<n><Target>_<n>Imp and its values agree with the protocol (validator addition)."),
    ("Naming", "CH_NM_05", "One consistent base name across all files; no duplicate or case-colliding filenames (validator addition)."),
    ("Naming", "CH_NM_06", "Scenario directory holds only valid RoadRunner/export/report extensions (validator addition)."),
    ("Road", "CH_RD_01", "Road Layout: Verify lane width (Euro NCAP standard: 3.5 m), road markings, and straight alignment."),
    ("Road", "CH_RD_02", "No single road should be present in the scene. Divide the road into atleast 2 segments and make the vehicle trajectory such that it covers both the road segments"),
    ("Road", "CH_RD_03", "Road Junction curvature should be maintained as 8 m"),
    ("Road", "CH_RD_04", "For scenarios that have static objects (vehicles, obstructions) at the intersection, while creating the scene the start of the leftmost road coordinates should be at the (0,0,0) position of the RoadRunner"),
    ("Road", "CH_RD_05", "For junction scenarios, roads must be created such that their start and end points are aligned with the VUT's direction of travel. The road orientation should follow the VUT's movement, with the road start representing the entry point and the road end the exit point of the VUT"),
    ("Road", "CH_RD_06", "For junction scenarios, road lanes must be added to the main driving lane not the shoulder lane. A shoulder lane creates a lane index mismatch in Model Desk"),
    ("Scenario", "CH_SC_01", "Check if all ENCAP scenario variations are covered"),
    ("Scenario", "CH_SC_02", "Check all 'x' and 'y' positions of VUT are correct"),
    ("Scenario", "CH_SC_03", "Check all 'x' and 'y' positions of Target are correct"),
    ("Scenario", "CH_SC_04", "Total simulation time should be 100 to 150 secs"),
    ("Scenario", "CH_SC_05", "Lane Positioning: VUT and GVT should be correctly placed in the lane as per scenario type. VUT should be at right lane"),
    ("Scenario", "CH_SC_06", "Direction of Travel: Ensure vehicles move in the correct direction (left-to-right or as per protocol)"),
    ("Scenario", "CH_SC_07", "Curvature path at part 2 (angle beta) - constant radius should be maintained and as close as possible to the protocol value for turning / lane change scenarios"),
    ("Scenario", "CH_SC_08", "Respective scenario should suffice the respective protocol defined. Reviewer should go through protocol and check the important points applicable for that scenario"),
    ("Scenario", "CH_SC_09", "Positions of assets (stationary) should be as per protocol for the respective scenario"),
    ("Scenario", "CH_SC_10", "No vehicle trajectory should start or end at an intersection. Trajectory should be until the end of the road for longitudinal scenarios. Make sure there is atleast 1 waypoint on the junction in crossing scenarios."),
    ("Scenario", "CH_SC_11", "No anchor should be present in the scenario. For all the actors the anchoring should be disabled"),
    ("Scenario", "CH_SC_12", "In the action phase for the actor we need to select the 'Waypoint Time Data' in the Relative to option"),
    ("Scenario", "CH_SC_13", "In the Route Timing Tool, the Timing Data option has to be checked."),
    ("Scenario", "CH_SC_14", "For static targets and obstructions keep the Initialize Speed as Absolute (with speed 0 m/s) in the action phase"),
    ("Scenario", "CH_SC_15", "For stationary targets like EMT, it should have Absolute (with speed 0 m/s) in the action phase"),
    ("Scenario", "CH_SC_16", "Impact percentages for turning and crossing should be approximately close to the actual value as final tuning is done in HILs"),
    ("Scenario", "CH_SC_17", "Impact percentages for longitudinal should exactly match the actual value"),
    ("Scenario", "CH_SC_18", "Check if VUT speed and target speed is as per scenario at the time of impact"),
    ("Scenario", "CH_SC_19", "Target should start moving only after VUT reaches its set speed (optional)"),
    ("Scenario", "CH_SC_20", "VUT turn direction and EBT / EPT direction should be maintained (Farside, Nearside, Same and Opposite)"),
    ("Scenario", "CH_SC_21", "VUT should always be on top of the action phase"),
    ("Scenario", "CH_SC_22", "All obstructions should be placed in the NCAP Asset folder in RR"),
    ("ModelDesk", "CH_MD_01", "Check there are no blue dots in the imported road"),
    ("ModelDesk", "CH_MD_02", "Check the number of routes is equal to the number of fellows in the scenario"),
    ("ModelDesk", "CH_MD_03", "Check if all routes have atleast 2 roads present in them"),
    ("ModelDesk", "CH_MD_04", "For junction scenarios, check the direction of roads comparing with the RoadRunner"),
    ("ModelDesk", "CH_MD_05", "Check that the routes do not have any warnings or errors. For junction scenarios ignore the warnings: change the junction path to default in the routes and check if warnings disappear; if yes, revert back to original path"),
    ("ModelDesk", "CH_MD_06", "Check the routes get correctly linked to the VUT and assets"),
    ("ModelDesk", "CH_MD_07", "Check the initial positions and directions of VUT and fellows displayed in the interpreter is correct as compared with the RoadRunner scenario"),
    ("ModelDesk", "CH_MD_08", "Check that there are no warnings or cautions displayed in the interpreter (exception is for static objects and static targets)"),
    ("ModelDesk", "CH_MD_09", "Check the duration for fellows is endless and VUT"),
    ("ModelDesk", "CH_MD_10", "For scenarios that have obstructions on the junction, check that the obstructions are present on the road i.e. in the .rd file"),
    ("ModelDesk", "CH_MD_11", "For scenarios that have obstructions on the road segments, check they are created as fellows in the scenario (.xml) and the position value is set for them according to the RR scenario"),
    ("Excel Macro", "CH_MR_01", "Check for any garbage/incorrect speed values for VUT and asset."),
    ("Excel Macro", "CH_MR_02", "Check the deceleration speed values for GVT/EMT for braking scenarios. Deceleration should be -4 m/s2"),
    ("Functional block", "CH_FB_01", "TA file should be provided along with the respective scenario. Use the v4 template ENCAP_Scenario_func_template_V4.0.xlsm."),
    ("Functional block", "CH_FB_02", "In the TA file, columns J to N have to be updated with a value of '2' based on the number of fellows in the scenario. The corresponding position values have to be updated in columns O to S in row 10"),
]

# Prequisites sheet rules, verbatim from the reference (ASCII-normalised).
PREREQUISITES = [
    "No vehicle trajectory should start or end at an intersection",
    "No anchor should be present in the scenario. For all the actors the anchoring should be disabled",
    "Actor naming convention should be followed as mentioned below: Ego should always be present with either of the names Ego/VUT/Vehicle, Actors (Vehicle2, Vehicle3 etc)",
    "In the action phase for the actor we need to select the 'Waypoint Time Data' in the Relative to option",
    "In the Route Timing Tool, the Timing Data option has to be checked.",
    "The timing profile in the Route Timing Tool for the actors needs to be adjusted for the vehicle to run at an intended speed.",
    "Exporting format for scene .xodr is shown below",
    "Exporting format for scenario is shown below",
    "No single road should be present in the scene. Divide the road into atleast 2 segments and make the vehicle trajectory such that it covers both the road segments",
    "For static targets and obstructions keep the Initialize Speed as Absolute (with speed 0 m/s) in the action phase",
    "For scenarios that have static objects (vehicles, obstructions) at the intersection, while creating the scene the start of the leftmost road coordinates should be at the (0,0,0) position of the RoadRunner",
    "For junction scenarios, roads must be created such that their start and end points are aligned with the VUT's direction of travel. The road orientation should follow the VUT's movement, with the road start representing the entry point and the road end the exit point of the VUT",
]
