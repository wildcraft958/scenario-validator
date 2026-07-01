# Configuration Guide

The validator reads its settings from **either** of two files - pick whichever you prefer:

| File | Who it's for | How |
|---|---|---|
| `config.xlsx` | Test engineers (recommended) | Edit in Excel, then run `python validator.py <dir> --config config.xlsx` |
| `config.json` | Developers | Edit in a text editor; the validator gives plain-language error messages on mistakes |

After ANY edit, verify it loads cleanly (no scenario run needed):

```
python validator.py --check-config --config config.xlsx
```

To regenerate `config.xlsx` after developers change `config.json`:

```
python tools/make_config_xlsx.py
```

---

## The four kinds of settings

### 1. PROTOCOL CONSTANTS - do not edit
EuroNCAP-mandated values, confirmed against the official protocol and checklist.
Changing them makes the report wrong, not the scenario right.

| Key | Value | Meaning |
|---|---|---|
| `protocol_version` | text | Label printed on every report header |
| `lane_width_m` | 3.5 | EuroNCAP lane width (CH_RD_01) |
| `junction_radius_m` | 8.0 | Junction corner/kerb radius (CH_RD_03). Note: RoadRunner does not export the kerb radius to OpenDRIVE, so the check reports the connecting-road radii and asks for GUI confirmation unless a radius is below spec |
| `simulation_time_min_s` / `max_s` | 100 / 150 | Fallback simulation-time window when VUT speed is unknown (CH_SC_04) |
| `expected_decel_ms2` | -4.0 | Required braking deceleration (CH_MR_02) |
| **Curve Radii** table | Table 1.2.4 | Steady-state turn radii (the constant-radius arc, EuroNCAP path Part 2) per speed and side (CH_SC_07) |
| **Sim Time Bands** table | 35/40/45 → 60 s | Speed-dependent simulation-time limits (CH_SC_04) |

### 2. SITE SETTINGS - edit freely
These describe *your* workflow and naming conventions.

| Key | Example | When to change |
|---|---|---|
| `traffic_handedness` | `LHT` | `LHT` = drive on left (Japan/India/UK, the EuroNCAP default). Set `RHT` for right-hand-traffic projects - Farside/Nearside swap automatically |
| `vut_entity_names` | `VUT, Ego, …` | Names your team uses for the vehicle under test |
| `encap_actor_names` | `GVT, EPTa, …` | Allowed target names (prefix match: `Vehicle2` passes because of `Vehicle`) |
| `sov_entity_names` | `SOV, SK_SUV` | Entities allowed to use non-NCAP asset paths (the protocol lets the SOV be a real vehicle) |
| `static_target_name_patterns` | `Obstruction, …` | Names that must have speed 0 (CH_SC_14) |
| `stationary_target_name_patterns` | `EMT, EPTa, …` | VRU targets that start stationary (CH_SC_15) |
| `required_file_extensions` | `.xosc, .xodr, …` | Extensions every scenario folder must contain (CH_NM_03) |
| `required_standalone_files` | `TA.xml` | Exact filenames every folder must contain |
| `optional_standalone_files` | `VehicleCatalog.xosc` | Reported if present, never required |
| `junction_scenario_prefixes` | `CP, CB, …` | Scenario families that get the junction geometry checks |
| `extra_scenario_prefixes` | `CPLA, CMRs, …` | Valid name prefixes that have no row in the Scenarios sheet yet |
| `checklist_column_widths` | `{"4": 196.71, …}` | Column widths (characters) for the `--checklist` reviewer-export ChecklistFinal sheet, keyed by 1-based column number. Defaults mirror the reviewer file exactly (the export is a replica); override a column here only to deviate. Any omitted column uses the built-in default. JSON-only (not surfaced in `config.xlsx`). |

In Excel, list values are one cell, comma-separated: `VUT, Ego, EgoVehicle, Vehicle`.

The batch summary's **Confidence** buckets (`tools/batch_validate.py` -> `Summary_Stats_*.xlsx`)
are deliberately *not* config: they are reporting thresholds, not protocol tolerances, so they
live as the `CONF_HIGH` / `CONF_MED` constants in `src/rollup.py` to keep config to the values
that change a verdict.

### 3. TUNING KNOBS - change only if validation is consistently too strict or too loose
Tolerances and thresholds (`*_tolerance_*`, `*_threshold_*`, `speed_sanity_max_kmh`,
`junction_waypoint_radius_m`, `curvature_min_*`). Defaults are sensible; note that
`impact_tolerance_pct` = 5 means ±0.09 m of lateral precision for a pedestrian impact -
widen it if the design process cannot hold that.

### 4. SCENARIOS - one row per scenario family
This is the table you'll edit most. Adding a row automatically registers the scenario
name prefix - nothing else to update.

| Column | Meaning |
|---|---|
| `tag` | Scenario family name as it appears in filenames (`CCFhol`, `CPTA`, `CPNA-50` …) |
| `impact_tolerance_class` | Impact-tolerance routing (NOT the EuroNCAP Scenario-Type taxonomy): `longitudinal` (CH_SC_17 applies), `crossing` (CH_SC_16 applies), or `head-on`. The legacy column name `type` is still accepted |
| `vut_min_kmh` / `vut_max_kmh` | Allowed VUT speed range per protocol (CH_SC_18). Leave blank if unknown |
| `side_impact` | TRUE for side-impact scenarios (CMCscp, CBTAfs, CBTAns) - impact % is measured across VUT length, not width |
| `has_sov` | TRUE only for scenarios that include an overtaken vehicle (CCFhol) |
| `impact_overlaps` | Comma-separated list of the protocol impact-location %s this family allows (e.g. `-25, 0, 25, 50, 75, 100, 125` for CCRb). CH_NM_04 checks the filename `NNImp` token against it; blank = fall back to the `allowed_impact_overlaps` site setting. Negative and >100 values are allowed (rear partial pre/post overlap) |

`Vehicle Dimensions` sheet: bounding-box fallbacks used **only** when the `.xosc` does
not embed a BoundingBox (RoadRunner exports always do).

---

## When something goes wrong

- **JSON typo** → the validator prints the line/column and the most likely cause
  (usually a trailing comma) - no stack trace.
- **Wrong value type** → the message names the exact key and what it expected.
- **Excel sheet renamed/deleted** → the message names the missing sheet and how to
  regenerate the file.

Always re-run `--check-config` after editing.
