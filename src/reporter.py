"""Excel and CSV reporter for EuroNCAP scenario validation results.

Sheet 1: Validation   - one row per check
Sheet 2: Issues Log   - failed checks only
Sheet 3: Run Summary  - aggregate stats and audit metadata
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

_VALIDATION_HEADERS = [
    "Check ID",
    "Category",
    "Check name",
    "Result",
    "Comment",
    "Source file",
    "Severity",
    "Automatable or Manual",
    "Timestamp",
]
# CSV omits the Comment column — comments contain proprietary check logic details.
_CSV_HEADERS = [
    "Check ID",
    "Category",
    "Check name",
    "Result",
    "Source file",
    "Severity",
    "Automatable or Manual",
    "Timestamp",
]
_ISSUE_HEADERS = ["Check ID", "Category", "Issue", "File", "Suggested fix", "Severity"]


def _header_row(ws, row: int, headers: list[str]) -> None:
    fills = PatternFill("solid", fgColor=_BLUE_HDR)
    font = Font(bold=True, color=_WHITE)
    for col_idx, text in enumerate(headers, start=1):
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


def _set_column_widths(ws) -> None:
    widths = {1: 16, 2: 18, 3: 56, 4: 12, 5: 64, 6: 24, 7: 14, 8: 22, 9: 22}
    for col, width in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = width


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

    _set_column_widths(ws)
    ws.freeze_panes = "A4"

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
                result.severity,
            ]
            for col_idx, value in enumerate(values, start=1):
                cell = ws_issues.cell(row=row, column=col_idx, value=value)
                cell.alignment = Alignment(wrap_text=True)
            row += 1

    for col, width in {1: 16, 2: 18, 3: 72, 4: 24, 5: 72, 6: 14}.items():
        ws_issues.column_dimensions[get_column_letter(col)].width = width

    # ---- Sheet 3: Run Summary ----
    ws_sum = wb.create_sheet("Run Summary")

    summary_rows = [
        ("Scenario Directory", stats.scenario_dir),
        ("Scenario Name", stats.scenario_name),
        ("Run Timestamp", stats.run_timestamp),
        ("Config Path", stats.config_path),
        ("Template Path", stats.template_path or "None"),
        ("Protocol Version", stats.protocol_version),
        ("Total Checks", stats.total),
        ("Yes Count", stats.passed),
        ("No Count", stats.failed),
        ("NA Count", stats.na),
        ("Manual Count", stats.manual),
        ("Automatable Pass Rate", f"{stats.pass_rate:.1f}%"),
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


def write_csv(results: list[CheckResult], stats: SummaryStats, output_path: Path) -> Path:
    """Write validation results to CSV — Comment column excluded (proprietary)."""
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(_CSV_HEADERS)
        for r in results:
            writer.writerow(r.as_csv_row())

    log.info("CSV report written to %s", output_path)
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
