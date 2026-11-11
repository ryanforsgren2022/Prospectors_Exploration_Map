# Master PLSS blueprint and VM inventory

The controlling specification is seven required layers for each of AZ, CA, CO, ID, MT, NV, NM, OR, UT, WA, and WY: townships, sections, quarter sections, quarter-quarter sections, government lots, special surveys, and survey points (77 requirements). Government lots retain official numbers and identifiers; special surveys retain types, identifiers, and classifications; survey points retain available identifiers and coordinates. Vector MBTiles remain on the DigitalOcean VM and are served through the existing MVT backend. No duplicate PLSS PMTiles belong in R2. Target package names are `{state}-plss-{townships,sections,quarter-sections,quarter-quarter-sections,government-lots,special-surveys,survey-points}.mbtiles` under `/root/arizona-naip-build/live-mvt/data/{state}/plss/tiles/`. Existing verified packages may have different names; check dependencies before renaming.

## Read-only inventory, 2026-10-28

`Published` means the running VM discovery service listed the corresponding group. `Present` means a matching named layer was found in an MBTiles metadata record in the standard directory, but discovery did not publish it. `Unconfirmed` means no directly named package for that requirement was identified in this directory; it does not establish that source data is unavailable or that another layer cannot contain it. These labels do not establish data completeness, semantic equivalence, or live browser rendering. Existing verification manifests have not been independently revalidated for every item.

| State | Townships | Sections | Quarter sections | Quarter-quarter | Government lots | Special surveys | Survey points |
|---|---|---|---|---|---|---|---|
| AZ | Published | Published | Present | Present | Published | Published | Present |
| CA | Published | Published | Present | Present | Published | Published | Present |
| CO | Published | Published | Present | Present | Published | Published | Present |
| ID | Published | Published | Present | Present | Published | Unconfirmed | Unconfirmed |
| MT | Published | Present* | Unconfirmed | Unconfirmed | Unconfirmed | Published | Present |
| NV | Published | Published | Present | Present | Published | Published | Present |
| NM | Present* | Present* | Unconfirmed | Unconfirmed | Published | Present* | Present* |
| OR | Unconfirmed | Unconfirmed | Present | Present | Published | Published | Unconfirmed |
| UT | Published | Published | Present | Present | Unconfirmed | Unconfirmed | Present |
| WA | Published | Published | Present | Present | Published | Published | Present |
| WY | Published | Unconfirmed | Unconfirmed | Unconfirmed | Unconfirmed | Published | Present |

\* Montana sections use `plss_first_division`; New Mexico layers use `nm_plss_` prefixes and hyphenated names. These require semantic and source verification; they are not identical naming conventions. Existing Montana/New Mexico/Wyoming second-division or intersected archives are not assumed to satisfy either quarter-section requirement without checking geometry, attributes, and coverage.

The running discovery configuration recognizes township, section, government-lot, and special-survey groups, but not the other three required groups. It also does not recognize the Montana section and New Mexico names above. Filename changes alone do not make those groups discoverable. Washington contains both authoritative and smaller alternate government-lot and quarter-quarter archives; their uniqueness has not been established, so do not overwrite or delete either.

No files, VM services, data packs, or application code were changed as part of this inventory. Production verification of the individual layers remains outstanding.
