#!/usr/bin/env bash
set -Eeuo pipefail

# One-time candidate. All outputs are new files in the supplied scratch folder.
scratch=${1:?Pass the existing candidate scratch directory}
original=/root/arizona-naip-build/prospectors-west/roads/final/western-prospectors-roads-v3.pmtiles
filter="$scratch/filter-road-overview-tiles.py"
test -d "$scratch" && test -s "$original" && test -f "$filter"
for output in overview-filtered.pmtiles detail-original-7-15.pmtiles merged-filtered.pmtiles; do
  test ! -e "$scratch/$output"
done
free_kib=$(df -Pk "$scratch" | awk 'NR==2 {print $4}')
(( free_kib >= 16 * 1048576 )) || { echo 'Less than 16 GiB free; stopping' >&2; exit 1; }
export TMPDIR="$scratch/tmp" TIPPECANOE_MAX_THREADS=3
test -d "$TMPDIR"

echo 'Filtering the existing zoom 4–6 tile payloads without re-tiling'
python3 -u "$filter" "$original" "$scratch/overview-filtered.mbtiles"
pmtiles convert "$scratch/overview-filtered.mbtiles" "$scratch/overview-filtered.pmtiles"
pmtiles verify "$scratch/overview-filtered.pmtiles"

free_kib=$(df -Pk "$scratch" | awk 'NR==2 {print $4}')
(( free_kib >= 14 * 1048576 )) || { echo 'Less than 14 GiB free; stopping' >&2; exit 1; }
echo 'Extracting existing zooms 7–15'
pmtiles extract "$original" "$scratch/detail-original-7-15.pmtiles" --minzoom=7 --maxzoom=15
free_kib=$(df -Pk "$scratch" | awk 'NR==2 {print $4}')
(( free_kib >= 9 * 1048576 )) || { echo 'Less than 9 GiB free; stopping' >&2; exit 1; }
echo 'Merging disjoint zoom ranges'
pmtiles merge "$scratch/overview-filtered.pmtiles" "$scratch/detail-original-7-15.pmtiles" "$scratch/merged-filtered.pmtiles"
pmtiles verify "$scratch/merged-filtered.pmtiles"
sha256sum "$scratch/overview-filtered.pmtiles" "$scratch/detail-original-7-15.pmtiles" "$scratch/merged-filtered.pmtiles"
pmtiles show "$scratch/merged-filtered.pmtiles" --header-json
echo "CANDIDATE_READY $scratch/merged-filtered.pmtiles"
