# Data archive remediation

2026-10-24. Changes are prepared locally only. No production service, source archive, R2 object, or hiccup log has been changed.

## PASS / FAIL / BLOCKED

PASS means local integration and fixture validation passed; it does not claim a production archive was read.

| Dataset | Local remediation | Production validation |
| --- | --- | --- |
| Washington PLSS | PASS: statewide BLM source mappings and renderer | BLOCKED: production files/network unavailable |
| Arizona townships | PASS: dedicated source, preserved attributes, no duplicate township rendering | BLOCKED: production tile payloads unavailable |
| Idaho claims on BLM lands | PASS: independent control, archive, route and source layer | BLOCKED: production tile payloads unavailable |
| Montana claims canonicalization | PASS locally: canonical registry, tile route and count scanner use `mt-claims.mbtiles` | BLOCKED: duplicate deletion and live reference/hash checks; SSH denied |

Local validation: 23 Python tests plus the frontend integration suite passed. No outstanding local test failure. The handler and VM-verifier tests exercised every one of 117 explicit registrations against synthetic SQLite/MVT fixtures using the audit metadata. FastAPI is unavailable, so tests invoked the actual handlers through a response/decorator shim; they did not verify ASGI routing or HTTP transport.

## Washington PLSS

**Issue:** Smaller alternate-source archives competed with statewide BLM cadastral data.

**Root cause:** Discovery ranked matches by zoom/date and only recognized some PLSS layer names. The frontend omitted additional PLSS families.

**Corrective action:** Explicit registrations preserve statewide BLM coverage. Generator input, `STATEABBR=WA`, `STEWARD=BLM Cadastral - OR`, `aem_source=BLM_Natl_PLSS_CadNSDI_MapServer_3`, cadastral fields and bounds support the choice. The generator asserts this evidence before accepting the selection.

**Final archives selected, relative to canonical data root:**

- `wa/plss/tiles/wa-plss-government-lots-blm-authoritative.mbtiles` → `plss_government_lots`.
- `wa/plss/tiles/wa-plss-quarter-quarter-sections-blm-authoritative.mbtiles` → `plss_quarter_quarter_sections`.

The selected extents span approximately longitude −124.73 to −116.92 and latitude 45.55 to 49.00. Competing smaller-archive extents cover only small northwestern subsets. Metadata reports 81,151/505,410 features versus 26/16 for those subsets; these statistics support, but alone do not prove, coverage. Full comparison records are in `western-audit-analysis.json`.

**Validation:** PASS locally. Both exact source layers, native zoom limits and bounds attach to the renderer. All additional PLSS groups render through the survey-details control.

**Remaining blocker:** Actual production tile contents, archive integrity and full source completeness cannot be independently established from metadata alone.

## Arizona townships

**Issue:** Dedicated and combined archives both contain `plss_townships`.

**Root cause:** Generic archive selection did not identify which source should supply township rendering.

**Corrective action:** Select the dedicated township source and retain the combined file for government lots, sections and special surveys. The dedicated source spans Arizona, retains `GlobalID`, `STATEABBR`, `PRINMER`, `PLSSID` and township attributes, and has a nonempty audit sample. The combined conversion omits several of these fields. No choice was made from date, size or zoom alone.

**Final archive selected:** `az/plss/tiles/az-plss-townships.mbtiles`.

**Source layer:** `plss_townships`.

**Retained archive:** `az/plss/tiles/az-plss.mbtiles` supplies `plss_government_lots`, `plss_sections` and `plss_special_surveys`.

**Validation:** PASS locally. One township source supplies one fill/outline/label set; repeated syncs do not add sources or duplicate layers. Original feature attributes remain in the tile payloads.

**Remaining blocker:** Live feature-level coverage and integrity checks require the VM files.

## Idaho claims

**Issue:** A BLM-lands-only archive could be mistaken for authoritative statewide coverage.

**Root cause:** A generic claims group obscured spatial scope. The word “active” in the filename also misdescribes its multiple dispositions.

