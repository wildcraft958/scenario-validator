"""CH_NM checks - actor naming, filename convention, and scenario file contract.

Consolidated set (CH_NM_01..05):
  NM_01  actor names inside the .xosc follow the EuroNCAP convention
  NM_02  scenario base name follows the structured pattern AND its values agree
         with the protocol (program_type_<n>VUT_<n><Target>_<n>Imp)
  NM_03  all required files are present (7 base extensions + required affix files);
         files are auto-detected so a present-but-misnamed file is never missed
  NM_04  one consistent base name, no duplicate / case-collision filenames
  NM_05  directory holds only known scenario / RoadRunner / report extensions
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from ..models import CheckResult, CheckStatus, Config

CATEGORY = "Naming"


def _make(check_id: str, status: CheckStatus, comment: str = "") -> CheckResult:
    descriptions = {
        "CH_NM_01": "Actor names inside scenario follow EuroNCAP convention (VUT=Ego/VUT/Vehicle, targets=GVT/EPTa/EBTa/EPTc/EMT/SOV etc.)",
        "CH_NM_02": "Scenario name follows program_type_<n>VUT_<n><Target>_<n>Imp and its values agree with the protocol",
        "CH_NM_03": "All required scenario files present (7 base files + ENCAP functional + macro workbooks)",
        "CH_NM_04": "One consistent base name, no duplicate or case-colliding filenames",
        "CH_NM_05": "Scenario directory contains only valid RoadRunner/export/report extensions",
    }
    return CheckResult(
        check_id=check_id,
        category=CATEGORY,
        description=descriptions[check_id],
        status=status,
        comment=comment,
        source_file="scenario directory",
    )


# ---------------------------------------------------------------------------
# Scenario tag + filename parsing
# ---------------------------------------------------------------------------

def detect_scenario_tag(name: str, config: Config) -> str | None:
    """Detect a configured scenario tag from a filename or scenario description."""
    upper_name = name.upper()
    scenario_keys = sorted(config.scenarios, key=len, reverse=True)
    for key in scenario_keys:
        if key.upper() in upper_name:
            return key
    for prefix in sorted(config.naming_convention.get("valid_prefixes", []), key=len, reverse=True):
        if prefix.upper() in upper_name:
            return prefix
    return None


@dataclass
class ParsedName:
    """Result of parsing a scenario base name against the configured grammar."""
    program: str | None = None
    type_tag: str | None = None          # resolved config key, e.g. CCFtap, CPTA
    type_token: str | None = None        # raw 2nd token, e.g. CPTAno
    vut_speed_kmh: int | None = None
    target_speed_kmh: int | None = None
    target_type: str | None = None       # GVT / EPTa / ...
    impact_pct: int | None = None
    tokens: list[str] = field(default_factory=list)
    well_formed: bool = False
    problems: list[str] = field(default_factory=list)


def _split_int_suffix(token: str, suffix: str) -> int | None:
    """'10VUT' + 'VUT' -> 10 ; returns None if it doesn't match <int><suffix>."""
    if not token.upper().endswith(suffix.upper()):
        return None
    head = token[: len(token) - len(suffix)]
    return int(head) if head.isdigit() else None


def _split_int_prefix(token: str) -> tuple[int | None, str]:
    """'30GVT' -> (30, 'GVT') ; '5EPTa' -> (5, 'EPTa'). Non-digit lead -> (None, token)."""
    i = 0
    while i < len(token) and token[i].isdigit():
        i += 1
    if i == 0:
        return None, token
    return int(token[:i]), token[i:]


