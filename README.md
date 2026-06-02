# EuroNCAP RoadRunner Scenario Validator

A command-line tool that automatically validates RoadRunner scenario exports against EuroNCAP protocols, replacing the manual Excel review process.

---

## What it does

When a RoadRunner scenario is exported, the team must validate it against a checklist before moving to the OpenDesk phase. This tool reads the exported files and:

1. Runs all checks across 6 categories automatically (Naming, Road, Scenario, Model Desk, Model Review, Functional Block)
2. Writes results to a pre-filled Excel file matching the existing team template
3. Generates a timestamped run summary sheet
4. Optionally writes a CSV alongside the Excel
5. Writes a full audit log for traceability

---

## Quick start

**Linux / macOS:**
```bash
sh setup.sh
python validator.py /path/to/scenario/CCRs_70kph/
```

**Windows:**
```bat
setup.bat
python validator.py C:\path\to\scenario\CCRs_70kph\
```

**Common options:**
```bash
# Also write a CSV report
python validator.py /path/to/scenario/CCRs_70kph/ --csv

# Populate an existing Excel template instead of creating a new file
python validator.py /path/to/scenario/CCRs_70kph/ --template ./Validation_Template.xlsx

# Skip Model Desk checks (when .rd file is not yet available)
python validator.py /path/to/scenario/CCRs_70kph/ --no-rd
```

Output is written alongside the scenario files by default:
```
CCRs_70kph/
  Validation_CCRs_70kph_20260525_221000.xlsx   <- pre-filled report
  Validation_CCRs_70kph_20260525_221000.csv    <- (if --csv flag used)
  validation_run.log                           <- full audit trail
```

---

## Required files in the scenario directory

All files must share the same base name except `TA.xml`:

```
ScenarioName.rrscene
ScenarioName.rrscenario
ScenarioName.xosc
ScenarioName.xodr
ScenarioName.rd
ScenarioName.xml
ScenarioName.txt
TA.xml
```

---

## Reading the Excel output

Each check produces one of four results:

| Result | Colour | Meaning |
|--------|--------|---------|
| `Yes` | Green | Check passed automatically |
| `No` | Red | Check failed - see the Comment column for what to fix |
| `NA` | Grey | Check does not apply to this scenario type |
| `Manual` | Yellow | Visual check - the reviewer must fill this in |

The Excel file has three sheets:
- **Validation sheet** - one row per check with result and comment
- **Issues Log** - all failures pre-populated for quick review
- **Run Summary** - total counts, pass rate, timestamp

---

## Command-line options

```
python validator.py <scenario_dir> [options]

positional arguments:
  scenario_dir          Path to the exported scenario directory

options:
  --config PATH         Path to config.json (default: config.json next to validator.py)
  --output DIR          Where to write reports (default: inside scenario_dir)
  --template PATH       Existing .xlsx template to populate instead of creating new
  --csv                 Also write a CSV report (results only, no internal comments)
  --no-rd               Skip Model Desk checks (use when .rd file is absent)
  --quiet               Suppress console output (still writes to log file)
```

Exit code is `0` if all automatable checks pass, `1` if any fail.

---

## Installing dependencies

The setup scripts detect `uv` if it is already installed and use it for speed. Otherwise they fall back to standard `pip`. Nothing is downloaded from the internet beyond the packages themselves.

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

All protocol values live in `config.json`. You never need to touch Python code to update a threshold.

```jsonc
{
  "lane_width_m": 3.5,
  "junction_radius_m": 8.0,
  "simulation_time_min_s": 100,
  "simulation_time_max_s": 150,
  "scenarios": {
    "CCRs": {
      "type": "longitudinal",
      "vut_speed_range_kmh": [10, 80],
      "target_speed_kmh": 0,
      "impact_overlap_pct": 50
    }
  }
}
```

---

## Adding a new scenario type

Add an entry to the `scenarios` block in `config.json`:

```json
"CPNA-25": {
  "type": "crossing",
  "vut_speed_range_kmh": [20, 60],
  "impact_overlap_pct": 25,
  "direction": "crossing"
}
```

That is the only edit needed. The scenario key's prefix (the text before any `-`, e.g. `CPNA`) is auto-registered for name detection at load time, so you do **not** also have to edit `naming_convention.valid_prefixes`. Every key starting with `_` in `config.json` is treated as a comment and ignored by the loader, so you can leave inline notes for the next editor.

---

## Project structure

```
scenario_validator/
├── validator.py              # Entry point - run this
├── config.json               # EuroNCAP thresholds (edit here, not in code)
├── setup.sh                  # Dependency installer (Linux / macOS)
├── setup.bat                 # Dependency installer (Windows)
├── requirements.txt          # Loose version constraints
├── requirements-lock.txt     # Pinned versions for reproducible installs
├── requirements-hashed.txt   # Hash-verified lockfile for pip --require-hashes
├── src/
│   ├── models.py             # Data models: CheckResult, SummaryStats, Config
│   ├── geometry.py           # Vehicle bounding box overlap calculation
│   ├── reporter.py           # Excel and CSV output
│   ├── parsers/
│   │   ├── xosc.py           # OpenSCENARIO parser
│   │   ├── xodr.py           # OpenDRIVE parser
│   │   └── rd.py             # Model Desk route file parser
│   └── checks/
│       ├── naming.py         # Naming convention checks (CH_NM)
│       ├── road.py           # Road layout checks (CH_RD)
│       ├── scenario.py       # Scenario behaviour checks (CH_SC)
│       ├── model_desk.py     # Model Desk checks (CH_MD)
│       ├── model_review.py   # Model Review checks - speed sanity + decel (CH_MR)
│       └── functional_block.py # Functional Block check - TA file presence (CH_FB)
└── tests/
    └── test_checks.py        # Automated test suite
```

---

## Running tests

```bash
python -m pytest tests/test_checks.py -v
```

Unit and negative tests run without any external files. Integration tests require real scenario files - place them in `tests/scenarios/` and they will be picked up automatically.

---

## Security design

All XML files are parsed with lxml's secure parser - no network access, no external entity resolution, no DTD loading:

```python
etree.XMLParser(no_network=True, resolve_entities=False, load_dtd=False)
```

This prevents XML External Entity (XXE) injection and Billion Laughs attacks from malformed scenario files. No data is sent to any external service. All computation is local.

---

## Dependencies

| Package | Why |
|---------|-----|
| `lxml` | XML parsing and XPath queries |
| `pydantic` | Typed data models and config validation |
| `openpyxl` | Excel report generation |
| `shapely` | Vehicle bounding box geometry |

Standard library only for everything else: `csv`, `json`, `logging`, `pathlib`, `math`, `argparse`.

No pandas. No scipy. No ML frameworks.
