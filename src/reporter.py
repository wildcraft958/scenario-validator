"""Excel and CSV reporter for EuroNCAP scenario validation results.

Excel output matches the existing team checklist layout:
  Col B = Category, Col C = CheckPoint Number, Col D = Description
  Col E = Self Review (Yes/No/NA/Manual), Col F = Comment

Sheet 1: Validation_<ScenarioName>   - one row per check
Sheet 2: Run_Summary_<Timestamp>     - aggregate stats + critical failures
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .models import CheckResult, SummaryStats

log = logging.getLogger(__name__)

# Colour palette (ARGB)
_GREEN = "FF92D050"
_RED = "FFFF0000"
_YELLOW = "FFFFC000"
_GREY = "FFD3D3D3"
_BLUE_HDR = "FF4472C4"
_WHITE = "FFFFFFFF"

_STATUS_FILL = {
    "Yes": PatternFill("solid", fgColor=_GREEN),
    "No": PatternFill("solid", fgColor=_RED),
    "NA": PatternFill("solid", fgColor=_GREY),
    "Manual": PatternFill("solid", fgColor=_YELLOW),
}
_STATUS_FONT = {
    "Yes": Font(bold=True, color="FF000000"),
    "No": Font(bold=True, color=_WHITE),
    "NA": Font(bold=False, color="FF000000"),
    "Manual": Font(bold=True, color="FF000000"),
}

_COL_B = 2   # Category
_COL_C = 3   # CheckPoint Number
_COL_D = 4   # Check Points Description
_COL_E = 5   # Self Review (auto result)
_COL_F = 6   # Comment


def _header_row(ws, row: int) -> None:
    headers = ["Category", "CheckPoint Number", "Check Points", "Self Review", "Comment"]
    fills = PatternFill("solid", fgColor=_BLUE_HDR)
    font = Font(bold=True, color=_WHITE)
    for col_idx, text in enumerate(headers, start=_COL_B):
        cell = ws.cell(row=row, column=col_idx, value=text)
        cell.fill = fills
        cell.font = font
        cell.alignment = Alignment(horizontal="center", wrap_text=True)


def _result_row(ws, row: int, result: CheckResult) -> None:
    category, chk_id, description, status_str, comment = result.as_row()

    ws.cell(row=row, column=_COL_B, value=category)
    ws.cell(row=row, column=_COL_C, value=chk_id)

    desc_cell = ws.cell(row=row, column=_COL_D, value=description)
    desc_cell.alignment = Alignment(wrap_text=True)

    status_cell = ws.cell(row=row, column=_COL_E, value=status_str)
    status_cell.fill = _STATUS_FILL.get(status_str, PatternFill("solid", fgColor=_GREY))
    status_cell.font = _STATUS_FONT.get(status_str, Font())
    status_cell.alignment = Alignment(horizontal="center")

    comment_cell = ws.cell(row=row, column=_COL_F, value=comment)
    comment_cell.alignment = Alignment(wrap_text=True)

    # Category grouping: merge category cell vertically when category repeats
    # (handled later via category blocks)


def _set_column_widths(ws) -> None:
    widths = {_COL_B: 14, _COL_C: 16, _COL_D: 60, _COL_E: 14, _COL_F: 50}
    for col, width in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = width


def _merge_category_cells(ws, category_rows: dict[str, list[int]]) -> None:
    """Merge category cells vertically for cleaner look."""
    for rows in category_rows.values():
        if len(rows) > 1:
            ws.merge_cells(
                start_row=rows[0],
                start_column=_COL_B,
                end_row=rows[-1],
                end_column=_COL_B,
            )
            cell = ws.cell(row=rows[0], column=_COL_B)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.font = Font(bold=True)


def write_excel(
    results: list[CheckResult],
    stats: SummaryStats,
    output_path: Path,
    template_path: Path | None = None,
) -> Path:
    """Write full Excel report. Returns path of written file."""
    if template_path and template_path.exists():
        wb = openpyxl.load_workbook(template_path)
        log.info("Loaded template from %s", template_path)
    else:
        wb = openpyxl.Workbook()
        if "Sheet" in wb.sheetnames:
            del wb["Sheet"]

    # ---- Sheet 1: Validation results ----
    sheet_name = f"Validation_{stats.scenario_name[:20]}"
    if sheet_name in wb.sheetnames:
        del wb[sheet_name]
    ws = wb.create_sheet(sheet_name, 0)

    # Title row
    title_cell = ws.cell(row=7, column=_COL_B, value=f"EuroNCAP Scenario Validation - {stats.scenario_name}")
    title_cell.font = Font(bold=True, size=12)
    ws.merge_cells(start_row=7, start_column=_COL_B, end_row=7, end_column=_COL_F)

    _header_row(ws, row=8)

    category_rows: dict[str, list[int]] = {}
    data_start = 9
    for i, result in enumerate(results):
        row = data_start + i
        _result_row(ws, row, result)
        category_rows.setdefault(result.category, []).append(row)

    _merge_category_cells(ws, category_rows)
    _set_column_widths(ws)
    ws.freeze_panes = "B9"

    # ---- Sheet 2: Issues log (mirrors the 3rd image section) ----
    issues_sheet_name = "Issues_Log"
    if issues_sheet_name in wb.sheetnames:
        del wb[issues_sheet_name]
    ws_issues = wb.create_sheet(issues_sheet_name)
    issue_headers = ["Sr No", "Severity", "Details", "Status", "SelfReview Comment", "R1 Comment", "R2 Comment"]
    hdr_fill = PatternFill("solid", fgColor=_BLUE_HDR)
    hdr_font = Font(bold=True, color=_WHITE)
    for col_idx, h in enumerate(issue_headers, start=2):
        cell = ws_issues.cell(row=56, column=col_idx, value=h)
        cell.fill = hdr_fill
        cell.font = hdr_font
        cell.alignment = Alignment(horizontal="center")

    sr = 1
    for result in results:
        if result.status == "FAIL":
            ws_issues.cell(row=56 + sr, column=2, value=sr)
            ws_issues.cell(row=56 + sr, column=3, value="HIGH")
            ws_issues.cell(row=56 + sr, column=4, value=f"[{result.check_id}] {result.comment}")
            ws_issues.cell(row=56 + sr, column=5, value="Open")
            sr += 1

    ws_issues.column_dimensions[get_column_letter(4)].width = 70

    # ---- Sheet 3: Run Summary ----
    ts = stats.run_timestamp.replace(":", "-").replace(" ", "_")
    summary_name = f"Run_Summary_{ts[:16]}"
    if summary_name in wb.sheetnames:
        del wb[summary_name]
    ws_sum = wb.create_sheet(summary_name)

    summary_rows = [
        ("Scenario Name", stats.scenario_name),
        ("Protocol Version", stats.protocol_version),
        ("Run Timestamp", stats.run_timestamp),
        ("Total Checks", stats.total),
        ("Passed", stats.passed),
        ("Failed", stats.failed),
        ("Manual Review", stats.manual),
        ("NA / Not Applicable", stats.na),
        ("Pass Rate (%)", f"{stats.pass_rate:.1f}%"),
        ("Critical Failures", ", ".join(stats.critical_failures) or "None"),
    ]
    header_fill = PatternFill("solid", fgColor=_BLUE_HDR)
    for row_idx, (label, value) in enumerate(summary_rows, start=2):
        lbl_cell = ws_sum.cell(row=row_idx, column=2, value=label)
        lbl_cell.fill = header_fill
        lbl_cell.font = Font(bold=True, color=_WHITE)

        val_cell = ws_sum.cell(row=row_idx, column=3, value=value)
        if label == "Pass Rate (%)":
            pct = stats.pass_rate
            val_cell.fill = PatternFill(
                "solid",
                fgColor=_GREEN if pct >= 80 else _YELLOW if pct >= 50 else _RED,
            )
        val_cell.alignment = Alignment(wrap_text=True)

    ws_sum.column_dimensions["B"].width = 22
    ws_sum.column_dimensions["C"].width = 60

    wb.save(output_path)
    log.info("Excel report written to %s", output_path)
    return output_path


def write_csv(results: list[CheckResult], stats: SummaryStats, output_path: Path) -> Path:
    """Write results to CSV using stdlib csv (zero extra deps).

    Comment column is intentionally omitted - full details (including failure reasons)
    are written to the Excel report and the audit log only.
    """
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["CheckPoint_ID", "Category", "Description", "Status", "Result"])
        for r in results:
            _, chk_id, desc, status_str, _comment = r.as_row()
            writer.writerow([chk_id, r.category, desc, r.status, status_str])

        writer.writerow([])
        writer.writerow(["=== RUN SUMMARY ==="])
        writer.writerow(["Scenario", stats.scenario_name])
        writer.writerow(["Protocol", stats.protocol_version])
        writer.writerow(["Timestamp", stats.run_timestamp])
        writer.writerow(["Total", stats.total])
        writer.writerow(["Passed", stats.passed])
        writer.writerow(["Failed", stats.failed])
        writer.writerow(["Manual", stats.manual])
        writer.writerow(["NA", stats.na])
        writer.writerow(["Pass Rate", f"{stats.pass_rate:.1f}%"])
        writer.writerow(["Critical Failures", ", ".join(stats.critical_failures) or "None"])

    log.info("CSV report written to %s", output_path)
    return output_path


def setup_logging(log_path: Path) -> None:
    """Configure file + console logging."""
    fmt = "%(asctime)s %(levelname)-8s %(name)s - %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