**Corrective action:** Register `claimsBlmLands` separately from statewide `claims`. Add an independent, initially disabled “Idaho claims — BLM lands only” control. Non-closed semantics include Filed, Submitted, Under Review and appeal classifications; there is no Active-only restriction.

**Final archive selected:** `id/claims/id-claims-active-blm-lands.mbtiles`.

**Source layer:** `claims`.

**Discovery tile route:** `/api/vm-data/id/claimsBlmLands/{z}/{x}/{y}.pbf`.

**Frontend source:** `prospector-id-claims-blm-lands`; its layer IDs use a separate `blm` prefix. The statewide claims control does not toggle this source.

**Validation:** PASS locally: registration, native extent, source layer, independent toggle and route handler tests pass. Metadata lists Active, Appeal - Stay Granted, Filed, Submitted and Under Review.

**Remaining blocker:** Authoritative statewide Idaho claims are not represented by this archive; live file verification remains unavailable.

## Montana verified duplicate removal — local preparation complete; deletion BLOCKED

**Issue:** Two Montana claims files were previously unresolved competitors. The user now confirms identical SHA-256 hashes and passing SQLite integrity checks, and explicitly designates the canonical filename.

**Canonical archive retained:** `/root/LIVE_SITE_CASHE/live-mvt/data/mt/claims/mt-claims.mbtiles` (configured-root equivalent: `/root/arizona-naip-build/live-mvt/data/mt/claims/mt-claims.mbtiles`). The original VM file is untouched; this path is now selected by the local registry.

**Duplicate archive deleted:** **NOT DELETED.** The requested target is `/root/LIVE_SITE_CASHE/live-mvt/data/mt/claims/montana-claims-active.mbtiles`. Deletion is authorized only after live reference, route, filesystem and SHA-256 checks. These cannot run from this environment, so no deletion was attempted.

**SHA-256 verification:** User-reported identical hashes and passing SQLite integrity establish the canonicalization decision. The actual digest text was not supplied in the workspace. An independent immediately-before-deletion rehash remains BLOCKED by SSH access (`socket: Operation not permitted`). No fabricated digest or deletion result is recorded.

**Root cause:** Generic discovery previously ranked competing archives by zoom/date and had no explicit canonical Montana registration.

**Corrective action:** `scripts/prepare-western-integration.py` now explicitly selects `mt/claims/mt-claims.mbtiles` based on the user's verification and instruction. Regenerated `vm-review/western-datasets.json` contains the canonical path and no duplicate registration. The generic copied service reads that entry; no frontend URL change is required. The classification scanner follows the canonical registration and skips the duplicate in the historical audit. Original audit evidence is preserved.

**Source layer:** `claims`.

**Discovery and tile route:** `/api/vm-data/mt/claims/{z}/{x}/{y}.pbf`. Discovery declares non-Closed classification filtering; all non-Closed classifications remain eligible, with unknowns reported separately.

**Reference checks completed locally:** Copied Python runtime modules contain no hard-coded dependency on `montana-claims-active.mbtiles`. The generator references only the canonical path for registration. The duplicate name remains intentionally in the read-only two-file verification tool and historical audit/analysis records, which are not serving dependencies. No copied source code needs the duplicate to serve Montana claims.

**Filesystem/reference checks still BLOCKED:** Live service code/configuration, state manifests, symlinks, hard links and open-file references could not be inventoried. The old audit has different file identities (`64769:2885703` duplicate and `64769:1311266` canonical), but that does not establish current link counts or that no live service requires the duplicate. Production discovery may differ from the copied code. No local result is presented as a live production-path check.

**Final validation result:** PASS for local canonical registration, source-layer mapping and direct-handler tile serving. A regression fixture contains only `mt-claims.mbtiles`; discovery and the actual tile handler return a claims tile successfully without any duplicate file. The count scanner also passes using only the canonical archive and skips the historical duplicate. Overall deletion status remains **BLOCKED**, not complete.

The existing read-only verifier is saved at `vm-review/verify_montana_archives.py`. From the repository terminal:

