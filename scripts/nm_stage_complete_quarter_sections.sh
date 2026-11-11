#!/bin/bash
set -Eeuo pipefail
ulimit -v 7340032
export TIPPECANOE_MAX_THREADS=3

NM_RUN=/root/arizona-naip-build/prospectors-west/plss-state-full-v1/nm/quarter-build-20261029
NM_STAGE="$NM_RUN/estimated-quarter-build-20261029-r2"

if [ -e "$NM_STAGE" ]; then
  echo "Refusing to reuse existing staging directory: $NM_STAGE" >&2
  exit 1
fi

if [ "$(df -Pk "$NM_RUN" | awk 'NR==2 {print $4}')" -lt $((15 * 1024 * 1024)) ]; then
  echo 'Refusing to start: fewer than 15 GiB free disk remains' >&2
  exit 1
fi

python3 /tmp/nm_build_estimated_quarters.py

tippecanoe -q -P -Z11 -z16 \
  --no-feature-limit --no-tile-size-limit --no-tiny-polygon-reduction \
  -t "$NM_STAGE" -l plss_quarter_sections \
  -n 'New Mexico complete reference quarter sections' \
  -o "$NM_STAGE/nm-plss-quarter-sections-complete.mbtiles" \
  "$NM_STAGE/nm-plss-quarter-sections-complete.geojsonl"

/root/arizona-naip-build/live-mvt/.venv/bin/python /tmp/wy_build_verify.py \
  "$NM_STAGE/nm-plss-quarter-sections-complete.mbtiles" \
  "$NM_STAGE/nm-plss-quarter-sections-complete.geojsonl" \
  plss_quarter_sections

python3 - "$NM_STAGE/preparation.json" <<'PY'
import json
import sys

path = sys.argv[1]
data = json.load(open(path))
data['mbtiles_verified'] = True
data['status'] = 'staged_not_published'
open(path, 'w').write(json.dumps(data, indent=2) + '\n')
PY

echo 'COMPLETE: staged and verified; production untouched'
