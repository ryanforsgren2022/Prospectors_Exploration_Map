#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$HOME/Prospectors_Exploration_Map/builds/boundaries-11-state-2025"
SOURCE="$ROOT/source"
FINAL="$ROOT/final"
ZIP="$SOURCE/cb_2025_us_state_500k.zip"
UNPACK="$SOURCE/cb_2025_us_state_500k"
MANIFEST="$ROOT/manifest.tsv"

mkdir -p "$SOURCE" "$FINAL"

for cmd in python3 curl ogr2ogr tippecanoe; do
  command -v "$cmd" >/dev/null 2>&1 || {
    echo "STOP: required command is unavailable: $cmd"
    exit 1
  }
done

echo "=== BUILD — 11-STATE BOUNDARIES ==="
echo "Started: $(date -Is)"
echo "Build root: $ROOT"

if [[ ! -s "$ZIP" ]]; then
  curl --fail --location --retry 3 --retry-delay 5 --continue-at - \
    -o "$ZIP" \
    "https://www2.census.gov/geo/tiger/GENZ2025/shp/cb_2025_us_state_500k.zip"
fi

if [[ ! -d "$UNPACK" ]]; then
  python3 - "$ZIP" "$UNPACK" <<'PYZIP'
from pathlib import Path
import sys
import zipfile

archive = Path(sys.argv[1])
destination = Path(sys.argv[2])
destination.mkdir(parents=True, exist_ok=True)

with zipfile.ZipFile(archive) as zf:
    zf.extractall(destination)
PYZIP
fi

SHP="$(find "$UNPACK" -maxdepth 1 -type f -name 'cb_2025_us_state_500k.shp' -print -quit)"
[[ -f "$SHP" ]] || {
  echo "STOP: Census state shapefile was not found after extraction."
  exit 1
}

printf 'state\tmbtiles\tbytes\ttiles\tintegrity\n' > "$MANIFEST"

for STATE in AZ CA CO ID MT NV NM OR UT WA WY; do
  CODE="$(printf '%s' "$STATE" | tr '[:upper:]' '[:lower:]')"
  STATE_DIR="$FINAL/$CODE"
  GEOJSON="$STATE_DIR/$CODE.boundary.geojson"
  OUT="$STATE_DIR/boundary.mbtiles"

  mkdir -p "$STATE_DIR"

  if [[ ! -s "$OUT" ]]; then
    echo "--- BUILDING $STATE ---"

    ogr2ogr -overwrite -f GeoJSON "$GEOJSON" "$SHP" \
      -where "STUSPS='$STATE'" \
      -select "STATEFP,STUSPS,NAME,LSAD,ALAND,AWATER"

    [[ -s "$GEOJSON" ]] || {
      echo "STOP: empty boundary extraction for $STATE"
      exit 1
    }

    tippecanoe \
      -o "$OUT" \
      -l boundary \
      -Z 4 \
      -z 14 \
      --force \
      "$GEOJSON"
  else
    echo "--- VERIFYING EXISTING $STATE OUTPUT ---"
  fi

  VERIFY="$(python3 - "$OUT" <<'PYVERIFY'
from pathlib import Path
import sqlite3
import sys

path = Path(sys.argv[1])

with sqlite3.connect(path) as db:
    integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
    tiles = db.execute("SELECT count(*) FROM tiles").fetchone()[0]

if integrity != "ok":
    raise SystemExit(f"integrity={integrity}")

if tiles < 1:
    raise SystemExit("tiles=0")

print(f"{path.stat().st_size}\t{tiles}\t{integrity}")
PYVERIFY
)"

  IFS=$'\t' read -r BYTES TILES INTEGRITY <<< "$VERIFY"
  printf '%s\t%s\t%s\t%s\t%s\n' \
    "$STATE" "$OUT" "$BYTES" "$TILES" "$INTEGRITY" >> "$MANIFEST"

  echo "DONE: $STATE — $TILES tiles"
done

echo "=== VERIFY — COMPLETE ==="
column -t -s $'\t' "$MANIFEST" 2>/dev/null || cat "$MANIFEST"
echo "Finished: $(date -Is)"
