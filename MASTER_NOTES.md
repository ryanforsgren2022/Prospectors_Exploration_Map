
## Future Task — Saved Pin Storage
When cloud storage is added for American Exploration Maps, revisit the Saved Locations / pin system.

Current behavior:
- Saved locations are stored locally in the browser with localStorage.
- Storage key: az-prospecting-map.saved-locations.v1

Future change:
- Move saved pins/locations from browser localStorage to the user's cloud account.
- Saved pins should follow the user across phones, tablets, and computers.
- Preserve pin name, description, coordinates, and associated research data where practical.
- Migrate existing locally saved pins when possible instead of silently discarding them.
- Keep local storage only as an offline/cache fallback if useful.

Status: DEFERRED until site cloud storage/account data system is implemented.

## Arizona Parcels — Discovery Distinction (2026-10-29)
Arizona has parcel data even though the VM's shared state discovery does not list an Arizona parcels dataset. The VM provides a separate `/az/parcels/{z}/{x}/{y}.pbf` route backed by Arizona's statewide ArcGIS parcel service. A Phoenix test tile returned 2,477 parcel records on October 29, 2026.

Do not report Arizona parcel data as missing solely because it is absent from shared state discovery. Whether the rewritten frontend currently attaches this separate route and renders it on the map remains unverified.