```bash
ssh aem-vm 'python3 -' < vm-review/verify_montana_archives.py
```

It strictly resolves the root, checks existence, hashes both files, runs SQLite integrity checks, compares metadata/source layers/tile counts, and prints IDENTICAL/DIFFERENT/BLOCKED. It never deletes or selects a file. Exit codes are 0/1/2 respectively. This verification is necessary but does not replace the still-required live reference/symlink/route checks before deletion.

**Remaining blocker:** Network access to the DigitalOcean VM. No files were deleted, no service was restarted, and no production references were changed or deployed.

## Master configuration and integration

`vm-review/western-datasets.json` is the explicit VM dataset registry; `scripts/prepare-western-integration.py` generates it from the audit. The copied `aem_vm_discovery_v2.py` now uses this registry instead of ranking competing archives. It checks actual metadata, layer presence, byte size, bounds and zoom coverage before publishing. Paths resolve beneath the canonical state root. Active SQLite WAL files are not published as finished immutable archives.

All audited PLSS source-layer spellings are mapped, including New Mexico prefixes, Montana first divisions, second divisions, intersected surveys, government lots, special surveys, quarter sections, quarter-quarter sections and survey points. The frontend's group list, standard style templates and supplemental PLSS configuration are the master rendering configuration in this project; no separate master layer file was supplied. Repeated attachment is idempotent.

Withdrawals support authorized/pending sublayers from shared or separate archives. Claims preserve their original classification attributes. Roads retain the continuous R2 archive. Historic mines retain the metadata-driven R2 integration; this remediation does not rebuild or change historic-mine source data. R2 failure does not delay VM layer initialization. An old hard-coded R2 Nevada boundary source was removed because non-road/non-mine families must use VM data; its missing VM boundary is reported as a gap rather than hidden by a substitute.

Parcel processing remains last. The existing canonical Colorado parcel archive is explicitly registered; dedicated VM parcel routes are preserved when present in state manifests. No parcel data is uploaded to R2.

## Storage and data gaps

No source files were copied, linked, overwritten, moved or deleted. Existing `data/{state}/{family}/` conventions and `tiles/` subdirectories remain intact; completed archives are not moved into staging.

The audit has 168 path records, 34 outside the resolved canonical root, 13 same-file identity groups and six error records. Seven outside paths already have an identity represented under the canonical root. Eight records are excluded for errors or missing vector metadata/bounds; this includes Arizona's boundary and an incomplete Idaho township build. Aliases and competing records are listed in `western-audit-analysis.json`; no hash equivalence is inferred for separate files.

Distinguish **data absent from this MBTiles audit** from **data present but blocked/unintegrated**:

- Claims absent from the audit: Colorado, Nevada and Wyoming. Idaho has BLM-only claims, not statewide coverage. Montana is registered to the user-verified canonical archive; duplicate deletion remains blocked by live access.
- Nevada boundary and surface management, and Oregon surface management, are absent from the supplied MBTiles audit. Arizona boundary exists but lacks required vector metadata/bounds.
- Oregon lacks township/section/survey-point archives in this audit. Wyoming lacks sections, government lots and quarter/quarter-quarter archives. Other state-specific PLSS gaps are listed in the state checklist; the absence of one PLSS type does not remove the types that exist.
- Outside build files, rejected variants and precision-recovery patches are not silently promoted or merged. The audit alone cannot establish their finality, SHA-256 equivalence or merge completeness.
- R2 object presence was reported by the user; live R2 metadata/payload checks are blocked here by DNS/network access. No live verification is claimed.

The local bundle is prepared without deploying. Production discovery responses, ASGI routing, WebGL rendering and production file hashes/tile payloads remain BLOCKED by unavailable runtime/dependencies/network access. All executable local tests above passed.


## Classification correction completed after archive remediation

**Issue:** “Active” in archive names was incorrectly treated as a possible exclusive selection rule. The actual requirement is every named classification except Closed, for every state.

**Root cause:** Filename-based inference and legacy discovery had no explicit normalized per-feature filter or unknown-classification accounting.

