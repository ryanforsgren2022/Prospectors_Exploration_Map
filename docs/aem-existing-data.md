# AEM Existing Data Sources

## Road Search Indexes
Directory: /mnt/volume_sfo3_1794422503599/updater/data/search-v2

States: az ca co id mt nv nm or ut wa wy

Each state has:
  <state>/roads.sqlite

These are existing search indexes, not confirmed routing graphs.

## Private Parcel Archives
Directory: /root/LIVE_SITE_CASHE/live-mvt/data

Pattern:
  <state>/parcels/tiles/<state>-parcels.mbtiles

Nevada uses nv-parcels.pmtiles.

## Important
- Reuse existing data.
- Do not duplicate archives.
- Do not modify production indexes.
- Do not rebuild data without identifying a specific requirement.
- Verify SQLite schema and road connectivity before routing.
- Route must be generated and displayed before feature discovery.
- Private parcels within 0.5 mile must be identified.
- Never activate PLSS grid lines through routing or search.
