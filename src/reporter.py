"""Excel reporter for EuroNCAP scenario validation results.

Sheet 1: Validation   - one row per check
Sheet 2: Issues Log   - failed checks only
Sheet 3: Run Summary  - aggregate stats and audit metadata
"""
from __future__ import annotations

import logging
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.views import Selection

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

# Trust-tier fills for the Automation Level column (green = trust it, yellow = confirm,
# grey = human decides).
_AUTOMATION_FILL = {
    "Fully Automated": PatternFill("solid", fgColor=_GREEN),
    "Partially Automated": PatternFill("solid", fgColor=_YELLOW),
    "Manual": PatternFill("solid", fgColor=_GREY),
}

_VALIDATION_HEADERS = [
    "Check ID",
    "Category",
    "Check name",
    "Result",
    "Comment",
    "Source file",
    "Timestamp",
    "Automation Level",
    "Automation - why",
]
_ISSUE_HEADERS = ["Check ID", "Category", "Issue", "File", "Suggested fix"]
_VALIDATION_COL_CHARS = {1: 16, 2: 16, 3: 52, 4: 10, 5: 60, 6: 22, 7: 20, 8: 20, 9: 50}


def _header_row(ws, row: int, headers: list[str], start_col: int = 1) -> None:
    fills = PatternFill("solid", fgColor=_BLUE_HDR)
    font = Font(bold=True, color=_WHITE)
    for col_idx, text in enumerate(headers, start=start_col):
        cell = ws.cell(row=row, column=col_idx, value=text)
        cell.fill = fills
        cell.font = font
        cell.alignment = Alignment(horizontal="center", wrap_text=True)


def _result_row(ws, row: int, result: CheckResult) -> None:
    values = result.as_validation_row()
    for col_idx, value in enumerate(values, start=1):
        cell = ws.cell(row=row, column=col_idx, value=value)
        cell.alignment = Alignment(wrap_text=True)
        if col_idx == 4:
            cell.fill = _STATUS_FILL.get(str(value), PatternFill("solid", fgColor=_GREY))
            cell.font = _STATUS_FONT.get(str(value), Font())
            cell.alignment = Alignment(horizontal="center")
        elif col_idx == 8:
            cell.fill = _AUTOMATION_FILL.get(str(value), PatternFill("solid", fgColor=_GREY))
            cell.alignment = Alignment(horizontal="center", wrap_text=True)


def _set_column_widths(ws, widths: dict[int, int]) -> None:
    for col, width in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = width


def _auto_row_heights(ws, data_start_row: int, col_char_widths: dict[int, int],
                      min_height: float = 15.0, line_height: float = 14.0) -> None:
    """Set row heights so wrapped text is fully visible without double-clicking.

    openpyxl sets wrap_text=True but leaves row height at the Excel default (15pt),
    which clips multi-line content. This function estimates the number of wrapped
    lines in each cell based on text length ÷ column character width and sizes
    the row to fit the tallest cell.
    """
    import math
    for row in ws.iter_rows(min_row=data_start_row):
        max_lines = 1
        for cell in row:
            if cell.value is None:
                continue
            text = str(cell.value)
            col_idx = cell.column
            col_w = col_char_widths.get(col_idx, 15)
            # Each Excel "character width" unit ≈ 1 character at default font. Count wrapped
            # lines per explicit paragraph (split on newlines) so multi-line comments are not
            # clipped, then sum.
            lines = sum(max(1, math.ceil(len(seg) / max(col_w, 1))) for seg in text.split("\n"))
            max_lines = max(max_lines, max(1, lines))
        height = min_height + (max_lines - 1) * line_height
        ws.row_dimensions[row[0].row].height = height


