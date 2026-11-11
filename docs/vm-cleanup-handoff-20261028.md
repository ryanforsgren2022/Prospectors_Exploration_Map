# VM cleanup audit handoff — October 28, 2026

## Current status

At 23:58 UTC, the VM root filesystem (`/dev/vda1`) showed 154 GB total, 127 GB used, and 28 GB available (82% used). These are `df -h` rounded values. Check again before any large operation.

The live MVT service uses `/root/arizona-naip-build/live-mvt/data`, which resolves to `/root/LIVE_SITE_CASHE/live-mvt/data`. Preserve active data, source material needed for future work, and backups unless the user specifically approves their deletion. Some files are hard-linked, so apparent sizes may not equal recoverable space. Confirm current dependencies, links, open files, and disk space before any further cleanup.

## Already deleted with user authorization

The user directed deletion of the unused road build archives and rejected California file. These VM files were removed; the current road archive in R2 was not touched.

| Deleted VM file | Bytes |
|---|---:|
| `/root/arizona-naip-build/prospectors-west/roads/overview-4-6-candidate.wwD2BDwR/detail-original-7-15.pmtiles` | 4,782,334,812 |
| `/root/arizona-naip-build/prospectors-west/roads/merge-z4-5-original-z6plus.vsEaok0D/merged.pmtiles` | 4,928,038,018 |
| `/root/arizona-naip-build/prospectors-west/roads/final/western-prospectors-roads-v3.pmtiles` | 5,100,362,741 |
| `/root/arizona-naip-build/prospectors-west/plss-state-full-v1/ca/quarter-sections/rejected/ca-plss-quarter-sections-dropped-20261024-0141.mbtiles` | 836,124,672 |

After the road deletion, `df -h /` showed 28 GB available, up from 14 GB. After the California deletion it still rounded to 28 GB. Each deleted file had one hard link at the time of deletion.

## Remaining candidates — not deleted

| VM file | Size | Finding |
|---|---:|---|
| `/root/colorado-build/run-20261018T170204Z/jobs/parcels/converted.mbtiles` | 1,918,373,888 bytes | Prior Colorado parcel build output; distinct inode from the live package. |
| `/root/colorado-build/run-20261018T170204Z/jobs/parcels-recovery/converted.mbtiles` | 1,992,048,640 bytes | Colorado parcel recovery build output; distinct inode from the live package. |

The live Colorado package is `/root/LIVE_SITE_CASHE/live-mvt/data/co/parcels/tiles/co-parcels.mbtiles` (1,922,949,120 bytes). Its manifest reports verification and references precision-recovery work. The intermediate files could have recovery value; byte/content equivalence and every dependency have not been established. Get a specific user decision before deleting them.

Other large areas observed include `/root/arizona-naip-build/prospectors-west/plss-state-full-v1` (25 GiB apparent `du`), `withdrawals-state-full-v1` (6.3 GiB), and `/root/nevada-build` (6.8 GiB). These include potentially useful source data or outputs; do not treat directory size as reclaimable without a file-by-file dependency and hard-link check. Prior road log files also exist; at least one monitor log was being updated, so don't assume logs are inactive.

## Wyoming PLSS work in progress

The user authorized starting Wyoming's missing quarter-section and quarter-quarter PLSS work while continuing this cleanup audit. A read-only service check found 1,390,692 records at the Wyoming Geographic Information Science Center BLM second-division service. The source sample contains subdivision identifiers and polygons. Source freshness and statewide completeness remain to be validated.

A source download was started on the VM at approximately 23:57 UTC, October 28. At 23:58 UTC PID `95249` was running. It writes to:

`/root/arizona-naip-build/prospectors-west/plss-state-full-v1/wy/source-20261028/second-division.geojsonl.partial`

Log: `/tmp/fetch-wy-plss-source.log`  
Script on Chromebook: `scripts/fetch-wy-plss-source.py`  
VM script: `/tmp/fetch-wy-plss-source.py`

The downloader pages by object ID, checks ordering and geometry, compares the total count, and stops if available disk drops below 15 GiB, retaining the partial file. A completed download is renamed to `second-division.geojsonl` and receives a manifest. This is **only the source download**; no Wyoming quarter or quarter-quarter MBTiles have been built, installed, or verified. Check the log, process, free space, and manifest before proceeding. The 15 GiB reserve is a stop condition, not proof that a complete build will fit.

## Other outstanding context

A candidate change for shared discovery of quarter sections, quarter-quarter sections, and survey points exists locally in `vm-review/aem_vm_discovery_live_candidate.py`, with coverage in `tests/test_live_plss_discovery.py`. It has not been deployed. The existing frontend uses dataset-specific minimum zooms for additional PLSS layers, which differ between states. The user was asked whether Arizona's 11/12/12 thresholds should become shared; no answer has been recorded. Do not assume those thresholds have been approved.

Follow the repository AGENTS.md: keep behavior uniform across states, build and verify locally before publishing, and publish only directly to production. Respect the user's instruction not to rebuild or repack roads.

## Download update

The initial sequential Wyoming downloader was stopped to honor the user’s three-core, 7 GiB limit. The resumed downloader uses three concurrent requests, a 7 GiB process memory limit, validates existing records and retains the 15 GiB disk reserve. Local script: `scripts/fetch-wy-plss-resume.py`; VM script: `/tmp/fetch-wy-plss-resume.py`; VM log: `/tmp/fetch-wy-plss-resume.log`. Check the log and process status before proceeding; the initial PID and log above no longer describe the active downloader.
