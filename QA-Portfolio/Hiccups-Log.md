# Selected QA Case Studies

**Project:** Prospectors Exploration Map / American Exploration Maps (AEM)  
**Source:** Curated from the internal Master Hiccups Log; original retained privately.  
**Scope:** Project-based functional QA, data quality, integration testing, and defect documentation.  
**Reporting rule:** Historical status is preserved. A reported or user-confirmed outcome is not represented as independently re-tested.

## 1. Cross-state parcel and search behavior

**Context:** The map expanded beyond a single state, requiring different state datasets and field names to work through one search experience.

**Risk / defect:** Legacy single-state assumptions could route parcel lookups to an incorrect state, return mismatched fields, or display the wrong pin details.

**Testing approach:** Reviewed state-specific search paths, checked expected state identifiers and search results, examined JavaScript syntax after edits, and separated code-level verification from browser-level acceptance.

**QA contribution:** Identified assumptions that needed explicit state-aware handling and maintained a clear distinction between a syntax pass and verified map behavior.

**Status:** Code-level checks were reported as passed during implementation; full cross-state browser verification is not asserted here.

## 2. Missing or incorrect search-result feedback

**Expected:** Out-of-boundary or otherwise invalid search outcomes should provide clear feedback to the user, including an appropriate warning or absence of a misplaced pin.

**Observed:** A reported test returned information without the expected marker and warning.

**QA contribution:** Documented expected versus actual behavior and classified the issue as a functional defect requiring UI feedback and map-result consistency checks.

**Status:** Defect documented; no verified resolution asserted in this public summary.

## 3. Geospatial data source reuse and duplicate downloads

**Context:** California PLSS subdivision processing relied on large government geospatial source datasets.

**Risk / defect:** Re-downloading source records already present in the working inventory increases time, network usage, and the chance of duplicate or conflicting data.

**Evidence:** An internal incident recorded a repeated fetch after an earlier inventory had identified available source material. Source completion was later user-confirmed.

**QA contribution:** Compared processing plans against existing inventories and defined a preflight control: check source availability, versions, and derived outputs before starting new retrieval or transformation.

**Status:** Workflow defect recorded and prevention control specified; this does not imply the control is deployed everywhere.

## 4. Long-running build monitoring and failure detection

**Context:** A multi-state vector-road build had to run in sequence and produce a validated output.

**Observed:** A runner exited after one state because of an undefined shell variable, while a separate monitor remained active.

**QA contribution:** Distinguished a running monitor from a running build, reviewed logged failure evidence, and specified stronger checks: exit status, progressing state marker, recent output, and validated final artifact.

**Status:** The internal record reported correction of the runner and a restart. It did not establish a verified final nationwide package.

## 5. API success versus visual map correctness

**Context:** Vector tiles were tested through backend routes.

**Observed:** Sampled endpoint requests returned successful HTTP responses, but an authenticated browser-layer verification was not completed in the historical audit.

**QA contribution:** Kept backend smoke tests separate from user-visible acceptance criteria. Defined the need to verify map-layer registration, correct rendering, click behavior, state alignment, and search integration in the browser.

**Status:** Backend sample passed in the historical record; end-to-end map QA remained outstanding at that point.

## 6. Safe release and rollback verification

**Context:** An earlier state-inheritance change was associated with a production outage and recovery difficulties.

**QA contribution:** Documented the importance of a known-good baseline, explicit production target, deployment provenance, rollback path, and post-release validation before declaring an incident closed.

**Status:** Historical incident documented. No claim is made here that every later release followed these controls.

---

## Testing methods demonstrated

| Method | Application |
| --- | --- |
| Functional testing | Search results, map pins, state transitions, and user warnings |
| Data validation | Dataset inventory, record counts, source reuse, and coverage |
| API smoke testing | Endpoint responses and JSON inspection |
| Regression analysis | Multi-state behavior after frontend changes |
| Defect documentation | Expected / actual, evidence, impact, status |
| Release QA | Build checks, deployment identification, rollback safeguards |

**Documentation integrity:** These are selected examples rather than a verbatim export. No fabricated defect IDs, timestamps, closure dates, or test passes have been added. Evidence not independently verified is labeled accordingly.

*Public portfolio edition: November 11, 2026.*
