# Final uniform MBTiles storage plan

**Storage migration remains planning-only. Local backend compatibility is prepared. No production operations were executed.**

The audit has 168 historical path records. The production inventory has 98 selected archive paths. Two smaller Washington archives are listed separately as **EXCLUDED — UNIQUENESS UNVERIFIED**; neither is a production layer, migration source or deletion candidate.

Canonical root: `/root/arizona-naip-build/live-mvt/data/`, historically resolved to `/root/LIVE_SITE_CASHE/live-mvt/data/`. Resolve the live symlink again before execution.

Canonical structure: `{state}/{dataset}/tiles/{state}-{dataset}.mbtiles`. PLSS uses `{state}/plss/tiles/{state}-plss-{sublayer}.mbtiles`; combined PLSS stays `{state}/plss/tiles/{state}-plss.mbtiles`. Keep original source-layer IDs and all attributes. Roads and historic mines remain R2 PMTiles; parcels remain VM MBTiles.

## Reconciled counts

- 98 selected archives; 26 filename corrections; **6 directory-only changes**, not seven.
- 15 parent-directory changes when including files whose names also change.
- 32 selected path changes: 30 have no known occupied target; two Washington names remain physically occupied.
- All 32 operations are additive hard links. No original file is renamed, moved, overwritten or deleted.

## All-state summary

| State | Selected | Filename corrections | Directory-only changes | Occupied targets |
| --- | ---: | ---: | ---: | ---: |
| AZ | 8 | 1 | 1 | 0 |
| CA | 11 | 1 | 0 | 0 |
| CO | 8 | 0 | 0 | 0 |
| ID | 10 | 2 | 0 | 0 |
| MT | 10 | 2 | 2 | 0 |
| NM | 11 | 7 | 1 | 0 |
| NV | 5 | 0 | 0 | 0 |
| OR | 7 | 3 | 0 | 0 |
| UT | 9 | 5 | 0 | 0 |
| WA | 11 | 3 | 0 | 2 |
| WY | 8 | 2 | 2 | 0 |

## Exact selected path corrections

