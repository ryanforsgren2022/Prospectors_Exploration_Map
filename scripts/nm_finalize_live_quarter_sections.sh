#!/bin/bash
set -Eeuo pipefail

build_pid=${1:?build PID is required}
run=/root/arizona-naip-build/prospectors-west/plss-state-full-v1/nm/quarter-build-20261029
stage="$run/estimated-quarter-build-20261029-r2"
candidate="$stage/nm-plss-quarter-sections-complete.mbtiles"
metadata="$stage/preparation.json"
live=/root/arizona-naip-build/live-mvt/data/nm/plss/tiles/nm-plss-quarter-sections.mbtiles

while kill -0 "$build_pid" 2>/dev/null; do
  sleep 30
done

python3 - "$metadata" "$candidate" <<'PY'
import json
import pathlib
import sys

metadata = json.loads(pathlib.Path(sys.argv[1]).read_text())
candidate = pathlib.Path(sys.argv[2])
if metadata.get("mbtiles_verified") is not True or metadata.get("status") != "staged_not_published":
    raise SystemExit("build did not reach verified staged status")
if not candidate.is_file() or candidate.stat().st_size == 0:
    raise SystemExit("verified MBTiles candidate is missing or empty")
PY

mv -f "$candidate" "$live"
python3 - "$metadata" <<'PY'
import json
import sys

path = sys.argv[1]
data = json.load(open(path))
data["status"] = "published_live"
open(path, "w").write(json.dumps(data, indent=2) + "\n")
PY
echo "COMPLETE: verified NM quarter-sections MBTiles published to $live"