def parse_scenario_filename(base: str, config: Config) -> ParsedName:
    """Validate `base` against program_type_<n>VUT_<n><Target>_<n>Imp.

    Each slot is checked independently; `problems` lists every malformed slot so
    NM_02 can report precisely. `well_formed` is True only when all five slots parse.
    """
    parsed = ParsedName(tokens=base.split("_"))
    tokens = parsed.tokens
    if len(tokens) != 5:
        parsed.problems.append(
            f"expected 5 tokens 'program_type_<n>{config.vut_speed_suffix}_<n><Target>_<n>{config.impact_suffix}', got {len(tokens)}"
        )
        return parsed

    program, type_token, vut_token, target_token, imp_token = tokens

    # program
    parsed.program = program
    if config.allowed_programs and program.upper() not in {p.upper() for p in config.allowed_programs}:
        parsed.problems.append(f"program '{program}' not in {config.allowed_programs}")

    # type
    parsed.type_token = type_token
    parsed.type_tag = detect_scenario_tag(type_token, config)
    if not parsed.type_tag:
        parsed.problems.append(f"type '{type_token}' is not a configured scenario tag")

    # VUT speed
    parsed.vut_speed_kmh = _split_int_suffix(vut_token, config.vut_speed_suffix)
    if parsed.vut_speed_kmh is None:
        parsed.problems.append(f"VUT-speed token '{vut_token}' must be <int>{config.vut_speed_suffix}")

    # target speed + type
    tgt_speed, tgt_type = _split_int_prefix(target_token)
    parsed.target_speed_kmh = tgt_speed
    parsed.target_type = tgt_type if tgt_type else None
    if tgt_speed is None:
        parsed.problems.append(f"target token '{target_token}' must start with a speed, e.g. 30GVT / 5EPTa")
    elif config.target_type_tokens and tgt_type.upper() not in {t.upper() for t in config.target_type_tokens}:
        parsed.problems.append(f"target type '{tgt_type}' not in {config.target_type_tokens}")

    # impact
    parsed.impact_pct = _split_int_suffix(imp_token, config.impact_suffix)
    if parsed.impact_pct is None:
        parsed.problems.append(f"impact token '{imp_token}' must be <int>{config.impact_suffix}")

    parsed.well_formed = not parsed.problems
    return parsed


# ---------------------------------------------------------------------------
# File discovery helpers
# ---------------------------------------------------------------------------

def _scenario_files(scenario_dir: Path) -> list[Path]:
    return [p for p in scenario_dir.iterdir() if p.is_file()]


def _associated_names(scenario_dir: Path, config: Config, base: str) -> set[str]:
    """Resolved + auto-detected affix filenames in the directory (any role)."""
    found: set[str] = set()
    for spec in config.associated_files(base):
        glob = spec[2]
        found.update(p.name for p in scenario_dir.glob(glob))
    return found


def _base_candidate_files(scenario_dir: Path, config: Config) -> list[Path]:
    """Base-named deliverable files (by required extension), excluding affix workbooks."""
    required = set(config.required_file_extensions)
    base = _canonical_base(scenario_dir, config) or scenario_dir.name
    affix = _associated_names(scenario_dir, config, base)
    return [
        p for p in _scenario_files(scenario_dir)
        if p.suffix in required
        and p.name not in config.required_standalone_files
        and p.name not in affix
    ]


def _canonical_base(scenario_dir: Path, config: Config) -> str | None:
    """Most reliable base name: the .rrscene stem, else the most common base stem."""
    rrscene = sorted(scenario_dir.glob("*.rrscene"))
    if rrscene:
        return rrscene[0].stem
    required = set(config.required_file_extensions)
    standalone = set(config.required_standalone_files)
    candidates = [
        p for p in _scenario_files(scenario_dir)
        if p.suffix in required and p.name not in standalone
    ]
    if not candidates:
        return None
    counts = Counter(p.stem for p in candidates)
    return counts.most_common(1)[0][0]


# ---------------------------------------------------------------------------
# CH_NM_01 - actor naming inside the .xosc
# ---------------------------------------------------------------------------

def _matches_actor_name(name_upper: str, allowed_upper: list[str]) -> bool:
    """Word-boundary match of an actor name against the allowed registry.

    A name matches an allowed token when it equals it exactly, or extends it only with
    a non-alphabetic boundary - a digit ('Vehicle2') or separator ('EPTc_Trajectory').
    A trailing letter ('VehicleX', 'VehicleTest') is a different, non-standard name and
    does NOT match, which the old loose startswith() wrongly accepted.
    """
    for a in allowed_upper:
        if name_upper == a:
            return True
        if name_upper.startswith(a):
            nxt = name_upper[len(a):len(a) + 1]
            if nxt and not nxt.isalpha():
                return True
    return False


