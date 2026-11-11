import gzip
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx


ROOT = Path(
    __file__
).resolve().parent

BASELINE_PATH = (
    ROOT
    / "data"
    / "historic-mines-baseline.json.gz"
)

DB_PATH = (
    ROOT
    / "data"
    / "az-historic-mines-delta.sqlite3"
)

MRDS_QUERY = (
    "https://energy.usgs.gov/"
    "arcgis/rest/services/Hosted/"
    "Mineral_Resource_Data_System/"
    "FeatureServer/0/query"
)

ARIZONA_QUERY = (
    "https://tigerweb.geo.census.gov/"
    "arcgis/rest/services/TIGERweb/"
    "State_County/MapServer/0/query"
)

AZ_BBOX = (
    -114.9,
    31.2,
    -108.9,
    37.1
)

PAGE_SIZE = 2000


def clean(value):
    if value is None:
        return ""

    return str(
        value
    ).strip()


def fingerprint(
    site_name,
    dev_stat,
    lon,
    lat
):
    payload = [
        clean(
            site_name
        ).lower(),

        clean(
            dev_stat
        ).lower(),

        round(
            float(lon),
            5
        ),

        round(
            float(lat),
            5
        ),
    ]

    raw = json.dumps(
        payload,
        separators=(",", ":"),
        ensure_ascii=False
    )

    return hashlib.sha256(
        raw.encode()
    ).hexdigest()


def point_in_ring(
    x,
    y,
    ring
):
    inside = False

    j = len(ring) - 1

    for i in range(
        len(ring)
    ):
        xi, yi = ring[i][:2]
        xj, yj = ring[j][:2]

        intersects = (
            (yi > y)
            !=
            (yj > y)
        ) and (
            x
            <
            (
                (xj - xi)
                * (y - yi)
                / (
                    (yj - yi)
                    or 1e-30
                )
                + xi
            )
        )

        if intersects:
            inside = not inside

        j = i

    return inside


def point_in_polygon(
    x,
    y,
    polygon
):
    if not polygon:
        return False

    if not point_in_ring(
        x,
        y,
        polygon[0]
    ):
        return False

    for hole in polygon[1:]:
        if point_in_ring(
            x,
            y,
            hole
        ):
            return False

    return True


def point_in_geometry(
    x,
    y,
    geometry
):
    kind = geometry.get(
        "type"
    )

    coordinates = geometry.get(
        "coordinates",
        []
    )

    if kind == "Polygon":
        return point_in_polygon(
            x,
            y,
            coordinates
        )

    if kind == "MultiPolygon":
        return any(
            point_in_polygon(
                x,
                y,
                polygon
            )
            for polygon
            in coordinates
        )

    return False


def load_arizona_geometry(
    client
):
    params = {
        "where":
            "NAME = 'Arizona'",

        "outFields":
            "NAME",

        "returnGeometry":
            "true",

        "outSR":
            "4326",

        "f":
            "geojson",
    }

    response = client.get(
        ARIZONA_QUERY,
        params=params
    )

    response.raise_for_status()

    data = response.json()

    features = data.get(
        "features",
        []
    )

    if not features:
        raise RuntimeError(
            "Arizona boundary query returned no features"
        )

    return features[0][
        "geometry"
    ]


