"""Build a staged, complete NM reference-quarter layer from CadNSDI geometry.

This intentionally never writes to live-mvt.  Exact source-derived quarters are
kept separate from estimated section-quadrant fills through feature attributes.
"""
import collections
import hashlib
import json
import os
import resource
import shutil
import sqlite3
import sys
from pathlib import Path

from osgeo import ogr

resource.setrlimit(resource.RLIMIT_AS, (7 * 1024**3, 7 * 1024**3))
ogr.UseExceptions()

RUN = Path("/root/arizona-naip-build/prospectors-west/plss-state-full-v1/nm/quarter-build-20261029")
STAGE = RUN / "estimated-quarter-build-20261029-r2"
RAW = RUN / "second-divisions.geojsonl"
SECTIONS = RUN / "sections.geojsonl"
EXACT = RUN / "repair-stage-20261029" / "recovered-all.geojsonl"
STATUS = STAGE / "status.json"
VALID = {"NE", "NW", "SE", "SW"}


def update_status(**values):
    previous = json.loads(STATUS.read_text()) if STATUS.exists() else {}
    previous.update(values)
    STATUS.write_text(json.dumps(previous, indent=2) + "\n")


def geometry_from_json(raw):
    geometry = ogr.CreateGeometryFromJson(raw)
    if not geometry or geometry.IsEmpty():
        raise ValueError("empty geometry")
    if not geometry.IsValid():
        geometry = geometry.MakeValid()
    if not geometry or geometry.IsEmpty() or not geometry.IsValid():
        raise ValueError("invalid geometry")
    return geometry


def feature_id(section, quarter):
    return int(hashlib.sha256(("nm-quarter|" + section + "|" + quarter).encode()).hexdigest()[:13], 16)


def write_feature(output, section, quarter, geometry, method, child_count):
    ident = feature_id(section, quarter)
    feature = {
        "type": "Feature",
        "id": ident,
        "properties": {
            "source_id": ident,
            "FRSTDIVID": section,
            "SECDIVNO": quarter,
            "SECDIVTYP": "R",
            "SECDIVTXT": "Derived reference quarter",
            "DERIVED": True,
            "ESTIMATED": method == "estimated_section_quadrant",
            "AEM_METHOD": method,
            "CHILD_COUNT": child_count,
            "NOMINAL_ACRES": 160,
        },
        "geometry": json.loads(geometry.ExportToJson()),
    }
    output.write(json.dumps(feature, separators=(",", ":")) + "\n")


if STAGE.exists():
    raise SystemExit(f"staging directory already exists: {STAGE}")
if shutil.disk_usage(RUN).free < 15 * 1024**3:
    raise SystemExit("15 GiB disk reserve reached")
STAGE.mkdir()
update_status(state="indexing", raw_source=str(RAW), production_modified=False)

database = sqlite3.connect(STAGE / "parts.sqlite")
database.execute("PRAGMA journal_mode=OFF")
database.execute("PRAGMA synchronous=OFF")
database.execute("CREATE TABLE parts(section TEXT, quarter TEXT, child TEXT, source_id INTEGER, geometry TEXT)")
database.execute("CREATE TABLE sections(section TEXT PRIMARY KEY, geometry TEXT)")
database.execute("CREATE TABLE section_collisions(section TEXT PRIMARY KEY)")

for line in SECTIONS.open():
    feature = json.loads(line)
    section = feature["properties"].get("FRSTDIVID")
    if section:
        raw_geometry = json.dumps(feature["geometry"], separators=(",", ":"))
        existing = database.execute("SELECT geometry FROM sections WHERE section=?", (section,)).fetchone()
        if not existing:
            database.execute("INSERT INTO sections VALUES (?, ?)", (section, raw_geometry))
        elif not geometry_from_json(existing[0]).Equals(geometry_from_json(raw_geometry)):
            database.execute("INSERT OR IGNORE INTO section_collisions VALUES (?)", (section,))
database.commit()

quarter_quarter_count = 0
for source_id, line in enumerate(RAW.open(), 1):
    feature = json.loads(line)
    props = feature.get("properties", {})
    code = str(props.get("SECDIVNO") or "").strip().upper()
    section = props.get("FRSTDIVID")
    if props.get("SECDIVTXT") != "Aliquot Part" or not section:
        continue
    if len(code) != 4 or code[:2] not in VALID or code[2:] not in VALID:
        continue
    database.execute(
        "INSERT INTO parts VALUES (?, ?, ?, ?, ?)",
        (section, code[2:], code[:2], source_id, json.dumps(feature["geometry"], separators=(",", ":"))),
    )
    quarter_quarter_count += 1
    if quarter_quarter_count % 25000 == 0:
        database.commit()
        update_status(state="indexing", quarter_quarter_records=quarter_quarter_count)
        if shutil.disk_usage(RUN).free < 15 * 1024**3:
            raise RuntimeError("15 GiB disk reserve reached")