def write_excel(
    results: list[CheckResult],
    stats: SummaryStats,
    output_path: Path,
) -> Path:
    """Write full Excel report. Returns path of written file."""
    wb = openpyxl.Workbook()
    if "Sheet" in wb.sheetnames:
        del wb["Sheet"]

    for sheet_name in ("Validation", "Issues Log", "Run Summary"):
        if sheet_name in wb.sheetnames:
            del wb[sheet_name]

    # ---- Sheet 1: Validation results ----
    ws = wb.create_sheet("Validation", 0)
    title_cell = ws.cell(row=1, column=1, value=f"EuroNCAP Scenario Validation - {stats.scenario_name}")
    title_cell.font = Font(bold=True, size=12)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(_VALIDATION_HEADERS))

    _header_row(ws, row=3, headers=_VALIDATION_HEADERS)

    data_start = 4
    for i, result in enumerate(results):
        row = data_start + i
        _result_row(ws, row, result)

    _set_column_widths(ws, _VALIDATION_COL_CHARS)
    ws.freeze_panes = "A4"
    # openpyxl leaves the bottom (scrollable) pane's active cell at A1, which sits inside the
    # frozen header region. Excel then scrolls the bottom pane up to row 1 on redraw, painting
    # the title + header rows a SECOND time below the frozen ones (the "duplicate header"
    # artifact). Anchor the bottom-pane selection to the first scrollable cell so it opens clean.
    ws.sheet_view.selection = [Selection(pane="bottomLeft", activeCell="A4", sqref="A4")]
    # Set header rows to fixed heights; auto-size data rows
    ws.row_dimensions[1].height = 20
    ws.row_dimensions[3].height = 28
    _auto_row_heights(ws, data_start_row=4, col_char_widths=_VALIDATION_COL_CHARS)

    # ---- Sheet 2: Issues log ----
    ws_issues = wb.create_sheet("Issues Log")
    _header_row(ws_issues, row=1, headers=_ISSUE_HEADERS)

    row = 2
    for result in results:
        if result.status == "FAIL":
            values = [
                result.check_id,
                result.category,
                result.comment,
                result.source_file,
                result.suggested_fix,
            ]
            for col_idx, value in enumerate(values, start=1):
                cell = ws_issues.cell(row=row, column=col_idx, value=value)
                cell.alignment = Alignment(wrap_text=True)
            row += 1

    _ISSUES_COL_WIDTHS = {1: 16, 2: 16, 3: 64, 4: 22, 5: 64}
    for col, width in _ISSUES_COL_WIDTHS.items():
        ws_issues.column_dimensions[get_column_letter(col)].width = width
    ws_issues.row_dimensions[1].height = 28
    _auto_row_heights(ws_issues, data_start_row=2, col_char_widths=_ISSUES_COL_WIDTHS)

    # ---- Sheet 3: Run Summary ----
    ws_sum = wb.create_sheet("Run Summary")

    fully = sum(1 for r in results if r.automation_level == "Fully Automated")
    partial = sum(1 for r in results if r.automation_level == "Partially Automated")
    manual_auto = sum(1 for r in results if r.automation_level == "Manual")
    summary_rows = [
        ("Scenario Directory", stats.scenario_dir),
        ("Scenario Name", stats.scenario_name),
        ("Run Timestamp", stats.run_timestamp),
        ("Config Path", stats.config_path),
        ("Protocol Version", stats.protocol_version),
        ("Total Checks", stats.total),
        ("Yes Count", stats.passed),
        ("No Count", stats.failed),
        ("NA Count", stats.na),
        ("Manual Count", stats.manual),
        ("Automatable Pass Rate", f"{stats.pass_rate:.1f}%"),
        ("Automation - Fully", fully),
        ("Automation - Partially", partial),
        ("Automation - Manual", manual_auto),
        ("Final Status", stats.final_status),
        ("CLI Command Used", stats.cli_command),
        ("Failed Check IDs", ", ".join(stats.critical_failures) or "None"),
    ]
    header_fill = PatternFill("solid", fgColor=_BLUE_HDR)
    for row_idx, (label, value) in enumerate(summary_rows, start=2):
        lbl_cell = ws_sum.cell(row=row_idx, column=2, value=label)
        lbl_cell.fill = header_fill
        lbl_cell.font = Font(bold=True, color=_WHITE)

        val_cell = ws_sum.cell(row=row_idx, column=3, value=value)
        if label == "Automatable Pass Rate":
            pct = stats.pass_rate
            val_cell.fill = PatternFill(
                "solid",
                fgColor=_GREEN if pct >= 80 else _YELLOW if pct >= 50 else _RED,
            )
        if label == "Final Status":
            val_cell.fill = PatternFill("solid", fgColor=_GREEN if value == "PASS" else _RED)
            val_cell.font = Font(bold=True, color=_WHITE if value == "FAIL" else "FF000000")
        val_cell.alignment = Alignment(wrap_text=True)

    ws_sum.column_dimensions["B"].width = 22
    ws_sum.column_dimensions["C"].width = 60

    wb.save(output_path)
    log.info("Excel report written to %s", output_path)
    return output_path