def check_nm_01(scenario_dir: Path, config: Config) -> CheckResult:
    """Actor names inside the .xosc must follow EuroNCAP naming convention."""
    from ..parsers import xosc as xosc_mod

    xosc_files = list(scenario_dir.glob("*.xosc"))
    if not xosc_files:
        return _make("CH_NM_01", "MANUAL_REVIEW", "No .xosc file found - cannot verify actor naming convention")

    try:
        root = xosc_mod.load(xosc_files[0])
    except Exception as exc:
        return _make("CH_NM_01", "MANUAL_REVIEW", f"Failed to parse .xosc: {exc}")

    entities = xosc_mod.get_entities(root)
    if not entities:
        return _make("CH_NM_01", "MANUAL_REVIEW", "No ScenarioObject entities found in .xosc")

    vut_names_upper = [n.upper() for n in config.vut_entity_names]
    allowed_upper = [n.upper() for n in config.encap_actor_names] if config.encap_actor_names else []
    # A registered SOV is accepted: per the protocol the overtaken vehicle "can either be a GVT
    # or a real vehicle", so a real-vehicle SOV name (e.g. SK_SUV) is legitimate once the team
    # registers it in config.sov_entity_names. Match these EXACTLY (explicit full names, not
    # EuroNCAP tokens). This keeps NM_01 consistent with the CH_SC_22 SOV exemption; an
    # UNREGISTERED non-standard name still fails, with a hint to register it.
    sov_names_upper = {n.upper() for n in getattr(config, "sov_entity_names", [])}

    vut_found = False
    wrong: list[str] = []

    for entity in entities:
        name = xosc_mod.get_entity_name(entity)
        name_upper = name.upper()
        if any(name_upper == v for v in vut_names_upper):
            vut_found = True
            continue
        if name_upper in sov_names_upper:
            continue
        if not allowed_upper:
            continue
        if not _matches_actor_name(name_upper, allowed_upper):
            wrong.append(name)

    if not vut_found:
        return _make(
            "CH_NM_01",
            "FAIL",
            f"No VUT entity found. VUT must be named one of: {', '.join(config.vut_entity_names)}. "
            f"Entities found: {', '.join(xosc_mod.get_entity_name(e) for e in entities)}",
        )
    if wrong:
        return _make(
            "CH_NM_01",
            "FAIL",
            f"Non-standard actor name(s): {', '.join(wrong)}. "
            f"Use EuroNCAP standard names: GVT, EPTa, EBTa, EPTc, EMT, SOV, Vehicle2, "
            f"LargeObstructionVehicle, SmallObstructionVehicle, etc. If one is the overtaken "
            f"SOV (the protocol permits a real vehicle), add its name to config.sov_entity_names.",
        )
    return _make("CH_NM_01", "PASS", f"All {len(entities)} actor(s) follow EuroNCAP naming convention")


# ---------------------------------------------------------------------------
# CH_NM_02 - structured filename + value cross-check
# ---------------------------------------------------------------------------

def check_nm_02(scenario_dir: Path, config: Config) -> CheckResult:
    """Scenario base name must follow the structured pattern and agree with the protocol.

    Structure: program_type_<n>VUT_<n><Target>_<n>Imp (e.g. AEB_CCFtap_10VUT_30GVT_50Imp).
    Value cross-checks (only when the protocol value is configured - unset values are
    skipped so partially-specified taxonomy entries do not FAIL):
      * VUT speed within the scenario's vut_speed_range_kmh
      * target-type token recognised
      * impact token is one of the allowed protocol overlaps (exact correctness is SC_16/17)
    """
    base = _canonical_base(scenario_dir, config) or scenario_dir.name
    tag = detect_scenario_tag(base, config)
    if not tag:
        return _make(
            "CH_NM_02",
            "FAIL",
            f"Scenario name '{base}' does not contain a configured EuroNCAP scenario tag. "
            "Add the tag to config.json/scenarios or rename the scenario.",
        )

    parsed = parse_scenario_filename(base, config)
    if not parsed.well_formed:
        return _make(
            "CH_NM_02",
            "FAIL",
            f"Scenario name '{base}' does not match program_type_<n>VUT_<n><Target>_<n>Imp: "
            + "; ".join(parsed.problems) + ".",
        )

    proto = config.scenario_protocol(parsed.type_tag or tag)
    if proto is None:
        return _make(
            "CH_NM_02",
            "MANUAL_REVIEW",
            f"Filename well-formed (tag '{parsed.type_tag}'), but no scenario protocol entry "
            "matched. Add an exact config.json/scenarios entry to enable value cross-checks.",
        )

    value_problems: list[str] = []
    if proto.vut_speed_range_kmh and parsed.vut_speed_kmh is not None:
        lo, hi = proto.vut_speed_range_kmh
        if not (lo <= parsed.vut_speed_kmh <= hi):
            value_problems.append(
                f"VUT speed {parsed.vut_speed_kmh} km/h outside protocol range [{lo:.0f}, {hi:.0f}]"
            )
    if config.allowed_impact_overlaps and parsed.impact_pct is not None:
        if parsed.impact_pct not in {int(v) for v in config.allowed_impact_overlaps}:
            value_problems.append(
                f"impact {parsed.impact_pct}% not an allowed overlap {sorted({int(v) for v in config.allowed_impact_overlaps})}"
            )

    if value_problems:
        return _make("CH_NM_02", "FAIL", f"Scenario '{base}' - " + "; ".join(value_problems) + ".")

    # Cross-check the filename target-type token against the actual .xosc entity category,
    # so a mislabeled filename (e.g. '30GVT' on a pedestrian scenario) is caught.
    mismatch = _target_type_category_mismatch(scenario_dir, config, parsed.target_type)
    detail = f"tag={parsed.type_tag}, {parsed.vut_speed_kmh}km/h VUT, {parsed.target_speed_kmh}{parsed.target_type}, {parsed.impact_pct}% impact"
    if mismatch:
        return _make(
            "CH_NM_02",
            "MANUAL_REVIEW",
            f"Filename well-formed ({detail}), but {mismatch} - likely a naming mistake; verify.",
        )
    return _make("CH_NM_02", "PASS", f"Filename well-formed and values agree with protocol ({detail}).")