| Current path relative to data root | Canonical proposed path | Status |
| --- | --- | --- |
| `az/claims/az-claims-not-closed.mbtiles` | `az/claims/tiles/az-claims.mbtiles` | Plan only; live checks pending |
| `az/surface-management/az-surface-management.mbtiles` | `az/surface-management/tiles/az-surface-management.mbtiles` | Plan only; live checks pending |
| `ca/claims/ca-claims-not-closed.mbtiles` | `ca/claims/tiles/ca-claims.mbtiles` | Plan only; live checks pending |
| `id/claims/id-claims-active-blm-lands.mbtiles` | `id/claims-blm-lands/tiles/id-claims-blm-lands.mbtiles` | Plan only; live checks pending |
| `id/plss/tiles/id-plss-intersected.mbtiles` | `id/plss/tiles/id-plss-intersected-surveys.mbtiles` | Plan only; live checks pending |
| `mt/claims/mt-claims.mbtiles` | `mt/claims/tiles/mt-claims.mbtiles` | Plan only; live checks pending |
| `mt/plss/tiles/mt-plss-intersected.mbtiles` | `mt/plss/tiles/mt-plss-intersected-surveys.mbtiles` | Plan only; live checks pending |
| `mt/plss/tiles/mt-plss-second-division.mbtiles` | `mt/plss/tiles/mt-plss-second-divisions.mbtiles` | Plan only; live checks pending |
| `mt/surface-management/mt-surface-management.mbtiles` | `mt/surface-management/tiles/mt-surface-management.mbtiles` | Plan only; live checks pending |
| `nm/claims/nm-claims-not-closed.mbtiles` | `nm/claims/tiles/nm-claims.mbtiles` | Plan only; live checks pending |
| `nm/plss/tiles/intersected-surveys.mbtiles` | `nm/plss/tiles/nm-plss-intersected-surveys.mbtiles` | Plan only; live checks pending |
| `nm/plss/tiles/second-divisions.mbtiles` | `nm/plss/tiles/nm-plss-second-divisions.mbtiles` | Plan only; live checks pending |
| `nm/plss/tiles/sections.mbtiles` | `nm/plss/tiles/nm-plss-sections.mbtiles` | Plan only; live checks pending |
| `nm/plss/tiles/special-surveys.mbtiles` | `nm/plss/tiles/nm-plss-special-surveys.mbtiles` | Plan only; live checks pending |
| `nm/plss/tiles/survey-points.mbtiles` | `nm/plss/tiles/nm-plss-survey-points.mbtiles` | Plan only; live checks pending |
| `nm/plss/tiles/townships.mbtiles` | `nm/plss/tiles/nm-plss-townships.mbtiles` | Plan only; live checks pending |
| `nm/surface-management/nm-surface-management.mbtiles` | `nm/surface-management/tiles/nm-surface-management.mbtiles` | Plan only; live checks pending |
| `or/claims/or-claims-not-closed.mbtiles` | `or/claims/tiles/or-claims.mbtiles` | Plan only; live checks pending |
| `or/plss/tiles/or-plss-government-lots-blm-authoritative.mbtiles` | `or/plss/tiles/or-plss-government-lots.mbtiles` | Plan only; live checks pending |
| `or/plss/tiles/or-plss-quarter-quarter-sections-blm-authoritative.mbtiles` | `or/plss/tiles/or-plss-quarter-quarter-sections.mbtiles` | Plan only; live checks pending |
| `ut/boundary/utah-state-boundary.mbtiles` | `ut/boundary/tiles/ut-boundary.mbtiles` | Plan only; live checks pending |
| `ut/claims/utah-claims-active.mbtiles` | `ut/claims/tiles/ut-claims.mbtiles` | Plan only; live checks pending |
| `ut/plss/tiles/utah-plss-sections.mbtiles` | `ut/plss/tiles/ut-plss-sections.mbtiles` | Plan only; live checks pending |
| `ut/plss/tiles/utah-plss-townships.mbtiles` | `ut/plss/tiles/ut-plss-townships.mbtiles` | Plan only; live checks pending |
| `ut/surface-management/utah-surface-management.mbtiles` | `ut/surface-management/tiles/ut-surface-management.mbtiles` | Plan only; live checks pending |
| `wa/claims/wa-claims-not-closed.mbtiles` | `wa/claims/tiles/wa-claims.mbtiles` | Plan only; live checks pending |
| `wa/plss/tiles/wa-plss-government-lots-blm-authoritative.mbtiles` | `wa/plss/tiles/wa-plss-government-lots.mbtiles` | BLOCKED: occupied filename |
| `wa/plss/tiles/wa-plss-quarter-quarter-sections-blm-authoritative.mbtiles` | `wa/plss/tiles/wa-plss-quarter-quarter-sections.mbtiles` | BLOCKED: occupied filename |
| `wy/boundary/wy-boundary.mbtiles` | `wy/boundary/tiles/wy-boundary.mbtiles` | Plan only; live checks pending |
| `wy/plss/tiles/wy-plss-intersected.mbtiles` | `wy/plss/tiles/wy-plss-intersected-surveys.mbtiles` | Plan only; live checks pending |
| `wy/plss/tiles/wy-plss-second-division.mbtiles` | `wy/plss/tiles/wy-plss-second-divisions.mbtiles` | Plan only; live checks pending |
| `wy/surface-management/wy-surface-management.mbtiles` | `wy/surface-management/tiles/wy-surface-management.mbtiles` | Plan only; live checks pending |

Idaho corrections explicitly retain BLM-only scope and standardize the intersected-survey name. They do not convert restricted claims into statewide claims or change either vector source layer.

## Washington — final selection and exclusions

Keep `wa-plss-government-lots-blm-authoritative.mbtiles` (source layer `plss_government_lots`) and `wa-plss-quarter-quarter-sections-blm-authoritative.mbtiles` (source layer `plss_quarter_quarter_sections`) as canonical **data sources**. Their proposed standardized filenames remain occupied; no script overwrites or relocates the excluded occupants. All selected statewide special-survey and other PLSS archives remain included.