**Corrective action:** `vm-review/aem_claims_classification.py` filters actual claims MVT responses using `CSE_DISP`. Attribute-key matching ignores case and surrounding whitespace. Classification comparison collapses Unicode whitespace and uses casefold; only the normalized value `closed` is excluded as Closed. Active, Filed, Submitted, Under Review, Draft, Interim and appeal classifications are retained. Missing, null, blank and invalid values are not labeled Active: they are counted separately and omitted from the classified non-closed layer pending resolution.

Retained feature, geometry, ID and attribute bytes are preserved. Original dictionaries and classification spelling are not rewritten. Unused dictionary values may still contain the text Closed; only features referencing that classification are removed. No source MBTiles are rebuilt or modified. No historic-mine changes were made as part of this classification correction.

The discovery service applies this reader to both `claims` and `claimsBlmLands`, publishes the explicit classification policy, and returns before/after, Closed, unknown and per-classification counts in exposed response headers. The frontend accepts claims sources only when discovery declares `notClosed` semantics and separate unknown reporting. A tile containing only Closed/unknown features returns 204 with counts; malformed claims data returns 503 rather than bypassing validation. Empty/out-of-range requests retain their existing handling.

**Validation result: PASS locally.** The mixed fixture contains 16 features: eight different named non-closed statuses retained, three case/whitespace variants of Closed excluded, and five unknowns reported separately (one missing, one null, two blank, one invalid). This test is run for all 11 states: AZ, CA, CO, ID, MT, NM, NV, OR, UT, WA and WY. Each retained original feature is byte-identical. A separate direct-handler and scanner test verifies six before → three after, one Closed and two unknown, including the response count headers. Tests cover compressed/uncompressed payloads and malformed protobuf data. Backend filtering is not Active-only.

**Production count result: BLOCKED.** The actual source MBTiles cannot be read here. `docs/claims-classification-counts.json` records null rather than zero for unmeasured counts by state/archive/classification. `docs/claims-audit-metadata-summary.json` preserves the audit's reported totals and observed classification names; these are not a fresh before/after count, do not establish unknown-value counts, and must not be presented as unique legal-claim totals.

| State | Classifications observed in audit metadata | Actual before / after / Closed / unknown counts |
| --- | --- | --- |
| AZ | Active; Filed; On Appeal; Under Review | BLOCKED — not measured |
| CA | Active; Filed; Submitted; Under Review | BLOCKED — not measured |
| CO | No claims MBTiles identified in supplied audit | BLOCKED — source gap |
| ID | Active; Appeal - Stay Granted; Filed; Submitted; Under Review (BLM lands only) | BLOCKED — not measured; statewide source gap |
| MT | Active; Filed; Under Review (canonical `mt-claims.mbtiles`) | BLOCKED — not measured; duplicate deletion pending live checks |
| NM | Active; Filed; Under Review | BLOCKED — not measured |
| NV | No claims MBTiles identified in supplied audit | BLOCKED — source gap |
| OR | Active; Filed; Interim; On Appeal; Under Review | BLOCKED — not measured |
| UT | Active; Draft; Filed; On Appeal; Under Review | BLOCKED — not measured |
| WA | Active; Filed; Under Review | BLOCKED — not measured |
| WY | No claims MBTiles identified in supplied audit | BLOCKED — source gap |

The saved read-only scanner `vm-review/audit_claim_classifications.py` computes actual counts from the audited VM paths, with `aem_claims_classification.py` beside it:

```bash
python3 audit_claim_classifications.py --audit /root/aem-data-audit/20261024-203228/mbtiles-audit.json
```

It prints JSON only, distinguishes unknown reasons, includes representative unknown native feature IDs/tile coordinates, and follows the canonical Montana registration without counting the historical duplicate. Counts represent tile-feature occurrences across stored tiles/zooms; clipping and repeated zooms mean these are not deduplicated statewide legal-claim totals. Each archive must satisfy before = after + Closed + unknown. No historic-mine archives are scanned.