def _target_type_category_mismatch(scenario_dir: Path, config: Config, target_type: str | None) -> str | None:
    """Return a message if the filename target token disagrees with the .xosc target
    entity category, else None (no .xosc / unknown token / category -> no opinion).

    `expected` is the SET of OSC categories that are protocol-correct for the token, so a
    cyclist/motorcyclist exported by RoadRunner as <Vehicle> overlaps and is NOT flagged.
    """
    expected = config.target_type_to_category.get(target_type or "")
    if not expected:
        return None
    from ..parsers import xosc as xosc_mod

    xosc_files = list(scenario_dir.glob("*.xosc"))
    if not xosc_files:
        return None
    try:
        root = xosc_mod.load(xosc_files[0])
    except Exception:
        return None
    vut_upper = {n.upper() for n in config.vut_entity_names}
    cats: list[str] = []
    for entity in xosc_mod.get_entities(root):
        name = xosc_mod.get_entity_name(entity)
        if name.upper() in vut_upper:
            continue
        cat = xosc_mod.get_entity_category(root, name)
        if cat:
            cats.append(cat)
    if cats and not (expected & set(cats)):
        return (
            f"filename target '{target_type}' implies a {'/'.join(sorted(expected))} but the "
            f"scene target(s) are {', '.join(sorted(set(cats)))}"
        )
    return None


# ---------------------------------------------------------------------------
# CH_NM_03 - required files present (base + auto-detected affix files)
# ---------------------------------------------------------------------------

def check_nm_03(scenario_dir: Path, config: Config, skip_rd: bool = False) -> CheckResult:
    """All required files must be present.

    Base files are matched by `<base><ext>`; affix workbooks (functional/macro) are
    AUTO-DETECTED by deriving a glob from the configured pattern, so a present-but-
    misnamed file is found instead of being short-circuited to "missing".
    """
    base = _canonical_base(scenario_dir, config)
    if not base:
        return _make("CH_NM_03", "FAIL", "No scenario files found - cannot determine base name")

    missing: list[str] = []
    notes: list[str] = []

    # 1. base-named files by extension (.rd honours --no-rd, folding old NM_07)
    rd_skipped = False
    for ext in config.required_file_extensions:
        if ext == ".rd" and skip_rd:
            rd_skipped = (scenario_dir / f"{base}{ext}").exists()
            continue
        if not (scenario_dir / f"{base}{ext}").exists():
            missing.append(f"{base}{ext}")

    # 2. legacy exact standalone files (kept for back-compat; normally empty)
    for standalone in config.required_standalone_files:
        if not (scenario_dir / standalone).exists():
            missing.append(standalone)

    # 3. affix workbooks - auto-detected (robust to base drift / stale config)
    for role, expected, glob, required in config.associated_files(base):
        if (scenario_dir / expected).exists():
            continue
        matches = list(scenario_dir.glob(glob))
        if matches:
            notes.append(f"{role} file found as '{matches[0].name}' (expected '{expected}' - verify base)")
        elif required:
            missing.append(expected)
        else:
            notes.append(f"optional {role} file '{expected}' absent")

    # 4. optional catalog files (presence/absence never fails)
    optional = getattr(config, "optional_standalone_files", [])
    opt_present = [opt for opt in optional if (scenario_dir / opt).exists()]
    opt_absent = [opt for opt in optional if opt not in opt_present]
    if opt_present:
        notes.append(f"Optional catalog file(s) present: {', '.join(opt_present)}.")
    if opt_absent:
        notes.append(f"Optional catalog file(s) absent (not required): {', '.join(opt_absent)}.")

    if skip_rd:
        notes.append(".rd present but --no-rd requested" if rd_skipped else ".rd checks skipped (--no-rd)")

    note_str = (" " + " ".join(notes)) if notes else ""
    if not missing:
        return _make("CH_NM_03", "PASS", note_str.strip())
    return _make("CH_NM_03", "FAIL", f"Missing files: {', '.join(missing)}.{note_str}")


