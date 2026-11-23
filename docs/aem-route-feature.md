# Route Finder and Route Tracker

Development branch: `feature/aem-route-tracker`, based on `4351599`.

## Data flow

1. Finder requests a path from the connected road/trail graph.
2. MapLibre loads and renders the complete path.
3. Only after rendering, Finder starts independent corridor requests for private parcel records, claims, and historic mines.
4. Tracker records GPS points into one trip, with driving and hiking segments. Discovery failures do not affect recording.

The graph is a new derived dataset built from the verified OSM extracts that supplied the existing AEM road display. The existing search-v2 SQLite indexes are read-only and supply claim and mine candidate records. Parcel checks read exact polygon geometry from the existing published parcel tiles. No route action changes PLSS layers.

## Build the routing graph

The VM graph build uses a separate directory on the data volume and the existing verified extract manifest. It downloads one immutable extract at a time, checks its MD5, imports connected nodes and directed edges, then removes that temporary extract. It does not modify production indexes or parcel archives.

```bash
nice -n 15 ionice -c3 /root/LIVE_SITE_CASHE/live-mvt/.venv/bin/python \
  vm-review/build_aem_routes.py \
  --manifest /mnt/volume_sfo3_1794422503599/updater/reports/mines-roads-20261120/roads-source-downloads.json \
  --graph /mnt/volume_sfo3_1794422503599/aem-routing/routes.sqlite \
  --staging /mnt/volume_sfo3_1794422503599/aem-routing/staging
```

The plan endpoint refuses an incomplete graph. A route is advisory: access restrictions, closures, and passability need independent confirmation.

Arizona benchmark on 2026-11-23: the verified extract produced 1,111,624 routable ways, 10,039,091 nodes, and 21,250,038 directed edges in a 2.47 GB SQLite graph. SQLite `quick_check` returned `ok`. A roughly 18 km Phoenix-area drive routed in 1.8 seconds; Phoenix to Tucson routed 181.9 km in 16.2 seconds with the one-million-visit benchmark cap. The production default cap is 1.5 million visits. These timings are VM measurements, not guarantees for other states.

## Parcel coverage

The parcel endpoint tests route intersections and a fixed 0.5-mile corridor against tile polygons and labels each result `crossed` or `within_0_5_mile`. Its `complete` field is false when an archive manifest reports missing tile records. The current manifests report 509 missing zoom-16 parcel records across nine states, so the UI reports partial coverage there. Nevada has no comparable manifest and is reported as unknown coverage. Repairing those source gaps is required before claiming an exhaustive private parcel result.

## Verification

```bash
npm ci
npm run build
node --test tests/route-finder.test.mjs tests/route-tracker.test.mjs tests/search-v2.test.mjs
python3 -m unittest tests/test_aem_route_graph.py tests/test_aem_route_config.py
```

The browser tracker stores trips on the current device. Browser GPS recording can pause when a phone locks or the browser is suspended; reliable locked-phone recording requires a native-capable client.
