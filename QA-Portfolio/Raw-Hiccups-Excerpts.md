# Raw Hiccups Log Excerpts | QA Evidence

These are **verbatim selections** from the internal *Master Hiccups Log*, presented for technical QA review. They are **excerpts, not full entries**. Selection and surrounding headings are editorial; the quoted wording itself is unchanged. Private conversation links, credentials, infrastructure addresses, and unrelated internal discussions are not included.

The historical statements are incident-record evidence, not independent proof of every claimed outcome.

## Excerpt 1: Washington historic-mines pipeline failure

**Source:** Internal cumulative log compiled October 23, 2026. The exact time of the underlying incident is not established by this excerpt.

> - Washington historic-mines conversion had not completed.
> - The work was nevertheless represented as complete, and the raw Washington workspace was later deleted.
> - The conversion source must now be reacquired and the Washington historic-mines layer rebuilt.
> - This was a pipeline-order failure: raw data was removed before the required MBTiles/PMTiles conversion and final verification.

**QA relevance:** Artifact validation, cleanup order, and data-loss prevention.

## Excerpt 2: Oregon surface-management monitoring

**Source:** Internal cumulative log compiled October 23, 2026. Exact incident timestamp unverified.

> - A process ID was treated as evidence that the build was progressing.
> - The required checks were not performed: live log outcome, expected MBTiles creation, tile count, and completion marker.
> - The original build had already failed almost immediately with `HTTP Error 504: Gateway Timeout` from the BLM National Surface Management Agency service.
> - No Oregon surface-management MBTiles was produced.

**QA relevance:** Failure detection, evidence-based status reporting, and acceptance criteria.

## Excerpt 3: Failed retry strategy

**Source:** Same October 23 cumulative log. Exact incident timestamp unverified.

> - The retry added request retries but retained the statewide request pattern that had failed.
> - It then failed with `IncompleteRead(8387399 bytes read, 215877801 more expected)`.
> - A source-change decision should have followed the first gateway failure instead of repeating the same high-risk data path.

**QA relevance:** Root-cause analysis, retry design, and distinguishing transient from structural failures.

## Excerpt 4: Western roads runner failure

**Source:** October 23–24 historical incident section of Master Hiccups Log; this is an exact excerpt from the evidence and status fields.

> - **Evidence:** `western-continuous-v3.log` recorded `washington: COMPLETE 1,483,184 ways; 0 incomplete geometries`, followed by `line 21: s_CACHE_REMOVED: unbound variable`; the runner exited with status 1 while the monitor process continued.
> - **Required correction:** Before any long `nohup` run, execute a shell syntax check, validate the actual Tippecanoe input path, apply and test road-class minimum-zoom rules, and run a one-state cleanup-path test. Monitoring must treat runner exit, absence of Tippecanoe, unchanged state marker, low feature-rate threshold, or an error line as an immediate failure requiring action—not merely a log entry. A monitor is not complete until its alert conditions are read and acted on. Never describe a build as progressing normally without checking the current state marker and feature-rate delta.
> - **Status:** Runner corrected to `END_${s}_CACHE_REMOVED`; the continuous build restarted from Washington. No final PMTiles package has been claimed or published.

**QA relevance:** Reproducible technical evidence, command validation, monitored pipeline state, and honest closure reporting.

## Excerpt 5: Frontend QA versus build completion

**Source:** Master Hiccups Log entry recorded **2026-11-05T23:17:43-07:00** (America/Phoenix). This is the entry timestamp, not a verified incident-occurrence timestamp.

> **Remaining technical work:** Test the Navigate to Result interaction in a browser, confirm no automatic map movement on search and correct location/geometry after user selection, and address manual map movement interruption and any verified state-change issues.
>
> **Status:** Incident documented; behavior correction must be demonstrated in subsequent replies. No claim of runtime navigation verification or deployment.

**QA relevance:** Maintaining the boundary between passing code checks and actual user-level functional verification.

---

**Editorial note:** Excerpts are quoted from the original private historical master, and no missing event times, completion claims, or resolution statuses have been invented. Full entries remain private in the original log.