# ---------------------------------------------------------------------------
# CH_NM_04 - base-name consistency + duplicate / case collisions (folds old NM_06)
# ---------------------------------------------------------------------------

def check_nm_04(scenario_dir: Path, config: Config) -> CheckResult:
    """All base files share one base name, with no duplicate or case-colliding names."""
    candidates = _base_candidate_files(scenario_dir, config)
    if not candidates:
        return _make("CH_NM_04", "FAIL", "No base-named scenario files found")

    issues: list[str] = []

    bases = sorted({p.stem for p in candidates})
    if len(bases) > 1:
        by_base = {b: sorted(p.name for p in candidates if p.stem == b) for b in bases}
        details = "; ".join(f"{b}: {', '.join(names)}" for b, names in by_base.items())
        issues.append(f"multiple base names - all base files must share one name ({details})")

    # case-insensitive duplicate filenames across the whole directory
    lower_names = Counter(p.name.lower() for p in _scenario_files(scenario_dir))
    dup = sorted(name for name, count in lower_names.items() if count > 1)
    if dup:
        issues.append(f"case-insensitive duplicate filenames: {', '.join(dup)}")

    # case-collision among base stems (e.g. Foo vs foo)
    stems_by_lower: dict[str, set[str]] = {}
    for stem in {p.stem for p in candidates}:
        stems_by_lower.setdefault(stem.lower(), set()).add(stem)
    collisions = sorted(low for low, variants in stems_by_lower.items() if len(variants) > 1)
    if collisions:
        issues.append(f"case-colliding base names: {', '.join(collisions)}")

    if issues:
        return _make("CH_NM_04", "FAIL", "; ".join(issues))
    return _make("CH_NM_04", "PASS", f"Base name '{bases[0]}' is consistent")


# ---------------------------------------------------------------------------
# CH_NM_05 - extension allowlist
# ---------------------------------------------------------------------------

def check_nm_05(scenario_dir: Path, config: Config) -> CheckResult:
    """Detect wrong extensions while allowing known RoadRunner / report outputs."""
    allowed_suffixes = set(config.required_file_extensions) | {
        ".geojson", ".osgb", ".xlsx", ".xlsm", ".csv", ".log",
    }
    wrong: list[str] = []
    case_risk: list[str] = []
    for path in _scenario_files(scenario_dir):
        if path.name in config.required_standalone_files:
            continue
        if path.suffix != path.suffix.lower():
            case_risk.append(path.name)
        if path.suffix.lower() not in allowed_suffixes:
            wrong.append(path.name)

    if wrong:
        return _make(
            "CH_NM_05",
            "FAIL",
            f"Unsupported file extension(s): {', '.join(sorted(wrong))}. "
            "Use only configured scenario files plus known RoadRunner auxiliary/report outputs.",
        )
    if case_risk:
        return _make(
            "CH_NM_05",
            "FAIL",
            f"Case-sensitive extension risk: {', '.join(sorted(case_risk))}. "
            "Use lower-case required extensions exactly.",
        )
    return _make("CH_NM_05", "PASS")


def run_all(scenario_dir: Path, config: Config, skip_rd: bool = False) -> list[CheckResult]:
    return [
        check_nm_01(scenario_dir, config),
        check_nm_02(scenario_dir, config),
        check_nm_03(scenario_dir, config, skip_rd=skip_rd),
        check_nm_04(scenario_dir, config),
        check_nm_05(scenario_dir, config),
    ]