**Remaining blockers:** Production classification counts, missing statewide source archives, and Montana pre-deletion reference/hash verification require VM access. The copied Python changes and adjacent registry/classification module remain local; production is unchanged. FastAPI/ASGI, a real browser/WebGL session, production HTTP tile payloads, R2 metadata and original source-file integrity/hash checks could not execute in this environment.


## Uniform naming and organization plan — local backend compatibility complete

The naming phase originally deferred backend work. That deferral is now superseded: local discovery understands both each reviewed current path and its proposed standardized destination. Existing public discovery/tile routes are unchanged. No live rename, copy, link, deletion, service restart or deployment was performed.

**Canonical proposed structure:**

```text
/root/arizona-naip-build/live-mvt/data/
  {state}/{dataset}/tiles/{state}-{dataset}.mbtiles
  {state}/plss/tiles/{state}-plss-{sublayer}.mbtiles
```

The audit resolved this configured root to `/root/LIVE_SITE_CASHE/live-mvt/data`. Root resolution must be repeated on the VM before migration. Combined PLSS archives remain `{state}/plss/tiles/{state}-plss.mbtiles`; combined withdrawals remain `{state}/withdrawals/tiles/{state}-withdrawals.mbtiles`. Logical dataset/sublayer names are uniform across states while the original internal vector source-layer IDs remain unchanged. Idaho's restricted claims use the separate `claims-blm-lands` dataset, preserving the distinction from statewide claims. Static roads and historic mines stay in R2 as PMTiles; parcels remain on the VM.

**Inventory:** All 168 audited paths are recorded, including 98 distinct selected registry archive paths. Thirty-two selected paths need standardization: 26 filename changes and six directory-only changes. Two proposed destinations are blocked by existing different files. These counts describe the supplied snapshot and local selected registry, not a verified live production census. Outside builds, rejected variants, aliases, invalid files, regional aggregates and unselected sources are retained and labeled separately; none are automatically promoted or removed.

**Washington destination conflicts:** Proposed standardized government-lots and quarter-quarter filenames are currently occupied by the smaller alternate-source datasets. No overwrite or deletion commands are generated. Preserve statewide BLM sources and physically retain the excluded, uniqueness-unverified files. Resolving those name collisions requires dependency review and an approved coordinated path switch, which are deferred.

**Artifacts:**

- [Concise all-state/file naming table](mbtiles-naming-plan.md).
- [Complete inventory CSV](mbtiles-inventory.csv): filenames, datasets/source layers, proposals, aliases/competitors, known local discovery routes and deferred backend-reference status for every record.
- [Complete old-to-new manifest](mbtiles-path-manifest.json): all 168 path records and 98 selected migration entries with inert preparation/link-or-copy/hash-check command proposals and rollback mappings.

Commands are not executed. They require live symlink/service/dependency and writer checks, SHA-256 and SQLite integrity verification, a free-space/device check, absent destinations, and an approved deployment. Hard links or verified no-clobber copies preserve existing paths; no archive rebuild is proposed. After any byte-copy, source and destination SHA-256 must match. Rollback restores old references and leaves all data paths in place; no delete or restart command is generated. Redundant-file removal remains conditional on verified content identity and no active dependencies, and is outside this phase.

**Validation result: PASS for local inventory/manifest and backend compatibility.** The repeatable generator `scripts/inventory-mbtiles-naming.py` checks 168/168 records, all 11 states plus the retained regional aggregate, selected-source presence in the audit, naming syntax, unique destinations among selected sources, and known occupied-target collisions. It records the audit-input SHA-256 for reproducibility. Production SHA-256 values, running-service dependencies, live symlinks and actual migration remain BLOCKED by unavailable VM access. No live safety prerequisite is marked passed without evidence.


## Final storage-only standardization plan and Washington exclusion

This section supersedes earlier provisional descriptions of the two smaller Washington sources. Neither is classified as an aquatic-land dataset: both report `AQUATIC_LAND_FLG=N`, and source authority/feature uniqueness is unverified.

**EXCLUDED — UNIQUENESS UNVERIFIED**, with physical files untouched:

