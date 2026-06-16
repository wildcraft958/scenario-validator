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
| Total FAIL verdicts | 59 | 1 |
| Mean automatable pass rate | 96.5% | 99.9% |
| CH_MD_03 pass rate | 0.0% | 100.0% |
| Parity vs hand-validated reviews | - | 97.2% |
| Checks evaluated per scenario | 41 | 43 |

The single systematic defect the corpus exposed was **CH_MD_03 failing on 100% of
scenarios**. It was a parser bug, not 54 broken scenarios: the `.rd` reader only
understood a generic `<Route><Road/></Route>` shape and read 0 roads from real dSPACE
ModelDesk `RoadNetwork` files, whose route segments live in a `<Sections>` block of
`<RouteSection>` elements. Reading the real schema takes MD_03 from 0% to 100%.

After the parity work below, the **only remaining FAIL across the whole corpus** is one
genuine authoring deviation: **CH_SC_07** on `CBTAfo_15VUT_15EBTa_10Imp` (turn radius
3.8 m vs the protocol's 11.75 m, while its sibling scenarios measure 12.0 m) - a real
mistake the hand review passed, which the validator caught.

## What changed

1. **Robustness** - `.rd` parser now reads the dSPACE ModelDesk schema
   (`RouteSection` segments + child `<Name>`), namespace-agnostically. Generic-schema
   `.rd` files are unaffected.
2. **Scalability** - new `tools/run_eval.py` batch runner: discovers scenario folders
   under any root (handles paths with spaces), validates each, survives per-scenario
   exceptions, and writes this aggregate report. The incompatible `RR Scenarios/`
   directory is detected and reported rather than crashing.
3. **Parity with the hand review** (cross-checked by `tools/crosscheck_reviews.py`):
   - **CH_SC_22 / CH_RD_04** now return NA when their precondition is absent (no static
     obstruction) instead of a vacuous PASS - matching the checklist wording and the
     reviewers. A wrong obstruction asset path still FAILs.
   - **CH_FB_02** is automated from the TA workbook (object display-switches J-N and
     positions O-S vs the fellow count); **CH_FB_01** PASSes on a present+valid workbook.
   - **CH_SC_16/17** flag a narrow-VRU turning impact as MANUAL (HIL confirms) rather than
     a hard FAIL - the protocol finalises that location in HIL. Wide targets and
     longitudinal impacts still FAIL when off. No false PASS is introduced.

All Eval_Data scenario families (CCFtap, CBTAfo, CBTAno, CMFtap) were already registered
in `config.json`; no new families needed adding. NM now reports 6 checks and FB 2 checks
per scenario, so "checks per scenario" rises 41 -> 43.

## Verdict distribution (all checks x all scenarios)

| Verdict | Before | After |
|---|---:|---:|
| Yes (PASS) | 1601 | 1709 |
| No (FAIL) | 59 | 1 |
| Manual (MANUAL_REVIEW) | 230 | 180 |
| NA | 324 | 432 |
| Total | 2214 | 2322 |

## Automation coverage (after)

Each check carries an intrinsic trust tier (see `src/automation.py`). Across the corpus:

| Automation level | Count | Share |
|---|---:|---:|
| Fully Automated | 1404 | 60.5% |
| Partially Automated | 702 | 30.2% |
| Manual | 216 | 9.3% |

## Per-scenario-family pass rate

| Family | Scenarios | Before | After |
|---|---:|---:|---:|
| CCFtap | 16 | 96.8% | 100.0% |
| CBTAfo | 20 | 96.1% | 99.8% |
| CBTAno | 2 | 96.8% | 100.0% |
| CMFtap | 16 | 96.7% | 100.0% |

## Parity vs hand-validated reviews

38 of the 54 scenarios ship a human-completed reviewer checklist (`<base>_Review.xlsx`).
Taking those as ground truth, `tools/crosscheck_reviews.py` compares our verdict against
the reviewer's per check, over the 40 directly comparable checks (our NM_04-06 and the
reviewer-only MD_06-11 have no counterpart).

