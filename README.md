# EuroNCAP RoadRunner Scenario Validator

A command-line tool that automatically validates RoadRunner scenario exports against the EuroNCAP protocols, replacing the manual Excel review the team runs after every export.

---

## What it does

When a RoadRunner scenario is exported, it must be validated against the checklist before the OpenDesk / HIL phase. This tool reads the exported files and:

1. Runs **41 checks across 6 categories** automatically: Naming (5), Road (6), Scenario (22), Model Desk (5), Model Review (2), Functional Block (1).
2. Estimates the **impact location** geometrically from the trajectories, grounded in the EuroNCAP Frontal Collisions v1.1 reference-point definition (§1.2.5), not a manual visual check.
3. Writes a colour-coded, pre-filled Excel report (3 sheets) matching the team template.
4. Writes a full audit log for traceability.

Fully offline. No cloud, no external API, no database.

---

## Quick start

**Linux / macOS:**
```bash
sh setup.sh
python validator.py /path/to/scenario/AEB_CCRs_50VUT_30GVT_50Imp/
```

**Windows:**
```bat
setup.bat
python validator.py C:\path\to\scenario\AEB_CCRs_50VUT_30GVT_50Imp\
```

Run it against a bundled example to see it work:
```bash
python validator.py examples/CPNCO/ --no-rd
```

**Common options:**
```bash
# Skip the Model Desk (.rd) checks when the route file is not yet available
python validator.py /path/to/scenario/ --no-rd

# Use the Excel config instead of config.json
python validator.py /path/to/scenario/ --config config.xlsx

# Write reports to a chosen directory
python validator.py /path/to/scenario/ --output ./reports/

# Suppress console output (still writes the log file) - for CI
python validator.py /path/to/scenario/ --quiet
```

Output is written alongside the scenario files by default:
```
AEB_CCRs_50VUT_30GVT_50Imp/
  Validation_AEB_CCRs_50VUT_30GVT_50Imp_20260610_221000.xlsx   <- pre-filled report
  validation_run.log                                            <- full audit trail
```

---

## Required files in the scenario directory

The seven base files all share one base name; the two affix workbooks wrap that base name and are auto-detected (a present-but-misnamed workbook is found rather than reported missing):

```
<base>.rrscene
<base>.rrscenario
<base>.xosc
<base>.xodr
<base>.rd
<base>.xml
<base>.txt
ENCAP_Scenario_func_<base>.xlsm    <- functional / Test-Automation workbook (HIL)
MACRO_<base>.xlsx                   <- macro workbook
```

`<base>` follows the team convention `program_type_<n>VUT_<n><Target>_<n>Imp`, e.g. `AEB_CCFtap_20VUT_45GVT_50Imp`. The `.rd` file is optional under `--no-rd`. `VehicleCatalog.xosc` / `PedestrianCatalog.xosc` are recognised but never required.

---

## Reading the Excel output

Each check produces one of four results:

| Result | Colour | Meaning |
|--------|--------|---------|
| `Yes` | Green | Check passed automatically |
| `No` | Red | Check failed - see the Comment column for what to fix |
| `NA` | Grey | Check does not apply to this scenario type |
| `Manual` | Yellow | The tool measured the data but a human (or HIL) must confirm |

The Excel file has three sheets:
- **Validation** - one row per check with result and comment
- **Issues Log** - every failure pre-populated for quick triage
- **Run Summary** - total counts, automatable pass rate, timestamp, CLI command

The **automatable pass rate** counts only PASS/FAIL checks (it excludes NA and Manual), so it reflects the checks the tool can actually decide.

---

## Command-line options

```
python validator.py <scenario_dir> [options]

positional arguments:
  scenario_dir          Path to the exported scenario directory

options:
  --config PATH         Path to config.json or config.xlsx
                        (default: config.json next to validator.py)
  --output DIR          Where to write reports (default: inside scenario_dir)
  --no-rd               Skip the Model Desk checks (use when the .rd file is absent)
  --quiet               Suppress console output (still writes the log file)
  --check-config        Validate the config file, print the effective settings, and exit
```

Exit code is `0` if all automatable checks pass, `1` if any fail. `NA` and `Manual` never affect the exit code.

---

## How impact location is checked (the differentiator)

EuroNCAP §1.2.5 defines the impact percentage as where a **per-actor, per-motion reference point** on the target coincides with the VUT width (or length for side impacts). That point differs for a car, pedestrian, cyclist, or motorcyclist, and for longitudinal vs turning vs crossing motion. The tool (CH_SC_16 / CH_SC_17):

1. Resolves the target type (GVT / SOV / EPTa / EPTc / EBTa / EMT) from the entity name, then the filename token, then the bounding-box shape.
2. Picks the protocol reference point for that actor and motion, projects it into the VUT frame along the trajectories, and reads the impact percentage at first contact.
3. For turn-across-path geometry, where the impacting corner contacts before the reference point reaches the impact plane (§1.2.5.2), it switches to a rotation-robust overlap-centre estimate so the designed overlap is still recovered (e.g. CCFtap reads ~50%, not a misleading ~88%).
4. Returns **PASS** when the estimate is within tolerance of the designed value (from the filename `Imp` token), **MANUAL_REVIEW** when the geometry is sensitive within the protocol's ±0.1 s sync window, and **FAIL** otherwise.