| Exact excluded physical path | Audit-reported feature count | Source layer |
| --- | ---: | --- |
| `/root/LIVE_SITE_CASHE/live-mvt/data/wa/plss/tiles/wa-plss-government-lots.mbtiles` | 26 | `plss_government_lots` |
| `/root/LIVE_SITE_CASHE/live-mvt/data/wa/plss/tiles/wa-plss-quarter-quarter-sections.mbtiles` | 16 | `plss_quarter_quarter_sections` |

These are excluded from the 98-row production inventory, active manifest registrations and migration operations. They are separately listed in `washington-excluded-archives.json` and retained in the full historical audit inventory. They are not marked for deletion or preserved as extra production layers merely because their attribute schemas differ.

The statewide BLM sources remain canonical data selections:

- `wa/plss/tiles/wa-plss-government-lots-blm-authoritative.mbtiles`: `plss_government_lots`, audit-reported 81,151 records.
- `wa/plss/tiles/wa-plss-quarter-quarter-sections-blm-authoritative.mbtiles`: `plss_quarter_quarter_sections`, audit-reported 505,410 records.

Required statewide government lots, special surveys and other PLSS layers remain selected. Source-layer IDs, geometry and attributes are unchanged. `washington-partial-comparison.json` records the schema/source evidence; there is no feature geometry or source-ID crosswalk in the supplied audit, so containment, unique-feature counts and redundancy are not independently established. Reported `tilestats` counts are not a fresh unique-feature recount.

**Destination status:** The excluded files still physically occupy the desired standardized names. Both Washington operations remain BLOCKED until a separately approved resolution clears those names without overwriting unique data. There are no relocation operations for the excluded files in this plan. The local registry labels both as `canonicalPathBlocked`; discovery does not consider either occupied path a runtime candidate.

**Reconciled manifest:** 98 selected archives; 26 filename corrections; six directory-only changes; 15 parent-directory changes when including files whose names also change. The earlier figure of seven directory-only changes is not supported by the selected manifest. Thirty-two selected paths change; 30 have no known occupied destination and two are blocked. The full audit accounting remains 168 = 166 retained manifest records + two separately excluded records.

Both Idaho filename corrections are included:

| Current relative path | Proposed canonical relative path |
| --- | --- |
| `id/claims/id-claims-active-blm-lands.mbtiles` | `id/claims-blm-lands/tiles/id-claims-blm-lands.mbtiles` |
| `id/plss/tiles/id-plss-intersected.mbtiles` | `id/plss/tiles/id-plss-intersected-surveys.mbtiles` |

**Executable scripts:** `scripts/mbtiles_migrate.py` and `scripts/mbtiles_rollback.py`, supported by `scripts/mbtiles_migration.py`. Both default to read-only checks. Mutation requires explicit approval and dependency-review flags; no production execution was authorized or performed. The migration script creates only hard links into absent destinations, with live SHA-256, SQLite integrity, exact source-layer, symlink, device and free-space checks. Originals remain untouched. Rollback moves only generated aliases into transaction-specific retention paths after rechecking hashes and originals. It deletes nothing. A durable transaction receipt supports rollback; no hiccup logs are created. An interrupted pending operation requires manual reconciliation rather than guessing.

**Validation:** Six storage tests PASS, covering synthetic migration and rollback with unchanged bytes, approval gates, no-clobber behavior, symlink/path-escape refusal, metadata/integrity rejection, complete manifest accounting, both Idaho corrections, and exclusion of the smaller Washington sources while retaining required BLM layers. Python compilation and CSV/manifest checks pass. Running the read-only production preflight locally returned BLOCKED with permission denied for `/root/arizona-naip-build`; no production filesystem was changed.

**Remaining issues requiring approval/access:** live integrity/hash and service/symlink/dependency inspection; separate resolution of the two occupied Washington names; production storage execution; and deployment of the prepared backend change set. Cross-filesystem copying is unsupported by this hard-link plan until separately reviewed. Original selected and excluded data remain preserved; actual production safety still depends on those live preconditions.

