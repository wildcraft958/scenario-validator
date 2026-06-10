"""CH_FB_01 - Functional Block check (ENCAP functional / Test-Automation workbook).

Every scenario ships an ENCAP functional workbook (`ENCAP_Scenario_func_<base>.xlsm`)
used by the dSPACE HIL harness. CH_FB_01 confirms it is present and is a valid
workbook (OOXML/zip). Deep column validation (J-N updated per fellow count) is the
manual CH_FB_02 step. The file is auto-detected by a glob derived from the configured
pattern, so a present-but-misnamed file is found rather than reported missing.
"""
from __future__ import annotations

import logging
import zipfile
from pathlib import Path

from ..models import CheckResult, Config
from .naming import _canonical_base

log = logging.getLogger(__name__)

CATEGORY = "FunctionalBlock"

_DESCRIPTIONS = {
    "CH_FB_01": "ENCAP functional / Test-Automation workbook provided (ENCAP_Scenario_func); column values are manual (CH_FB_02)",
}


def _make(check_id: str, status: str, comment: str = "") -> CheckResult:
    return CheckResult(
        check_id=check_id,
        category=CATEGORY,
        description=_DESCRIPTIONS[check_id],
        status=status,  # type: ignore[arg-type]
        comment=comment,
    )


def check_fb_01(scenario_dir: Path, config: Config) -> CheckResult:
    """The ENCAP functional workbook must be present and a valid workbook (zip/OOXML)."""
    base = _canonical_base(scenario_dir, config) or scenario_dir.name
    expected = config.functional_file_name(base)
    glob = config.functional_file_pattern.replace("{base}", "*")

    path = scenario_dir / expected
    note = ""
    if not path.exists():
        matches = list(scenario_dir.glob(glob))
        if not matches:
            return _make("CH_FB_01", "FAIL", f"{expected} not found in scenario directory")
        path = matches[0]
        note = f" (found as '{path.name}', expected '{expected}' - verify base name)"

    if not zipfile.is_zipfile(path):
        return _make("CH_FB_01", "FAIL", f"{path.name} is not a valid .xlsm workbook (not a zip/OOXML file)")

    result = _make(
        "CH_FB_01",
        "MANUAL_REVIEW",
        f"{path.name} present and a valid workbook.{note} Manually verify it uses the EuroNCAP "
        "v4 template and that columns J-N / O-S are updated per the number of fellows (CH_FB_02).",
    )
    result.source_file = path.name
    return result


def run_all(scenario_dir: Path, config: Config) -> list[CheckResult]:
    return [
        check_fb_01(scenario_dir, config),
    ]