database.commit()
database.execute("CREATE INDEX parts_group ON parts(section, quarter, child)")
database.commit()

exact = {}
for line in EXACT.open():
    feature = json.loads(line)
    props = feature["properties"]
    exact[(props["FRSTDIVID"], props["SECDIVNO"])] = geometry_from_json(json.dumps(feature["geometry"]))

output_path = STAGE / "nm-plss-quarter-sections-complete.geojsonl"
stats = collections.Counter()
seen = set()
update_status(state="deriving", quarter_quarter_records=quarter_quarter_count, exact_repairs=len(exact))

with output_path.open("x") as output:
    cursor = database.execute("SELECT section, quarter, child, source_id, geometry FROM parts ORDER BY section, quarter, child, source_id")
    current = None
    rows = []

    def process(key, values):
        if key is None:
            return
        section, quarter = key
        if key in seen:
            raise ValueError(f"duplicate group {key}")
        seen.add(key)
        if key in exact:
            write_feature(output, section, quarter, exact[key], "source_verified_repair", len(values))
            stats["exact_repairs"] += 1
            return
        children = {row[2] for row in values}
        if len(values) == 4 and children == VALID:
            multi = ogr.Geometry(ogr.wkbMultiPolygon)
            for _, _, _, _, raw in values:
                part = geometry_from_json(raw)
                if part.GetGeometryName() == "POLYGON":
                    multi.AddGeometry(part)
                else:
                    for index in range(part.GetGeometryCount()):
                        multi.AddGeometry(part.GetGeometryRef(index))
            merged = multi.UnionCascaded()
            if not merged or merged.IsEmpty() or not merged.IsValid():
                raise ValueError(f"invalid authoritative union {key}")
            write_feature(output, section, quarter, merged, "source_quarter_quarter_union", 4)
            stats["authoritative_unions"] += 1
            return

        row = database.execute("SELECT geometry FROM sections WHERE section=?", (section,)).fetchone()
        collision = database.execute("SELECT 1 FROM section_collisions WHERE section=?", (section,)).fetchone()
        if not row:
            stats["unmapped_no_section"] += 1
            return
        if collision:
            stats["unmapped_ambiguous_section"] += 1
            return
        section_geometry = geometry_from_json(row[0])
        envelope = section_geometry.GetEnvelope()
        middle_x = (envelope[0] + envelope[1]) / 2
        middle_y = (envelope[2] + envelope[3]) / 2
        west = quarter.endswith("W")
        north = quarter.startswith("N")
        polygon = ogr.Geometry(ogr.wkbPolygon)
        ring = ogr.Geometry(ogr.wkbLinearRing)
        min_x, max_x = (envelope[0], middle_x) if west else (middle_x, envelope[1])
        min_y, max_y = (middle_y, envelope[3]) if north else (envelope[2], middle_y)
        for coordinate in ((min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y), (min_x, min_y)):
            ring.AddPoint(*coordinate)
        polygon.AddGeometry(ring)
        estimated = section_geometry.Intersection(polygon)
        if not estimated or estimated.IsEmpty() or not estimated.IsValid() or estimated.GetGeometryName() not in ("POLYGON", "MULTIPOLYGON"):
            stats["unmapped_invalid_estimate"] += 1
            return
        write_feature(output, section, quarter, estimated, "estimated_section_quadrant", len(values))
        stats["estimated"] += 1

    for row in cursor:
        key = (row[0], row[1])
        if current is not None and key != current:
            process(current, rows)
            rows = []
            if len(seen) % 10000 == 0:
                update_status(state="deriving", groups_processed=len(seen), **dict(stats))
        current = key
        rows.append(row)
    process(current, rows)

database.close()
update_status(state="derived", groups_processed=len(seen), **dict(stats))
(STAGE / "preparation.json").write_text(json.dumps({
    "source": "NM CadNSDI official second divisions and sections",
    "source_quarter_quarter_records": quarter_quarter_count,
    "groups": len(seen),
    "counts": dict(stats),
    "production_modified": False,
}, indent=2) + "\n")
print(json.dumps(dict(stats), sort_keys=True), flush=True)
