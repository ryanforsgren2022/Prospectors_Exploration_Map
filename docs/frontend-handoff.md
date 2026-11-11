# Frontend integration handoff

Prepared 2026-10-24 for the next worker. The frontend integration is implemented locally and its automated integration tests pass. Production has not been deployed or verified against live tile services.

## Main files

```text
source-dist/app.js                         Frontend layer loader and map rendering
source-dist/index.html                     Layer controls, including claims and PLSS controls
source-dist/styles.css                     Existing map styles
public/beta-404b87eaa6a7b90cc88f57111d565a25/index.html
                                            Protected static entry page
public/beta-404b87eaa6a7b90cc88f57111d565a25/map.9e30b6d15b14.js
                                            Currently referenced built app bundle
tests/r2-datasets.test.mjs                 Frontend integration tests
```

## Data routing contract

The frontend calls VM discovery at:

```text
https://tiles.americanexplorationmaps.com/api/states/discover-v2
```

It reads the actual discovered `sourceLayer`, tile template, zoom limits, bounds, and claims semantics. Do not hardcode alternate MBTiles paths in the frontend. The expected vector tile route pattern is:

```text
https://tiles.americanexplorationmaps.com/api/vm-data/{state}/{group}/{z}/{x}/{y}.pbf
```

The backend handoff and prepared code are described in [vm-backend-handoff.md](vm-backend-handoff.md). The frontend accepts claims only when discovery declares `semantics: notClosed`, `classificationFilter.rule: notClosed`, and `unknownPolicy: report-separately`.

R2 base URL:

```text
https://data.americanexplorationmaps.com
```

R2 objects:

```text
Continuous roads:
https://data.americanexplorationmaps.com/western-prospectors-roads-v3.pmtiles

Historic mines for each state code:
https://data.americanexplorationmaps.com/prospectors/{state}/historic-mines.pmtiles
```

For historic mines the browser reads PMTiles header and metadata to find the real vector source-layer, bounds, and zoom limits. If metadata is missing or ambiguous it skips that state’s mine layer rather than substituting another source. R2 availability is reported by the project owner; live object metadata and range responses have not been checked from this workspace.

Other map families use VM discovery. Parcels stay on the VM and are initialized last. No parcel data belongs in R2.

## Rendering behavior already implemented

- The one continuous roads PMTiles source spans the western states; map style rules and state selection use the bundled state boundaries.
- State initialization does not wait for R2 mine metadata. A failed mine request does not delay VM datasets.
- Mine rendering uses the archive’s actual source-layer, bounds and zoom limits, with `dep_id` promoted only when the field exists.
- The standard claims control is labeled “Mining claims — all non-closed statuses.” Closed features are filtered by the backend. Missing, null, blank and invalid classifications are reported separately and omitted from classified claims; the frontend never calls them Active.
- Idaho has a separate “Idaho claims — BLM lands only” control and source ID. This verifies only the restricted layer mapping; do not mark statewide Idaho claims complete until a statewide source and its production coverage are verified.
- Arizona townships use the dedicated archive through the standard discovered group. Repeated synchronization does not add a second township renderer from the combined archive.
- The PLSS survey-details control includes government lots, special surveys, quarter sections, quarter-quarter sections, survey points, intersected surveys and second divisions. Point survey data renders as points; the other additional PLSS groups render as lines. Township and section fill/outline/labels use their existing templates.
- Withdrawals support authorized and pending sources whether discovery returns them separately or nested under one dataset.
- The parcels group stays last in the group order.

## Local verification

From the repository root:

```bash
node --test tests/r2-datasets.test.mjs
```

Eight frontend tests pass. They check the public R2 object paths, actual PMTiles metadata selection, no fallback to ambiguous mine data, VM URL behavior, continuous roads, claim semantics, all 117 registered vector source mappings, exact VM tile URL templates, min/max zooms, geographic bounds, idempotent rendering, and the parcel-last order. The direct backend fixture suite also passed all nine tests, including discovery v2 and representative VM tile handlers across all 117 registrations; FastAPI is unavailable here, so it did not exercise real ASGI or HTTP transport.

The VM worker should first run the read-only checks in [vm-backend-handoff.md](vm-backend-handoff.md), then deploy backend only after separately approved. Once the backend is live, verify the discovery and representative PBF requests there before assessing the frontend against production.

## Static build and release caution

`build.mjs` no longer removes `public/`. It creates missing directories/files, copies vendor/data files only when absent, writes new hash-named app/CSS assets without overwriting conflicting hashed names, updates the protected beta entry page, and creates root `index.html`/`robots.txt` only if absent. Other existing public files are left in place.

`npm run build` was run locally after the change. Before/after inventory: 140 public files; zero missing, zero changed existing files, zero new files; protected beta entry page remained byte-identical. A fresh Terser build of `source-dist/app.js` exactly matches `public/beta-404b87eaa6a7b90cc88f57111d565a25/map.9e30b6d15b14.js`, and the protected index references it.

Production access check is BLOCKED in this workspace. `curl` could not resolve `data.americanexplorationmaps.com` for the roads PMTiles, Arizona mines PMTiles, or Idaho mines PMTiles (HTTP status 000). The web fetch tool could not access those objects or the tile discovery endpoint. This does not establish that the objects are unavailable to public clients; it means production reachability and range responses could not be verified from this network. The owner-reported R2 paths remain configured in the frontend.

## Production checklist for the next worker

1. Confirm the live backend version returns schema version 2 and the expected state registry.
2. Check that every discovered VM dataset exposes its real source-layer ID, bounds, zoom range, and valid PBF tile template.
3. Confirm `claims` and `claimsBlmLands` advertise the non-Closed rule and separate unknown policy.
4. Recheck R2 PMTiles HEAD/range access and metadata for continuous roads and representative historic-mine states from a network that can resolve the data host. Confirm the layer IDs against metadata, rather than assuming an ID from the filename.
5. Open the map in a browser at representative state extents; verify roads, mines, claims, PLSS, withdrawals, and parcels as independently enabled controls.
6. Check browser network/console errors, duplicate township rendering, and Idaho’s BLM-only labeling/scope.
7. Do not interpret a missing source from the audit as a frontend loading defect. Recorded gaps include claims in CO/NV/WY, statewide ID claims, AZ boundary metadata, NV boundary/surface management, OR surface management, and the listed OR/WY PLSS families.
8. Deploy only after the code review and user’s deployment authorization. No deploy or production changes are part of this handoff.