The estimate is design-time kinematics; **HIL remains the final authority** for impact location.

---

## Installing dependencies

The setup scripts detect `uv` if it is installed and use it for speed, otherwise they fall back to `pip`. Runtime dependencies are `lxml`, `pydantic`, `openpyxl`, and `shapely` only - nothing is downloaded beyond the packages themselves.

**Linux / macOS:**
```bash
sh setup.sh            # standard install
sh setup.sh --hashed   # enforce cryptographic hash verification (Linux x86_64 only)
```

**Windows:**
```bat
setup.bat
setup.bat --hashed
```

To install manually:
```bash
pip install -r requirements-lock.txt
```

---

## Updating EuroNCAP thresholds

All protocol values live in `config.json`. You never edit Python to change a threshold or add a scenario type.

```jsonc
{
  "lane_width_m": 3.5,
  "junction_radius_m": 8.0,
  "scenarios": {
    "CCFtap": { "type": "crossing", "vut_speed_range_kmh": [10, 25] }
  }
}
```

A scenario entry carries only what cannot be generalised from the data: `type` (the impact-tolerance routing key - `crossing` -> CH_SC_16 ±5%, `longitudinal`/`head-on` -> CH_SC_17 ±1%), `vut_speed_range_kmh`, and the optional `side_impact` / `has_sov` flags. Adding a scenario type is one entry under `scenarios` - its key prefix is auto-registered for filename detection, so you do **not** also edit `naming_convention.valid_prefixes`. Every key starting with `_` is treated as a comment and ignored by the loader.

**Prefer Excel?** Edit `config.xlsx` and run with `--config config.xlsx`. Both readers feed the same Pydantic model, so they validate identically. Regenerate the workbook after a JSON edit with `python tools/make_config_xlsx.py` (it round-trip-verifies that JSON and Excel agree). Validate any edit without a full run:

```bash
python validator.py --check-config --config config.json
```

See `CONFIG_GUIDE.md` for what every key means and which are protocol constants vs site settings.

---

## Project structure

```
scenario_validator/
├── validator.py              # Entry point - run this
├── config.json               # EuroNCAP thresholds (edit here, not in code)
├── config.xlsx               # Same thresholds as a 6-sheet Excel workbook
├── tools/make_config_xlsx.py # Regenerate config.xlsx from config.json (round-trip checked)
├── setup.sh / setup.bat      # Dependency installers
├── requirements.txt          # Loose version constraints
├── requirements-lock.txt     # Pinned versions for reproducible installs
├── src/
│   ├── models.py             # Data models: CheckResult, SummaryStats, Config
│   ├── geometry.py           # §1.2.5 impact-location estimator (per-actor reference point)
│   ├── reporter.py           # Excel output
│   ├── parsers/
│   │   ├── xosc.py           # OpenSCENARIO parser (secure lxml)
│   │   ├── xodr.py           # OpenDRIVE parser (secure lxml)
│   │   └── rd.py             # Model Desk route-file parser
│   └── checks/
│       ├── naming.py         # Naming convention checks (CH_NM_01..05)
│       ├── road.py           # Road layout checks (CH_RD_01..06)
│       ├── scenario.py       # Scenario behaviour checks (CH_SC_01..22)
│       ├── model_desk.py     # Model Desk route checks (CH_MD_01..05)
│       ├── model_review.py   # Speed sanity + braking decel (CH_MR_01..02)
│       └── functional_block.py # Functional / Test-Automation workbook (CH_FB_01)
└── tests/                    # 174 tests (unit + mutation robustness + protocol)
```

---

## Running tests

```bash
python -m pytest tests/ -q      # 174 tests
```

The suite mixes unit tests, mutation-based robustness tests on the real RoadRunner example exports (`examples/`), and protocol-grounded impact tests. Static typing is clean under `pyright src/ validator.py tools/`.

---

## Security design

All XML files are parsed with lxml's secure parser - no network access, no external entity resolution, no DTD loading:

```python
etree.XMLParser(no_network=True, resolve_entities=False, load_dtd=False)
```

This blocks XML External Entity (XXE) injection, SSRF via DOCTYPE, and Billion Laughs denial-of-service from malformed scenario files. All entity-name XPath lookups use lxml's parameterised `$variable` syntax so a name containing an apostrophe or XPath metacharacter cannot break or inject a query. No data is sent anywhere; all computation is local.

---

## Dependencies

| Package | Why |
|---------|-----|
| `lxml` | XML parsing and XPath queries |
| `pydantic` | Typed data models and config validation |
| `openpyxl` | Excel report generation (and the config.xlsx reader) |
| `shapely` | Vehicle bounding-box geometry for the impact estimator |

Standard library for everything else (`json`, `logging`, `pathlib`, `math`, `argparse`). No pandas, no scipy, no ML frameworks.
