# Preliminary summary: road loading issues

**Status:** Initial code review, not yet confirmed against a live browser session or network trace. The current application source is `source-dist/app.js`; `build.mjs` creates the protected files under `public/beta-404b87eaa6a7b90cc88f57111d565a25/`.

## Most likely issue found

### State boundary selector is omitted from the build

The road loader fetches `./data/western-state-boundaries.geojson` to choose a state-specific road archive. That file exists at `source-dist/data/western-state-boundaries.geojson`, but `build.mjs` copies only `source-dist/vendor` and `source-dist/data/geology` into the public build. The boundary file therefore will not be present after a clean build. The fetch fails, `loadStateRoadBoundaries()` logs an error, and the selector keeps its default `AZ` package as the user pans into other states.

**Likely symptom:** roads appear in Arizona but disappear, become incomplete, or load the wrong coverage when viewing another supported state. This does not by itself explain missing Arizona roads.

**Fix:** include `data/western-state-boundaries.geojson` in the build copy list (or copy the entire required `source-dist/data` tree), then confirm it is served at the expected relative URL in the generated beta directory.

**Confidence:** High for the packaging defect; medium for whether it matches the reported symptom.

## Other plausible causes to check

| Possible issue | Why it could affect roads | Suggested fix or check | Confidence |
|---|---|---|---|
| Road archive URL or range-request behavior | The current source moved all 11 archives from `data.americanexplorationmaps.com/prospectors/<state>/roads.pmtiles` (backup) to `tiles.americanexplorationmaps.com/api/vm-data/<state>/roads.pmtiles`. PMTiles relies on byte-range reads. A missing archive, denied request, bad `206 Partial Content`/`Content-Range`, or CORS failure can leave the road source blank. | In browser Network tools, inspect the archive metadata and tile requests. Confirm status, `Access-Control-Allow-Origin`, and range response headers. Verify the archive URLs and `vector_layers` metadata on the tile host. | Medium; URL change is visible, host behavior is unverified. |
| Road archive schema mismatch | Road styles initially use source-layer `roads`; a compatibility block fetches metadata and rewrites layers to `roads` or `transportation`. If the archive has neither layer, or metadata retrieval fails, the styled roads cannot render. | Check the archive's `vector_layers` metadata and the console for `[AEM roads]` warnings. Prefer publishing archives with a consistent `roads` layer; retain compatibility handling only for known legacy archives. | Medium. |
| Compatibility check can stall after a failed metadata request | `synchronize()` logs a metadata error and clears its in-flight URL, but retries depend on later map events. A transient failure can delay recovery until another triggering event occurs. | Add bounded retry/backoff for metadata errors and a visible diagnostic for a persistent failure. Avoid an unbounded retry loop. | Low to medium. |
| CSP or proxy/CDN response | The configured CSP permits `tiles.americanexplorationmaps.com` and `data.americanexplorationmaps.com`, so the current policy appears to allow the listed archive hosts. A CDN/API route may still return an error, redirect, or incorrect content type. | Check the actual browser request and response, including redirects and content type; compare with a direct request to the archive endpoint. | Low for CSP; endpoint behavior unverified. |

## Suggested order of investigation

1. Fix and deploy the missing boundary asset, then verify it loads with HTTP 200 from the built beta path.
2. Reproduce the issue in Arizona and one neighboring state with the browser Network and Console panels open.
3. Confirm archive metadata and tile requests return successfully, support byte ranges, and advertise a compatible vector layer.
4. If requests succeed but lines remain absent, inspect the loaded style's road layers and filters at the current zoom. The style has zoom-dependent road classes, so some roads are intentionally hidden at smaller scales.

The repo has no Git worktree metadata available in this environment, and no live network/browser trace was used for this preliminary review. Treat endpoint and runtime explanations as hypotheses until those checks are captured.