The following exact paths are excluded from production and migration registration:

| Excluded path under `/root/LIVE_SITE_CASHE/live-mvt/data/` | Audit-reported count | Status |
| --- | ---: | --- |
| `wa/plss/tiles/wa-plss-government-lots.mbtiles` | 26 | EXCLUDED — UNIQUENESS UNVERIFIED |
| `wa/plss/tiles/wa-plss-quarter-quarter-sections.mbtiles` | 16 | EXCLUDED — UNIQUENESS UNVERIFIED |

Both report `AQUATIC_LAND_FLG=N`; no aquatic-land authority is asserted. Counts are the audit’s `tilestats` counts, not an independent unique-feature recount. Extra attribute names do not establish unique features or a required additional production layer. Geometry overlap/redundancy cannot be proved from the supplied metadata. Neither physical file is marked for deletion.

## Duplicates versus destination conflicts

The Montana pair is a user-reported SHA-256-identical duplicate; only `mt-claims.mbtiles` is selected. No deletion is in this plan. The 13 same-file identity groups are aliases, not independent redundant copies. Washington’s occupied destinations are name conflicts, not verified duplicate data.

## Files and executable scripts

- [Production inventory CSV](mbtiles-inventory.csv): 98 selected archives, including all unchanged ones.
- [Final old-to-new manifest](mbtiles-path-manifest.json): 98 canonical mappings, 32 link operations, and retained nonselected records; the two excluded records have been removed.
- [Separate exclusions](washington-excluded-archives.json) and [Washington evidence](washington-partial-comparison.json).
- [Full historical audit inventory](mbtiles-audit-inventory.csv): all 168 records, with exclusions labeled.
- `scripts/mbtiles_migrate.py` and `scripts/mbtiles_rollback.py`: executable, read-only checks by default. They require explicit approval/review flags for filesystem changes; neither changes backend code or services.

Read-only check from the repository on the VM:

```bash
python3 scripts/mbtiles_migrate.py --manifest docs/mbtiles-path-manifest.json
```

Future approved execution only (not authorized or run in this task):

```bash
python3 scripts/mbtiles_migrate.py --manifest docs/mbtiles-path-manifest.json \
  --receipt /tmp/aem-mbtiles-migration-receipt.json --apply \
  --approved-deployment --dependencies-reviewed
python3 scripts/mbtiles_rollback.py --receipt /tmp/aem-mbtiles-migration-receipt.json
# After approval and review, add --apply --approved-deployment --dependencies-reviewed to roll back.
```

Preflight checks every source/destination, strictly resolves the root, rejects nested symlinks and path escapes, detects active SQLite journals, checks integrity and exact source-layer sets, hashes each source before/after inspection, checks filesystem/device and free-space reserve, and refuses any occupied destination. Execution adds only verified same-filesystem hard links; originals remain. Rollback verifies hashes and originals, then moves only created aliases into transaction-specific `migration-rollback/tiles/` retention paths. It never deletes a file. The receipt is rollback state, not a hiccup log.

A mid-operation pending receipt or changed file blocks automatic rollback for manual reconciliation. Cross-filesystem copying is intentionally unsupported until a separate verified copy plan is approved.

## Validation and approval issues

Six local storage tests pass, including actual synthetic apply/rollback, byte preservation, occupied-target refusal, symlink/path escape rejection, metadata/integrity failure, and final-manifest exclusions. The generator verifies all 11 states, 98 selected sources, both Idaho corrections, unique canonical destinations and retention of required statewide PLSS source layers.

Remaining: live SHA-256/integrity and symlink/service/dependency review; approval for production execution; a separate approved resolution of the two occupied Washington names without deleting unique data; and deployment of the prepared backend as a separately approved task. No storage loss is introduced by this plan: originals and excluded files are retained, links are verified, and rollback retains aliases. Live preconditions must pass before an actual production safety claim can be made.
