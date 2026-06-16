# Eval_Data benchmark - before and after improvement

Corpus: `Eval_Data/` - 54 fully-exported scenario folders (16 CCFtap car-to-car,
22 CBTAfo + 2 CBTAno car-to-bicycle, 16 CMFtap car-to-motorcycle) plus 1 incompatible
directory (`RR Scenarios/`, 5 RoadRunner-native exports with no `.xosc`/`.xodr`).

Both runs use `tools/run_eval.py`, which validates every scenario folder it finds,
never aborts the batch on a single failure, and aggregates the result. "Before" is the
code at the start of this work; "After" is the same corpus after the improvements below.

## Headline

| Metric | Before | After |
|---|---:|---:|
| Scenarios processed (of 54) | 54 | 54 |
| Crashes / errors | 0 | 0 |
| Total FAIL verdicts | 59 | 5 |
| Mean automatable pass rate | 96.5% | 99.7% |
| CH_MD_03 pass rate | 0.0% | 100.0% |
| Checks evaluated per scenario | 41 | 42 |

The single systematic defect the corpus exposed was **CH_MD_03 failing on 100% of
scenarios**. It was a parser bug, not 54 broken scenarios: the `.rd` reader only
understood a generic `<Route><Road/></Route>` shape and read 0 roads from real dSPACE
ModelDesk `RoadNetwork` files, whose route segments live in a `<Sections>` block of
`<RouteSection>` elements. Reading the real schema takes MD_03 from 0% to 100% and the
mean automatable pass rate from 96.5% to 99.7%.

The 5 remaining FAILs are genuine geometric findings, not bugs, and are left as-is:
- **CH_SC_07** (1): one CCFtap turn radius is outside the protocol tolerance.
- **CH_SC_16** (4): four CBTAfo bicycle impact-% estimates are outside +/-5%; impact %
  for a narrow VRU is a partially-automated estimate that is finalised in HIL.

## What changed (improvement = robustness + scalability only)

1. **Robustness** - `.rd` parser now reads the dSPACE ModelDesk schema
   (`RouteSection` segments + child `<Name>`), namespace-agnostically. Generic-schema
   `.rd` files are unaffected. No check's pass/fail logic or tolerance was changed; the
   check was simply fed correct data.
2. **Scalability** - new `tools/run_eval.py` batch runner: discovers scenario folders
   under any root (handles paths with spaces), validates each, survives per-scenario
   exceptions, and writes this aggregate report. The incompatible `RR Scenarios/`
   directory is detected and reported rather than crashing or producing a wall of FAILs.
3. All Eval_Data scenario families (CCFtap, CBTAfo, CBTAno, CMFtap) were already
   registered in `config.json`; no new families needed adding.

No new check logic was added. The NM renumber, automation-level column, and reviewer
checklist export shipped alongside this work are labelling/reporting features and do not
move any pass/fail verdict (NM now reports 6 checks per scenario instead of 5, which is
why "checks per scenario" rises 41 -> 42).

## Verdict distribution (all checks x all scenarios)

| Verdict | Before | After |
|---|---:|---:|
| Yes (PASS) | 1601 | 1709 |
| No (FAIL) | 59 | 5 |
| Manual (MANUAL_REVIEW) | 230 | 230 |
| NA | 324 | 324 |
| Total | 2214 | 2268 |

## Automation coverage (after)

Each check now carries an intrinsic trust tier (see `src/automation.py`). Across the
corpus:

| Automation level | Count | Share |
|---|---:|---:|
| Fully Automated | 1350 | 59.5% |
| Partially Automated | 702 | 31.0% |
| Manual | 216 | 9.5% |

## Per-scenario-family pass rate

| Family | Scenarios | Before | After |
|---|---:|---:|---:|
| CCFtap | 16 | 96.8% | 100.0% |
| CBTAfo | 20 | 96.1% | 99.2% |
| CBTAno | 2 | 96.8% | 100.0% |
| CMFtap | 16 | 96.7% | 100.0% |

## Checks that never pass automatically (by design)

These are Manual or always-NA on this corpus and rightly need a human or HIL: CH_FB_01
(workbook present, columns manual), CH_SC_08/09 (protocol judgement / asset positions),
CH_SC_14/15/17/19 (not applicable to these turning scenarios), CH_MR_02 (no braking
scenarios here), CH_RD_03 (kerb radius not exported by RoadRunner, GUI confirm),
CH_SC_16/20 (geometric estimates confirmed in HIL).

## Reproduce

```bash
python tools/run_eval.py Eval_Data --output /tmp/eval --report /tmp/eval/report.md --label After
```