def write_reference_checklist(
    results: list[CheckResult],
    stats: SummaryStats,
    output_path: Path,
) -> Path:
    """Write a workbook matching the reviewer checklist (Summary / ChecklistFinal /
    Prequisites). Our verdict fills Self Review; Review1/Review2 stay blank for humans;
    two extra columns carry the automation trust level. Checkpoints the validator does
    not compute (MD_06-11, FB_02) export as Manual rows with the reference wording."""
    from .automation import automation_for
    from .checklist_template import (
        CHECKLIST_COLUMNS,
        CHECKLIST_HEADER_LABELS,
        MASTER_CHECKLIST,
        PREREQUISITES,
        SUMMARY_META,
    )

    by_id = {r.check_id: r for r in results}
    wb = openpyxl.Workbook()
    if "Sheet" in wb.sheetnames:
        del wb["Sheet"]

    # ---- Sheet 1: Summary ----
    ws = wb.create_sheet("Summary")
    ws.cell(row=2, column=3, value="EuroNCAP Scenario Review Checklist").font = Font(bold=True, size=12)
    for i, (label, value) in enumerate(SUMMARY_META, start=4):
        ws.cell(row=i, column=3, value=label).font = Font(bold=True)
        ws.cell(row=i, column=4, value=value)
    ws.column_dimensions["C"].width = 20
    ws.column_dimensions["D"].width = 60

    # ---- Sheet 2: ChecklistFinal ----
    ws = wb.create_sheet("ChecklistFinal")
    header_values = {
        "Release": "PriorityA",
        "Protocol Name": stats.protocol_version,
        "Responsible": "",
        "Reviewer": "",
        "Date": stats.run_timestamp,
    }
    for i, label in enumerate(CHECKLIST_HEADER_LABELS, start=2):
        ws.cell(row=i, column=3, value=label).font = Font(bold=True)
        ws.cell(row=i, column=4, value=header_values.get(label, ""))

    table_header_row = 8
    _header_row(ws, table_header_row, CHECKLIST_COLUMNS, start_col=2)

    row = table_header_row + 1
    last_cat = None
    for cat, cid, ref_text in MASTER_CHECKLIST:
        result = by_id.get(cid)
        if cat != last_cat:
            ws.cell(row=row, column=2, value=cat).font = Font(bold=True)
            last_cat = cat
        ws.cell(row=row, column=3, value=cid)
        text = result.description if result else ref_text
        ws.cell(row=row, column=4, value=text).alignment = Alignment(wrap_text=True)

        verdict = result.result if result else "Manual"
        sc = ws.cell(row=row, column=5, value=verdict)
        sc.fill = _STATUS_FILL.get(verdict, PatternFill("solid", fgColor=_GREY))
        sc.font = _STATUS_FONT.get(verdict, Font())
        sc.alignment = Alignment(horizontal="center")
        # columns 6 (Review1) and 7 (Review2) left blank for human reviewers

        level, why = (result.automation_level, result.automation_note) if result else automation_for(cid)
        al = ws.cell(row=row, column=8, value=level)
        al.fill = _AUTOMATION_FILL.get(level, PatternFill("solid", fgColor=_GREY))
        al.alignment = Alignment(horizontal="center", wrap_text=True)
        ws.cell(row=row, column=9, value=why).alignment = Alignment(wrap_text=True)
        row += 1

    # Config-driven (config.checklist_column_widths), falling back to the default for any
    # column the team's config omits.
    default_checklist_widths = {2: 16, 3: 18, 4: 72, 5: 12, 6: 14, 7: 14, 8: 20, 9: 50}
    checklist_widths = {**default_checklist_widths, **stats.checklist_column_widths}
    for col, width in checklist_widths.items():
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.row_dimensions[table_header_row].height = 28
    ws.freeze_panes = f"A{table_header_row + 1}"
    _auto_row_heights(ws, data_start_row=table_header_row + 1, col_char_widths=checklist_widths)

    # ---- Sheet 3: Prequisites ----
    ws = wb.create_sheet("Prequisites")
    _header_row(ws, 2, ["SL.NO", "Rules"], start_col=1)
    for i, rule in enumerate(PREREQUISITES, start=1):
        ws.cell(row=2 + i, column=1, value=i)
        ws.cell(row=2 + i, column=2, value=rule).alignment = Alignment(wrap_text=True)
    ws.column_dimensions["A"].width = 8
    ws.column_dimensions["B"].width = 100
    _auto_row_heights(ws, data_start_row=3, col_char_widths={1: 8, 2: 100})

    wb.save(output_path)
    log.info("Reference checklist written to %s", output_path)
    return output_path


def setup_logging(log_path: Path, quiet: bool = False) -> None:
    """Configure file + console logging."""
    fmt = "%(asctime)s %(levelname)-8s %(name)s - %(message)s"
    handlers: list[logging.Handler] = [logging.FileHandler(log_path, encoding="utf-8")]
    if not quiet:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=handlers,
        force=True,
    )
