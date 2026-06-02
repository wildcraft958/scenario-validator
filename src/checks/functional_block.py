"""CH_FB_01 - Functional Block checks (TA file provisioning).

The TA (Test Automation) file ships alongside every scenario for the dSPACE HIL
harness. CH_FB_01 confirms it is present; CH_FB_02 (column values J-N updated to the
fellow count) requires opening the Excel template and is left as a manual step.
"""
from __future__ import annotations

import logging
from pathlib import Path
from lxml import etree

from ..models import CheckResult, Config

log = logging.getLogger(__name__)

CATEGORY = "FunctionalBlock"

_DESCRIPTIONS = {
    "CH_FB_01": "TA file provided with the scenario (EuroNCAP v4 template); column values are manual (CH_FB_02)",
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
    """TA.xml must be present and use the v4 template structure.

    Deep structure validation (columns J-N updated per fellow count - CH_FB_02)
    requires parsing the Excel template and is left as a manual step. This check
    flags presence only.
    """
    ta_path = scenario_dir / "TA.xml"
    if not ta_path.exists():
        return _make("CH_FB_01", "FAIL", "TA.xml not found in scenario directory")
    try:
        parser = etree.XMLParser(no_network=True, resolve_entities=False, load_dtd=False)
        with ta_path.open("rb") as fh:
            etree.parse(fh, parser)
    except Exception as exc:
        return _make("CH_FB_01", "FAIL", f"TA.xml is malformed or unsafe to parse: {exc}")

    result = _make(
        "CH_FB_01",
        "MANUAL_REVIEW",
        "TA.xml present and parseable with secure XML settings. Manually verify it uses "
        "the EuroNCAP v4 template and that columns J-N / O-S are updated per the number "
        "of fellows (CH_FB_02).",
    )
    result.source_file = "TA.xml"
    return result


def run_all(scenario_dir: Path, config: Config) -> list[CheckResult]:
    return [
        check_fb_01(scenario_dir, config),
    ]