| Measure | Before parity work | After |
|---|---:|---:|
| Agreement (all comparable checks) | 94.4% | **97.2%** |
| **Core metric** (NM + RD + SC, <= SC_22) | - | **96.3%** |
| Extension (MD + MR + FB) | - | **100.0%** |
| **False PASS (reviewer No, ours Yes)** | **0** | **0** |
| Our Manual defers (measured, asked for confirm) | 128 | 110 |

The **core checklist metric (NM + RD + SC, up to SC_22)** is the headline figure; MD / MR /
FB are reported as an extension. All of the residual disagreements sit in the core (RD/SC);
the extension checks agree 100%.

The reviewer marked **no failures anywhere** - every checkpoint they assessed is Yes or
N/A. So our validator never contradicts a human failure, and it adds independent
failure-detection on top of the manual pass. After the parity work the residual
disagreements are all defensible:

- **1 `Yes -> No`** - the reviewer miss the validator caught: `CBTAfo_15VUT_15EBTa_10Imp`
  has a 3.8 m VUT turn radius vs the protocol's 11.75 m, while its sibling scenarios at the
  same speed/side measure 12.0 m. The file was authored with a wrong (tight) turn that the
  reviewer passed (CH_SC_07).
- **22 `Yes -> NA`** - CH_RD_04 on the bicycle/motorcycle scenarios. RD_04 is conditional on
  static objects at the intersection; none of these have any, so NA is the protocol-correct
  verdict. The reviewers marked them N/A for the 16 car-to-car scenarios but Yes for these -
  an inconsistency in the hand review, not a validator error.
- **16 `NA -> Yes`** - CH_RD_02 on the car-to-car scenarios. RD_02 (>=2 road segments) is a
  universal check we verify deterministically; the reviewers marked it N/A as a
  "covered-by-prerequisite" convention. Our PASS is the more rigorous reading.

## Generalization (beyond the corpus families)

The corpus is all turn-across-path (1 moving target, no obstructions). A brittleness audit
checked that the logic holds for families NOT in the corpus, verified against the committed
`examples/` (CCFhol SOV, CCFhos head-on, CPNCO obstructions, CPTA pedestrian-turn):

- **Hardened so they generalize:** obstruction detection (`_obstruction_entity_names`)
  excludes every recognized target token + SOV names, so a stationary GVT (CCRs) or an SOV
  is never mistaken for an obstruction; SC_16/17 now pick the impact target by its filename
  token (not document order), so a multi-fellow scene (SOV, obstructions) measures the right
  pair; SC_14 obstruction layout uses each obstruction's own bounding box, not a fixed GVT
  length. FB_02 reads the TA workbook by header/step name with a try/except (degrades to
  MANUAL, never crashes) and uses the dynamic fellow count.
- **Verified already general:** junction gating (RD_03-06, SC_10) is `.xodr`-geometry-driven
  and NAs correctly off non-junction families; MR_02 deceleration applicability is derived
  from the action; the `.rd` parser is namespace-agnostic with a text fallback.
- **Documented coverage gaps (not silent errors):** side-impact families (CBTAfs/CBTAns/
  CMCscp) read impact on the length axis but ship no example to validate locally; a CCRs
  stationary lead encoded as a degenerate trajectory (rather than init-speed 0) would not be
  zero-speed-checked by SC_14/15. Add an example of each before running those families in
  anger. The `scenarios.*.type` key is the impact-tolerance routing key (SC_16 +/-5% vs
  SC_17 +/-1%), deliberately separate from the motion taxonomy used for the reference point.

The four CBTAfo bicycle impact-% disagreements present before the parity work are gone:
CH_SC_16 now flags a narrow-VRU turning impact as MANUAL (HIL confirms) rather than FAIL,
matching the reviewers and the protocol's "final tuning in HILs".

## Reproduce

```bash
python tools/run_eval.py Eval_Data --output /tmp/eval --report /tmp/eval/report.md --label After
python tools/crosscheck_reviews.py Eval_Data --report /tmp/eval/parity.md
```