def fetch_current(
    client,
    az_geometry
):
    current = {}

    offset = 0

    while True:

        params = {
            "where":
                "1=1",

            "geometry":
                ",".join(
                    str(value)
                    for value
                    in AZ_BBOX
                ),

            "geometryType":
                "esriGeometryEnvelope",

            "inSR":
                "4326",

            "spatialRel":
                "esriSpatialRelIntersects",

            "outFields":
                (
                    "objectid_1,"
                    "dep_id,"
                    "site_name,"
                    "dev_stat,"
                    "code_list,"
                    "grade"
                ),

            "returnGeometry":
                "true",

            "outSR":
                "4326",

            "resultOffset":
                str(offset),

            "resultRecordCount":
                str(PAGE_SIZE),

            "orderByFields":
                "objectid_1 ASC",

            "f":
                "json",
        }

        response = client.get(
            MRDS_QUERY,
            params=params
        )

        response.raise_for_status()

        data = response.json()

        if "error" in data:
            raise RuntimeError(
                str(
                    data["error"]
                )
            )

        features = data.get(
            "features",
            []
        )

        for feature in features:

            attrs = (
                feature.get(
                    "attributes"
                )
                or {}
            )

            geom = (
                feature.get(
                    "geometry"
                )
                or {}
            )

            dep_id = clean(
                attrs.get(
                    "dep_id"
                )
            )

            x = geom.get(
                "x"
            )

            y = geom.get(
                "y"
            )

            if (
                not dep_id
                or
                x is None
                or
                y is None
            ):
                continue

            lon = float(x)
            lat = float(y)

            if not point_in_geometry(
                lon,
                lat,
                az_geometry
            ):
                continue

            current[dep_id] = {
                "dep_id":
                    dep_id,

                "lon":
                    lon,

                "lat":
                    lat,

                "site_name":
                    clean(
                        attrs.get(
                            "site_name"
                        )
                    ),

                "dev_stat":
                    clean(
                        attrs.get(
                            "dev_stat"
                        )
                    ),

                "code_list":
                    clean(
                        attrs.get(
                            "code_list"
                        )
                    ),

                "grade":
                    clean(
                        attrs.get(
                            "grade"
                        )
                    ),

                "fingerprint":
                    fingerprint(
                        attrs.get(
                            "site_name"
                        ),
                        attrs.get(
                            "dev_stat"
                        ),
                        lon,
                        lat
                    ),
            }

        print(
            "Fetched page:",
            offset,
            "records:",
            len(features),
            "AZ retained:",
            len(current),
            flush=True
        )

        if len(features) < PAGE_SIZE:
            break

        offset += PAGE_SIZE

    return current


def open_database():
    connection = sqlite3.connect(
        DB_PATH
    )

    connection.execute(
        """
        PRAGMA journal_mode=WAL
        """
    )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS baseline (
          dep_id TEXT PRIMARY KEY,
          fingerprint TEXT NOT NULL
        )
        """
    )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS delta (
          dep_id TEXT PRIMARY KEY,
          lon REAL NOT NULL,
          lat REAL NOT NULL,
          site_name TEXT,
          dev_stat TEXT,
          code_list TEXT,
          grade TEXT,
          fingerprint TEXT NOT NULL,
          synced_at TEXT NOT NULL
        )
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        delta_lon_lat_idx
        ON delta(lon, lat)
        """
    )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS removed (
          dep_id TEXT PRIMARY KEY
        )
        """
    )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS meta (
          key TEXT PRIMARY KEY,
          value TEXT
        )
        """
    )

    return connection