Final artifacts: [naming plan](mbtiles-naming-plan.md), [98-row production inventory](mbtiles-inventory.csv), [old-to-new manifest](mbtiles-path-manifest.json), [excluded Washington files](washington-excluded-archives.json), [historical audit inventory](mbtiles-audit-inventory.csv).


## Final local backend remediation

**Issue:** The copied backend still needed non-disruptive path-standardization support, and older Arizona/Utah compatibility routes could bypass the normalized all-non-Closed claims policy.

**Root cause:** The registry recorded only reviewed current archive paths. Compatibility claim routes had separate readers and did not share the discovery route's filter.

**Corrective action:** Registry entries now record a reviewed `path` plus `canonicalPath` when the standardized destination is eligible. The two Washington conflicts instead use `canonicalPathBlocked`, which discovery ignores. Discovery validates source layer, native zoom coverage, bounds, byte size, nonempty tiles, stable age and WAL state. If current and standardized paths both exist, the standardized path is selected only when it is the same filesystem object as the reviewed current archive; otherwise the reviewed current archive wins. If only one eligible path exists, it still must pass every registration invariant. Public discovery and tile URLs do not change.

The shared `registered_mbtiles_tile` reader now supplies the v2 route and the older Utah route. Both claim groups apply the same filter and response accounting. The older live Arizona claims generator now filters source records before MVT encoding, changes its cache namespace so previously cached unfiltered tiles cannot be reused, preserves original named classifications, and exposes before/after/Closed/unknown/per-classification headers on cache hits and misses.

**Final archive/source decisions:** Washington statewide BLM government lots and quarter-quarter archives; dedicated Arizona townships plus the combined archive for its other layers; Idaho BLM-lands-only `claims` layer exposed only as `claimsBlmLands`; Montana `mt/claims/mt-claims.mbtiles` with source layer `claims`. All other source layers remain exactly those recorded in `western-datasets.json`.

**Validation result: PASS locally.** Twenty-three Python tests pass. They cover all 117 registrations, representative direct-handler requests, canonical hard-link selection, refusal of an unrelated occupied Washington destination, all-non-Closed filtering and unknown accounting, Utah compatibility handling, Montana canonical-only operation, and storage safety. The frontend integration suite also passes. Python compilation passes for all prepared runtime, validation and test modules.

**Production result: BLOCKED, not failed.** No VM files or services were changed. Live root resolution, source hashes/integrity, actual classification counts, active service dependencies, ASGI routing, public discovery responses and representative production requests require VM execution. The exact read-only preflight and approval-gated deployment sequence is in [vm-backend-handoff.md](vm-backend-handoff.md). No deployment, restart, archive move, archive deletion, R2 mutation or hiccup log occurred.

## Frontend safe local validation

`build.mjs` no longer recursively removes `public/`. It adds missing source assets without replacing existing static files, creates root fallback files only when absent, writes only absent hash-named JS/CSS outputs, and refreshes the protected beta index. Local `npm run build` completed with all 140 preexisting public files still present and byte-identical, including the protected entry page. The freshly minified `source-dist/app.js` exactly matches the protected `map.9e30b6d15b14.js` bundle referenced by that page.

All eight existing frontend tests pass. The suite now verifies the VM discovery tile templates, vector source layers, geographic bounds, minimum and maximum zooms for all 117 registered layer groups, Idaho's separate BLM-only claims control, and parcel-last ordering. Nine direct backend fixture tests pass for discovery v2 and representative handlers; FastAPI was unavailable, so these used a response/decorator shim and do not establish production ASGI behavior.

**R2 and production endpoint verification: BLOCKED by this workspace's DNS/network.** Requests to the continuous roads archive, representative Arizona/Idaho historic-mines archives, and tile discovery endpoint could not resolve their hosts. No conclusion is drawn about public client availability. Live range requests, PMTiles metadata, discovery JSON, browser rendering, VM archive access, and service operation remain unverified. See [frontend handoff](frontend-handoff.md) for the next worker's checklist.
