#!/usr/bin/env bash
set -Eeuo pipefail

# Run once inside a new, empty scratch directory and under an externally
# enforced CPU/memory limit. This script never writes to the existing archive.
scratch=${1:?Pass a newly created empty scratch directory}
producer=/root/arizona-naip-build/prospectors-west/roads/bin/stream-western-roads-v3.py
python=/root/arizona-naip-build/prospectors-west/roads/bin/.venv/bin/python
original=/root/arizona-naip-build/prospectors-west/roads/final/western-prospectors-roads-v3.pmtiles
filter="$scratch/prepare-road-overview.py"
base=https://download.geofabrik.de/north-america/us
states=(washington oregon california idaho nevada montana wyoming utah colorado arizona new-mexico)

test -d "$scratch" && test -f "$filter" && test -f "$producer" && test -x "$python" && test -s "$original"
test ! -e "$scratch/raw" && test ! -e "$scratch/overview.pmtiles" && test ! -e "$scratch/merged.pmtiles"
mkdir "$scratch/raw" "$scratch/tmp" "$scratch/cache"
export TMPDIR="$scratch/tmp" TIPPECANOE_MAX_THREADS=3

require_free_gib() {
  local available
  available=$(df -Pk "$scratch" | awk 'NR==2 {print $4}')
  if (( available < $1 * 1048576 )); then
    printf 'Stopping: less than %s GiB free in scratch filesystem\n' "$1" >&2
    exit 1
  fi
}

require_free_gib 18
printf 'Scratch: %s\n' "$scratch"
printf 'Original archive: %s\n' "$original"
for state in "${states[@]}"; do
  printf 'Downloading %s\n' "$state"
  curl --fail --location --silent --show-error --retry 3 --connect-timeout 30 \
    "$base/$state-latest.osm.pbf.md5" -o "$scratch/raw/$state.md5"
  expected=$(awk 'NR==1 {print $1}' "$scratch/raw/$state.md5")
  [[ $expected =~ ^[a-fA-F0-9]{32}$ ]]
  curl --fail --location --silent --show-error --retry 3 --connect-timeout 30 \
    "$base/$state-latest.osm.pbf" -o "$scratch/raw/$state.osm.pbf"
  actual=$(md5sum "$scratch/raw/$state.osm.pbf" | awk '{print $1}')
  [[ ${actual,,} == ${expected,,} ]] || { printf 'Checksum failed: %s\n' "$state" >&2; exit 1; }
  require_free_gib 17
done

produce() {
  for state in "${states[@]}"; do
    printf 'Preparing %s\n' "$state" >&2
    cache_file="$scratch/cache/$state.nodecache"
    test ! -e "$cache_file"
    "$python" -u "$producer" "$scratch/raw/$state.osm.pbf" "$state" "$cache_file" |
      "$python" -u "$filter"
    # This is a temporary index created by this run in its own new directory.
    if [[ -f "$cache_file" ]]; then rm -- "$cache_file"; fi
    require_free_gib 14
  done
}

printf 'Building zooms 4–6 without automatic feature dropping\n'
produce | tippecanoe -P -Z4 -z6 -B6 -r1 -l roads \
  -n AEM_Western_Roads_Overview_Candidate -A OpenStreetMap \
  --maximum-tile-bytes=1000000 --no-simplification-of-shared-nodes \
  -o "$scratch/overview.pmtiles"
pmtiles verify "$scratch/overview.pmtiles"

require_free_gib 14
printf 'Extracting unchanged zooms 7–15\n'
pmtiles extract "$original" "$scratch/detail-7-15.pmtiles" --minzoom=7 --maxzoom=15
require_free_gib 9
printf 'Merging disjoint zoom ranges\n'
pmtiles merge "$scratch/overview.pmtiles" "$scratch/detail-7-15.pmtiles" "$scratch/merged.pmtiles"
pmtiles verify "$scratch/merged.pmtiles"
sha256sum "$scratch/overview.pmtiles" "$scratch/detail-7-15.pmtiles" "$scratch/merged.pmtiles"
pmtiles show "$scratch/merged.pmtiles" --header-json
printf 'CANDIDATE_READY %s\n' "$scratch/merged.pmtiles"