def main():
    if not BASELINE_PATH.exists():
        raise SystemExit(
            "Baseline manifest missing"
        )

    with gzip.open(
        BASELINE_PATH,
        "rt",
        encoding="utf-8"
    ) as fh:
        manifest = json.load(
            fh
        )

    baseline_records = (
        manifest.get(
            "records",
            {}
        )
    )

    if len(
        baseline_records
    ) < 5000:
        raise SystemExit(
            "Baseline record count is unsafe"
        )

    baseline = {
        str(dep_id):
            record[
                "fingerprint"
            ]
        for (
            dep_id,
            record
        )
        in baseline_records.items()
    }

    timeout = httpx.Timeout(
        120.0,
        connect=30.0
    )

    with httpx.Client(
        timeout=timeout,
        follow_redirects=True
    ) as client:

        az_geometry = (
            load_arizona_geometry(
                client
            )
        )

        current = fetch_current(
            client,
            az_geometry
        )

    if len(current) < 5000:
        raise SystemExit(
            "SAFETY STOP: current MRDS Arizona count "
            f"is only {len(current)}"
        )

    baseline_ids = set(
        baseline
    )

    current_ids = set(
        current
    )

    changed = []

    new = []

    for dep_id, record in (
        current.items()
    ):

        if dep_id not in baseline:
            new.append(
                record
            )
            continue

        if (
            record["fingerprint"]
            !=
            baseline[dep_id]
        ):
            changed.append(
                record
            )

    removed = sorted(
        baseline_ids
        - current_ids
    )

    total_delta = (
        len(new)
        + len(changed)
    )

    # A huge first-run delta almost certainly means the
    # archive/source fingerprints are incompatible.
    safety_limit = max(
        1000,
        int(
            len(baseline)
            * 0.25
        )
    )

    if total_delta > safety_limit:
        raise SystemExit(
            "SAFETY STOP: unexpected delta size "
            f"{total_delta}; limit {safety_limit}"
        )

    now = datetime.now(
        timezone.utc
    ).isoformat()

    connection = (
        open_database()
    )

    with connection:

        connection.execute(
            "DELETE FROM baseline"
        )

        connection.executemany(
            """
            INSERT INTO baseline(
              dep_id,
              fingerprint
            )
            VALUES (?, ?)
            """,
            [
                (
                    dep_id,
                    fp
                )
                for dep_id, fp
                in baseline.items()
            ]
        )

        connection.execute(
            "DELETE FROM delta"
        )

        rows = (
            new
            + changed
        )

        connection.executemany(
            """
            INSERT INTO delta(
              dep_id,
              lon,
              lat,
              site_name,
              dev_stat,
              code_list,
              grade,
              fingerprint,
              synced_at
            )
            VALUES(
              ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            [
                (
                    item["dep_id"],
                    item["lon"],
                    item["lat"],
                    item["site_name"],
                    item["dev_stat"],
                    item["code_list"],
                    item["grade"],
                    item["fingerprint"],
                    now
                )
                for item
                in rows
            ]
        )

        connection.execute(
            "DELETE FROM removed"
        )

        connection.executemany(
            """
            INSERT INTO removed(
              dep_id
            )
            VALUES (?)
            """,
            [
                (dep_id,)
                for dep_id
                in removed
            ]
        )

        meta = {
            "last_sync_utc":
                now,

            "current_records":
                str(
                    len(current)
                ),

            "new_records":
                str(
                    len(new)
                ),

            "changed_records":
                str(
                    len(changed)
                ),

            "removed_records":
                str(
                    len(removed)
                ),
        }

        for key, value in (
            meta.items()
        ):
            connection.execute(
                """
                INSERT INTO meta(
                  key,
                  value
                )
                VALUES (?, ?)
                ON CONFLICT(key)
                DO UPDATE SET
                  value = excluded.value
                """,
                (
                    key,
                    value
                )
            )

    # === LIVE OVERVIEW TABLE ===

    bins = {}

    for record in current.values():

        lon = float(
            record["lon"]
        )

        lat = float(
            record["lat"]
        )

        grid_x = int(
            (lon + 180.0)
            // 0.25
        )

        grid_y = int(
            (lat + 90.0)
            // 0.25
        )

        key = (
            f"{grid_x}-{grid_y}"
        )

        item = bins.get(
            key
        )

        if item is None:

            item = {
                "tile_key":
                    key,

                "count":
                    0,

                "lon_sum":
                    0.0,

                "lat_sum":
                    0.0,
            }

            bins[key] = item

        item["count"] += 1

        item["lon_sum"] += lon
        item["lat_sum"] += lat


    with connection:

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS overview (
              tile_key TEXT PRIMARY KEY,
              lon REAL NOT NULL,
              lat REAL NOT NULL,
              point_count INTEGER NOT NULL
            )
            """
        )

        connection.execute(
            "DELETE FROM overview"
        )

        connection.executemany(
            """
            INSERT INTO overview(
              tile_key,
              lon,
              lat,
              point_count
            )
            VALUES (?, ?, ?, ?)
            """,
            [
                (
                    item["tile_key"],

                    item["lon_sum"]
                    / item["count"],

                    item["lat_sum"]
                    / item["count"],

                    item["count"],
                )

                for item
                in bins.values()
            ]
        )


    connection.close()

    print()
    print(
        "Baseline:",
        len(baseline)
    )

    print(
        "Current Arizona:",
        len(current)
    )

    print(
        "New:",
        len(new)
    )

    print(
        "Changed:",
        len(changed)
    )

    print(
        "Removed:",
        len(removed)
    )

    print(
        "PASS: historic mine delta synchronized"
    )


if __name__ == "__main__":
    main()
