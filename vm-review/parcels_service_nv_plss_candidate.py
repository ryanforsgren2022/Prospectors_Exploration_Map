import asyncio
import gzip
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from diskcache import FanoutCache
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from mapbox_vector_tile.Mapbox import vector_tile_pb2
from states.az import layers as az_layers
from states.az import plss as az_plss
from states.az import historic_mines as az_historic_mines
from states.az import state_routes as az_state_routes_module
from states.az import historic_overview as az_historic_overview

az_layers.LAYERS.update(az_plss.LAYERS)
from states.az import claims as az_claims


PARCEL_QUERY = (
    "https://azgeo.az.gov/arcgis/rest/services/"
    "TerraSystems/AZParcelFeatures/FeatureServer/0/query"
)

EXTENT = 4096
BUFFER_PIXELS = 64
ORIGIN = 20037508.342789244

MIN_ZOOM = 12
MAX_ZOOM = 18

PAGE_SIZE = 25000
MAX_PAGES = 8

CACHE_TTL = 120

CACHE_DIR = Path(
    "/root/arizona-naip-build/live-mvt/cache"
)

cache = FanoutCache(
    str(CACHE_DIR),
    shards=8,
    timeout=2,
    size_limit=1024 * 1024 * 1024
)

client = None
upstream_slots = asyncio.Semaphore(4)


@asynccontextmanager
async def lifespan(app):
    global client

    client = httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=10,
            read=90,
            write=20,
            pool=10
        ),
        limits=httpx.Limits(
            max_connections=12,
            max_keepalive_connections=8
        ),
        follow_redirects=True
    )

    yield

    await client.aclose()


app = FastAPI(
    title="American Exploration Maps Live MVT",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)


def mercator_bounds(z, x, y):
    world = ORIGIN * 2
    n = 2 ** z
    size = world / n

    west = -ORIGIN + x * size
    east = west + size

    north = ORIGIN - y * size
    south = north - size

    return west, south, east, north


def signed_area(points):
    total = 0

    for i in range(len(points)):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % len(points)]

        total += x1 * y2 - x2 * y1

    return total / 2


def zigzag(value):
    return (value << 1) ^ (value >> 31)


def command(command_id, count):
    return (count << 3) | command_id


def transform_ring(
    raw_ring,
    west,
    north,
    span
):
    if not raw_ring or len(raw_ring) < 4:
        return None

    source = []

    for point in raw_ring:
        if len(point) < 2:
            continue

        xy = (
            float(point[0]),
            float(point[1])
        )

        if not source or source[-1] != xy:
            source.append(xy)

    if (
        len(source) >= 2
        and source[0] == source[-1]
    ):
        source.pop()

    if len(source) < 3:
        return None

    source_area = signed_area(source)

    if source_area == 0:
        return None

    # ESRI:
    # clockwise = exterior
    # counter-clockwise = hole
    is_exterior = source_area < 0

    tile_points = []

    for px, py in source:
        tx = int(round(
            (px - west) * EXTENT / span
        ))

        ty = int(round(
            (north - py) * EXTENT / span
        ))

        point = (tx, ty)

        if (
            not tile_points
            or tile_points[-1] != point
        ):
            tile_points.append(point)

    if len(tile_points) < 3:
        return None

    tile_area = signed_area(tile_points)

    if tile_area == 0:
        return None

    if is_exterior and tile_area < 0:
        tile_points.reverse()

    elif not is_exterior and tile_area > 0:
        tile_points.reverse()

    return tile_points


def encode_geometry(
    rings,
    west,
    north,
    span
):
    geometry = []

    cursor_x = 0
    cursor_y = 0

    for raw_ring in rings or []:
        points = transform_ring(
            raw_ring,
            west,
            north,
            span
        )

        if not points:
            continue

        first_x, first_y = points[0]

        geometry.append(
            command(1, 1)
        )

        geometry.append(
            zigzag(first_x - cursor_x)
        )

        geometry.append(
            zigzag(first_y - cursor_y)
        )

        cursor_x = first_x
        cursor_y = first_y

        remaining = points[1:]

        if remaining:
            geometry.append(
                command(
                    2,
                    len(remaining)
                )
            )

            for x, y in remaining:
                geometry.append(
                    zigzag(x - cursor_x)
                )

                geometry.append(
                    zigzag(y - cursor_y)
                )

                cursor_x = x
                cursor_y = y

        geometry.append(
            command(7, 1)
        )

    return geometry


def make_tile(
    records,
    west,
    south,
    east,
    north
):
    span = east - west

    tile = vector_tile_pb2.tile()

    layer = tile.layers.add()
    layer.name = "parcels"
    layer.version = 2
    layer.extent = EXTENT

    key_indexes = {}
    value_indexes = {}

    encoded = 0
    rejected = 0

    def key_index(key):
        if key not in key_indexes:
            key_indexes[key] = len(layer.keys)
            layer.keys.append(key)

        return key_indexes[key]

    def value_index(value):
        text = str(value)
        token = ("string", text)

        if token not in value_indexes:
            index = len(layer.values)

            item = layer.values.add()
            item.string_value = text

            value_indexes[token] = index

        return value_indexes[token]

    for record in records:
        geometry = encode_geometry(
            record.get("geometry", {}).get(
                "rings",
                []
            ),
            west,
            north,
            span
        )

        if not geometry:
            rejected += 1
            continue

        feature = layer.features.add()

        attrs = record.get("attributes") or {}

        object_id = attrs.get("OBJECTID")

        if object_id is not None:
            try:
                feature.id = int(object_id)
            except Exception:
                pass

        # MVT polygon
        feature.type = 3
        feature.geometry.extend(geometry)

        for field in (
            "AZ_APN",
            "AZ_Address",
            "AZ_PlaceName"
        ):
            value = attrs.get(field)

            if value in (None, ""):
                continue

            feature.tags.append(
                key_index(field)
            )

            feature.tags.append(
                value_index(value)
            )

        encoded += 1

    return (
        tile.SerializeToString(),
        encoded,
        rejected
    )


async def fetch_page(
    query_bounds,
    result_offset,
    geometry_offset
):
    params = {
        "where": "1=1",

        "geometry": ",".join(
            str(v)
            for v in query_bounds
        ),

        "geometryType":
            "esriGeometryEnvelope",

        "inSR": "3857",

        "spatialRel":
            "esriSpatialRelIntersects",

        "outFields":
            "OBJECTID,"
            "AZ_APN,"
            "AZ_Address,"
            "AZ_PlaceName",

        "returnGeometry":
            "true",

        "outSR":
            "3857",

        "maxAllowableOffset":
            str(geometry_offset / 2),

        "geometryPrecision":
            "2",

        "resultOffset":
            str(result_offset),

        "resultRecordCount":
            str(PAGE_SIZE),

        "orderByFields":
            "OBJECTID ASC",

        "f":
            "json"
    }

    async with upstream_slots:
        response = await client.get(
            PARCEL_QUERY,
            params=params
        )

    response.raise_for_status()

    data = response.json()

    if "error" in data:
        raise RuntimeError(
            str(data["error"])
        )

    return data


async def fetch_records(
    query_bounds,
    geometry_offset
):
    records = []

    offset = 0
    pages = 0

    while True:
        data = await fetch_page(
            query_bounds,
            offset,
            geometry_offset
        )

        batch = data.get(
            "features",
            []
        )

        records.extend(batch)
        pages += 1

        exceeded = data.get(
            "exceededTransferLimit",
            False
        )

        if (
            not exceeded
            and len(batch) < PAGE_SIZE
        ):
            break

        if not batch:
            break

        if pages >= MAX_PAGES:
            raise RuntimeError(
                f"Tile exceeded {MAX_PAGES} ArcGIS pages"
            )

        offset += len(batch)

    return records, pages


async def generate_tile(z, x, y):
    west, south, east, north = (
        mercator_bounds(z, x, y)
    )

    span = east - west

    buffer = (
        span
        * BUFFER_PIXELS
        / EXTENT
    )

    query_bounds = (
        west - buffer,
        south - buffer,
        east + buffer,
        north + buffer
    )

    geometry_offset = (
        span / EXTENT
    )

    started = time.perf_counter()

    records, pages = await fetch_records(
        query_bounds,
        geometry_offset
    )

    upstream_ms = (
        time.perf_counter()
        - started
    ) * 1000

    started = time.perf_counter()

    tile, encoded, rejected = make_tile(
        records,
        west,
        south,
        east,
        north
    )

    encode_ms = (
        time.perf_counter()
        - started
    ) * 1000

    payload = gzip.compress(
        tile,
        compresslevel=6
    )

    return {
        "payload": payload,
        "records": len(records),
        "encoded": encoded,
        "rejected": rejected,
        "pages": pages,
        "upstream_ms": round(
            upstream_ms,
            1
        ),
        "encode_ms": round(
            encode_ms,
            1
        )
    }



# === AZ CLAIMS MVT ===

async def fetch_claims_count(
    query_bounds
):
    params = {
        "where": "1=1",

        "geometry": ",".join(
            str(v)
            for v in query_bounds
        ),

        "geometryType":
            "esriGeometryEnvelope",

        "inSR": "3857",

        "spatialRel":
            "esriSpatialRelIntersects",

        "returnCountOnly":
            "true",

        "f":
            "json"
    }

    async with upstream_slots:
        response = await client.get(
            az_claims.QUERY_URL,
            params=params
        )

    response.raise_for_status()

    data = response.json()

    if "error" in data:
        raise RuntimeError(
            str(data["error"])
        )

    return int(
        data.get("count", 0)
    )


async def fetch_claims_page(
    query_bounds,
    result_offset,
    geometry_offset
):
    params = {
        "where": "1=1",

        "geometry": ",".join(
            str(v)
            for v in query_bounds
        ),

        "geometryType":
            "esriGeometryEnvelope",

        "inSR":
            "3857",

        "spatialRel":
            "esriSpatialRelIntersects",

        "outFields":
            ",".join(
                az_claims.FIELDS
            ),

        "returnGeometry":
            "true",

        "outSR":
            "3857",

        "maxAllowableOffset":
            str(
                geometry_offset / 2
            ),

        "geometryPrecision":
            "2",

        "resultOffset":
            str(result_offset),

        "resultRecordCount":
            str(
                az_claims.PAGE_SIZE
            ),

        "orderByFields":
            "OBJECTID ASC",

        "f":
            "json"
    }

    async with upstream_slots:
        response = await client.get(
            az_claims.QUERY_URL,
            params=params
        )

    response.raise_for_status()

    data = response.json()

    if "error" in data:
        raise RuntimeError(
            str(data["error"])
        )

    return data.get(
        "features",
        []
    )


async def fetch_claim_records(
    query_bounds,
    geometry_offset
):
    total = await fetch_claims_count(
        query_bounds
    )

    if total > az_claims.MAX_RECORDS_PER_TILE:
        raise RuntimeError(
            "Claim tile contains "
            f"{total} records; "
            "safety ceiling exceeded"
        )

    if total == 0:
        return [], 0

    offsets = range(
        0,
        total,
        az_claims.PAGE_SIZE
    )

    batches = await asyncio.gather(
        *[
            fetch_claims_page(
                query_bounds,
                offset,
                geometry_offset
            )
            for offset in offsets
        ]
    )

    records = []

    for batch in batches:
        records.extend(batch)

    return records, len(batches)


def make_claims_tile(
    records,
    west,
    south,
    east,
    north
):
    span = east - west

    tile = vector_tile_pb2.tile()

    layer = tile.layers.add()

    layer.name = (
        az_claims.LAYER_NAME
    )

    layer.version = 2
    layer.extent = EXTENT

    key_indexes = {}
    value_indexes = {}

    encoded = 0
    rejected = 0


    def key_index(key):
        if key not in key_indexes:
            key_indexes[key] = (
                len(layer.keys)
            )

            layer.keys.append(key)

        return key_indexes[key]


    def value_index(value):
        if isinstance(value, bool):
            token = (
                "bool",
                value
            )

        elif isinstance(value, int):
            token = (
                "int",
                value
            )

        elif isinstance(value, float):
            token = (
                "float",
                value
            )

        else:
            token = (
                "string",
                str(value)
            )

        if token in value_indexes:
            return value_indexes[token]

        index = len(
            layer.values
        )

        item = layer.values.add()

        if isinstance(value, bool):
            item.bool_value = value

        elif isinstance(value, int):
            item.sint_value = value

        elif isinstance(value, float):
            item.double_value = value

        else:
            item.string_value = str(
                value
            )

        value_indexes[token] = index

        return index


    for record in records:

        geometry = encode_geometry(
            record.get(
                "geometry",
                {}
            ).get(
                "rings",
                []
            ),
            west,
            north,
            span
        )

        if not geometry:
            rejected += 1
            continue

        feature = (
            layer.features.add()
        )

        attributes = (
            record.get(
                "attributes"
            )
            or {}
        )

        object_id = (
            attributes.get(
                "OBJECTID"
            )
        )

        if object_id is not None:
            try:
                feature.id = int(
                    object_id
                )
            except Exception:
                pass

        # MVT polygon
        feature.type = 3

        feature.geometry.extend(
            geometry
        )

        for field in (
            "CSE_NAME",
            "CSE_NR",
            "CSE_DISP",
            "RCRD_ACRS"
        ):

            value = (
                attributes.get(
                    field
                )
            )

            if value in (
                None,
                ""
            ):
                continue

            feature.tags.append(
                key_index(field)
            )

            feature.tags.append(
                value_index(value)
            )

        encoded += 1

    return (
        tile.SerializeToString(),
        encoded,
        rejected
    )


async def generate_claims_tile(
    z,
    x,
    y
):
    (
        west,
        south,
        east,
        north
    ) = mercator_bounds(
        z,
        x,
        y
    )

    span = east - west

    buffer = (
        span
        * BUFFER_PIXELS
        / EXTENT
    )

    query_bounds = (
        west - buffer,
        south - buffer,
        east + buffer,
        north + buffer
    )

    geometry_offset = (
        span / EXTENT
    )

    started = (
        time.perf_counter()
    )

    records, pages = (
        await fetch_claim_records(
            query_bounds,
            geometry_offset
        )
    )

    upstream_ms = (
        (
            time.perf_counter()
            - started
        )
        * 1000
    )

    started = (
        time.perf_counter()
    )

    (
        tile,
        encoded,
        rejected
    ) = make_claims_tile(
        records,
        west,
        south,
        east,
        north
    )

    encode_ms = (
        (
            time.perf_counter()
            - started
        )
        * 1000
    )

    payload = gzip.compress(
        tile,
        compresslevel=6
    )

    return {
        "payload":
            payload,

        "records":
            len(records),

        "encoded":
            encoded,

        "rejected":
            rejected,

        "pages":
            pages,

        "upstream_ms":
            round(
                upstream_ms,
                1
            ),

        "encode_ms":
            round(
                encode_ms,
                1
            )
    }


@app.get(
    "/az/claims/{z}/{x}/{y}.pbf"
)
async def az_claims_tile(
    z: int,
    x: int,
    y: int
):
    if (
        z < az_claims.MIN_ZOOM
        or
        z > az_claims.MAX_ZOOM
    ):
        raise HTTPException(
            status_code=404,
            detail=(
                "Zoom outside "
                "supported range"
            )
        )

    limit = 2 ** z

    if (
        x < 0
        or
        y < 0
        or
        x >= limit
        or
        y >= limit
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid tile"
        )

    key = (
        f"az:claims:"
        f"{z}:{x}:{y}"
    )

    cached = cache.get(key)

    if cached:
        return Response(
            content=(
                cached["payload"]
            ),

            media_type=(
                "application/"
                "vnd.mapbox-vector-tile"
            ),

            headers={
                "Content-Encoding":
                    "gzip",

                "Cache-Control":
                    "public, max-age=120",

                "X-AEM-Cache":
                    "HIT",

                "X-AEM-Records":
                    str(
                        cached[
                            "records"
                        ]
                    ),

                "X-AEM-Encoded":
                    str(
                        cached[
                            "encoded"
                        ]
                    )
            }
        )

    started = (
        time.perf_counter()
    )

    try:
        result = (
            await generate_claims_tile(
                z,
                x,
                y
            )
        )

    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=str(error)
        )

    total_ms = round(
        (
            time.perf_counter()
            - started
        )
        * 1000,
        1
    )

    cache.set(
        key,
        result,
        expire=(
            az_claims.CACHE_TTL
        )
    )

    return Response(
        content=result["payload"],

        media_type=(
            "application/"
            "vnd.mapbox-vector-tile"
        ),

        headers={
            "Content-Encoding":
                "gzip",

            "Cache-Control":
                "public, max-age=120",

            "X-AEM-Cache":
                "MISS",

            "X-AEM-Records":
                str(
                    result[
                        "records"
                    ]
                ),

            "X-AEM-Encoded":
                str(
                    result[
                        "encoded"
                    ]
                ),

            "X-AEM-Rejected":
                str(
                    result[
                        "rejected"
                    ]
                ),

            "X-AEM-Pages":
                str(
                    result[
                        "pages"
                    ]
                ),

            "X-AEM-Upstream-Ms":
                str(
                    result[
                        "upstream_ms"
                    ]
                ),

            "X-AEM-Encode-Ms":
                str(
                    result[
                        "encode_ms"
                    ]
                ),

            "X-AEM-Total-Ms":
                str(total_ms)
        }
    )



# === AZ GENERIC POLYGON MVT ===

def az_clip_bounds(bounds):
    west, south, east, north = bounds

    (
        az_west,
        az_south,
        az_east,
        az_north
    ) = az_layers.AZ_BOUNDS_3857

    west = max(west, az_west)
    south = max(south, az_south)
    east = min(east, az_east)
    north = min(north, az_north)

    if west >= east or south >= north:
        return None

    return (
        west,
        south,
        east,
        north
    )


async def az_polygon_count(
    config,
    bounds
):
    params = {
        "where": config.get("where", "1=1"),

        "geometry": ",".join(
            str(value)
            for value in bounds
        ),

        "geometryType":
            "esriGeometryEnvelope",

        "inSR":
            "3857",

        "spatialRel":
            "esriSpatialRelIntersects",

        "returnCountOnly":
            "true",

        "f":
            "json"
    }

    async with upstream_slots:
        response = await client.get(
            config["query"],
            params=params
        )

    response.raise_for_status()

    data = response.json()

    if "error" in data:
        raise RuntimeError(
            str(data["error"])
        )

    return int(
        data.get("count", 0)
    )


async def az_polygon_page(
    config,
    bounds,
    offset,
    geometry_offset
):
    params = {
        "where":
            config.get("where", "1=1"),

        "geometry":
            ",".join(
                str(value)
                for value in bounds
            ),

        "geometryType":
            "esriGeometryEnvelope",

        "inSR":
            "3857",

        "spatialRel":
            "esriSpatialRelIntersects",

        "outFields":
            ",".join(
                config["fields"]
            ),

        "returnGeometry":
            "true",

        "outSR":
            "3857",

        "maxAllowableOffset":
            str(
                geometry_offset / 2
            ),

        "geometryPrecision":
            "2",

        "resultOffset":
            str(offset),

        "resultRecordCount":
            str(
                config["page_size"]
            ),

        "f":
            "json"
    }

    async with upstream_slots:
        response = await client.get(
            config["query"],
            params=params
        )

    response.raise_for_status()

    data = response.json()

    if "error" in data:
        raise RuntimeError(
            str(data["error"])
        )

    return data.get(
        "features",
        []
    )


async def az_polygon_records(
    config,
    bounds,
    geometry_offset
):
    count = await az_polygon_count(
        config,
        bounds
    )

    if count == 0:
        return [], 0

    if count > config["max_records"]:
        raise RuntimeError(
            "Tile exceeds record safety ceiling: "
            f"{count}"
        )

    offsets = range(
        0,
        count,
        config["page_size"]
    )

    batches = await asyncio.gather(
        *[
            az_polygon_page(
                config,
                bounds,
                offset,
                geometry_offset
            )
            for offset in offsets
        ]
    )

    records = []

    for batch in batches:
        records.extend(batch)

    return (
        records,
        len(batches)
    )


def az_polygon_tile(
    config,
    records,
    west,
    south,
    east,
    north
):
    span = east - west

    tile = vector_tile_pb2.tile()

    layer = tile.layers.add()

    layer.name = (
        config["layer_name"]
    )

    layer.version = 2
    layer.extent = EXTENT

    key_indexes = {}
    value_indexes = {}

    encoded = 0
    rejected = 0


    def key_index(key):
        if key not in key_indexes:
            key_indexes[key] = (
                len(layer.keys)
            )

            layer.keys.append(key)

        return key_indexes[key]


    def value_index(value):

        if isinstance(value, bool):
            token = (
                "bool",
                value
            )

        elif isinstance(value, int):
            token = (
                "int",
                value
            )

        elif isinstance(value, float):
            token = (
                "float",
                value
            )

        else:
            token = (
                "string",
                str(value)
            )

        if token in value_indexes:
            return value_indexes[token]

        index = len(
            layer.values
        )

        item = layer.values.add()

        if isinstance(value, bool):
            item.bool_value = value

        elif isinstance(value, int):
            item.sint_value = value

        elif isinstance(value, float):
            item.double_value = value

        else:
            item.string_value = str(
                value
            )

        value_indexes[token] = index

        return index


    for record in records:

        geometry = encode_geometry(
            record.get(
                "geometry",
                {}
            ).get(
                "rings",
                []
            ),
            west,
            north,
            span
        )

        if not geometry:
            rejected += 1
            continue

        feature = (
            layer.features.add()
        )

        feature.type = 3

        feature.geometry.extend(
            geometry
        )

        attributes = (
            record.get(
                "attributes"
            )
            or {}
        )

        for field in config["fields"]:

            value = (
                attributes.get(
                    field
                )
            )

            if value in (
                None,
                ""
            ):
                continue

            feature.tags.append(
                key_index(field)
            )

            feature.tags.append(
                value_index(value)
            )

        encoded += 1


    return (
        tile.SerializeToString(),
        encoded,
        rejected
    )


async def generate_az_polygon_tile(
    config,
    z,
    x,
    y
):
    (
        west,
        south,
        east,
        north
    ) = mercator_bounds(
        z,
        x,
        y
    )

    span = east - west

    buffer = (
        span
        * BUFFER_PIXELS
        / EXTENT
    )

    requested_bounds = (
        west - buffer,
        south - buffer,
        east + buffer,
        north + buffer
    )

    query_bounds = az_clip_bounds(
        requested_bounds
    )

    geometry_offset = (
        span / EXTENT
    )

    upstream_started = (
        time.perf_counter()
    )

    if query_bounds is None:
        records = []
        pages = 0
    else:
        (
            records,
            pages
        ) = await az_polygon_records(
            config,
            query_bounds,
            geometry_offset
        )

    upstream_ms = (
        (
            time.perf_counter()
            - upstream_started
        )
        * 1000
    )

    encode_started = (
        time.perf_counter()
    )

    (
        tile,
        encoded,
        rejected
    ) = az_polygon_tile(
        config,
        records,
        west,
        south,
        east,
        north
    )

    encode_ms = (
        (
            time.perf_counter()
            - encode_started
        )
        * 1000
    )

    payload = gzip.compress(
        tile,
        compresslevel=6
    )

    return {
        "payload":
            payload,

        "records":
            len(records),

        "encoded":
            encoded,

        "rejected":
            rejected,

        "pages":
            pages,

        "upstream_ms":
            round(
                upstream_ms,
                1
            ),

        "encode_ms":
            round(
                encode_ms,
                1
            ),
    }


async def az_polygon_response(
    config_key,
    z,
    x,
    y
):
    config = (
        az_layers.LAYERS[
            config_key
        ]
    )

    if (
        z < config["min_zoom"]
        or
        z > config["max_zoom"]
    ):
        raise HTTPException(
            status_code=404,
            detail=(
                "Zoom outside "
                "supported range"
            )
        )

    limit = 2 ** z

    if (
        x < 0
        or
        y < 0
        or
        x >= limit
        or
        y >= limit
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid tile"
        )

    key = (
        f"az:{config_key}:"
        f"{z}:{x}:{y}"
    )

    cached = cache.get(key)

    if cached:
        return Response(
            content=(
                cached["payload"]
            ),

            media_type=(
                "application/"
                "vnd.mapbox-vector-tile"
            ),

            headers={
                "Content-Encoding":
                    "gzip",

                "Cache-Control":
                    "public, max-age=120",

                "X-AEM-Cache":
                    "HIT",

                "X-AEM-Records":
                    str(
                        cached[
                            "records"
                        ]
                    ),

                "X-AEM-Encoded":
                    str(
                        cached[
                            "encoded"
                        ]
                    ),
            }
        )


    started = (
        time.perf_counter()
    )

    try:
        result = (
            await generate_az_polygon_tile(
                config,
                z,
                x,
                y
            )
        )

    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=str(error)
        )


    total_ms = round(
        (
            time.perf_counter()
            - started
        )
        * 1000,
        1
    )

    cache.set(
        key,
        result,
        expire=(
            config["cache_ttl"]
        )
    )


    return Response(
        content=(
            result["payload"]
        ),

        media_type=(
            "application/"
            "vnd.mapbox-vector-tile"
        ),

        headers={
            "Content-Encoding":
                "gzip",

            "Cache-Control":
                "public, max-age=120",

            "X-AEM-Cache":
                "MISS",

            "X-AEM-Records":
                str(
                    result["records"]
                ),

            "X-AEM-Encoded":
                str(
                    result["encoded"]
                ),

            "X-AEM-Rejected":
                str(
                    result["rejected"]
                ),

            "X-AEM-Pages":
                str(
                    result["pages"]
                ),

            "X-AEM-Upstream-Ms":
                str(
                    result["upstream_ms"]
                ),

            "X-AEM-Encode-Ms":
                str(
                    result["encode_ms"]
                ),

            "X-AEM-Total-Ms":
                str(total_ms),
        }
    )


@app.get(
    "/az/withdrawals/authorized/"
    "{z}/{x}/{y}.pbf"
)
async def az_withdrawals_authorized(
    z: int,
    x: int,
    y: int
):
    return await az_polygon_response(
        "withdrawals_authorized",
        z,
        x,
        y
    )


@app.get(
    "/az/withdrawals/pending/"
    "{z}/{x}/{y}.pbf"
)
async def az_withdrawals_pending(
    z: int,
    x: int,
    y: int
):
    return await az_polygon_response(
        "withdrawals_pending",
        z,
        x,
        y
    )


@app.get(
    "/az/surface-management/"
    "{z}/{x}/{y}.pbf"
)
async def az_surface_management(
    z: int,
    x: int,
    y: int
):
    return await az_polygon_response(
        "surface_management",
        z,
        x,
        y
    )



# === AZ PLSS ROUTES ===

@app.get(
    "/az/plss/townships/{z}/{x}/{y}.pbf"
)
async def az_plss_townships(
    z: int,
    x: int,
    y: int
):
    return await az_polygon_response(
        "plss_townships",
        z,
        x,
        y
    )


@app.get(
    "/az/plss/sections/{z}/{x}/{y}.pbf"
)
async def az_plss_sections(
    z: int,
    x: int,
    y: int
):
    return await az_polygon_response(
        "plss_sections",
        z,
        x,
        y
    )



# === AZ HISTORIC MINES DELTA ===

@app.get(
    "/az/historic-mines/updates/"
    "{z}/{x}/{y}.pbf"
)
async def az_historic_mine_updates(
    z: int,
    x: int,
    y: int
):
    result = await asyncio.to_thread(
        az_historic_mines.build_tile,
        z,
        x,
        y
    )

    return Response(
        content=result["payload"],

        media_type=(
            "application/"
            "vnd.mapbox-vector-tile"
        ),

        headers={
            "Content-Encoding":
                "gzip",

            "Cache-Control":
                "public, max-age=120",

            "X-AEM-Encoded":
                str(
                    result["encoded"]
                ),

            "X-AEM-Raw-Bytes":
                str(
                    result["raw_bytes"]
                ),
        }
    )


@app.get(
    "/az/historic-mines/"
    "superseded.json"
)
async def az_historic_mine_superseded():
    return Response(
        content=(
            az_historic_mines
            .superseded_json()
        ),

        media_type=(
            "application/json"
        ),

        headers={
            "Cache-Control":
                "public, max-age=120"
        }
    )


@app.get(
    "/az/historic-mines/status"
)
async def az_historic_mine_status():
    return Response(
        content=(
            az_historic_mines
            .status_json()
        ),

        media_type=(
            "application/json"
        ),

        headers={
            "Cache-Control":
                "no-store"
        }
    )



# === FINAL ZERO GEOJSON ROUTES ===

@app.get(
    "/az/historic-mines/overview/"
    "{z}/{x}/{y}.pbf"
)
async def az_historic_mine_overview(
    z: int,
    x: int,
    y: int
):

    if z < 0 or z > 9:

        raise HTTPException(
            status_code=404,
            detail=(
                "Zoom outside "
                "supported range"
            )
        )


    key = (
        f"az:historic-overview:"
        f"{z}:{x}:{y}"
    )

    cached = cache.get(
        key
    )

    if cached:

        return Response(
            content=(
                cached[
                    "payload"
                ]
            ),

            media_type=(
                "application/"
                "vnd.mapbox-vector-tile"
            ),

            headers={
                "Content-Encoding":
                    "gzip",

                "Cache-Control":
                    "public, max-age=300",

                "X-AEM-Cache":
                    "HIT",
            }
        )


    result = await asyncio.to_thread(
        az_historic_mines
        .build_overview_tile,
        z,
        x,
        y
    )


    cache.set(
        key,
        result,
        expire=300
    )


    return Response(
        content=(
            result["payload"]
        ),

        media_type=(
            "application/"
            "vnd.mapbox-vector-tile"
        ),

        headers={
            "Content-Encoding":
                "gzip",

            "Cache-Control":
                "public, max-age=300",

            "X-AEM-Cache":
                "MISS",

            "X-AEM-Encoded":
                str(
                    result[
                        "encoded"
                    ]
                ),
        }
    )


@app.get(
    "/az/boundary/"
    "{z}/{x}/{y}.pbf"
)
async def az_boundary(
    z: int,
    x: int,
    y: int
):

    return await az_polygon_response(
        "arizona_boundary",
        z,
        x,
        y
    )


@app.get(
    "/az/state-routes/"
    "{z}/{x}/{y}.pbf"
)
async def az_state_routes_tile(
    z: int,
    x: int,
    y: int
):

    if z < 8 or z > 12:

        raise HTTPException(
            status_code=404,
            detail=(
                "Zoom outside "
                "supported range"
            )
        )


    key = (
        f"az:state-routes:"
        f"{z}:{x}:{y}"
    )

    cached = cache.get(
        key
    )


    if cached:

        return Response(
            content=(
                cached[
                    "payload"
                ]
            ),

            media_type=(
                "application/"
                "vnd.mapbox-vector-tile"
            ),

            headers={
                "Content-Encoding":
                    "gzip",

                "Cache-Control":
                    "public, max-age=300",

                "X-AEM-Cache":
                    "HIT",
            }
        )


    try:

        result = await asyncio.to_thread(
            az_state_routes_module.build_tile,
            z,
            x,
            y
        )

    except Exception as error:

        raise HTTPException(
            status_code=502,
            detail=str(error)
        )


    cache.set(
        key,
        result,
        expire=300
    )


    return Response(
        content=(
            result["payload"]
        ),

        media_type=(
            "application/"
            "vnd.mapbox-vector-tile"
        ),

        headers={
            "Content-Encoding":
                "gzip",

            "Cache-Control":
                "public, max-age=300",

            "X-AEM-Cache":
                "MISS",

            "X-AEM-Encoded":
                str(
                    result[
                        "encoded"
                    ]
                ),
        }
    )


@app.get("/health")
async def health():
    return {
        "ok": True,
        "service": "aem-live-mvt",
        "backend": "DigitalOcean VM",
        "layer": "parcels",
        "cache_ttl": CACHE_TTL,
        "min_zoom": MIN_ZOOM,
        "max_zoom": MAX_ZOOM
    }


@app.get(
    "/az/parcels/{z}/{x}/{y}.pbf"
)
@app.get(
    "/parcels/{z}/{x}/{y}.pbf",
    include_in_schema=False
)
async def parcels(
    z: int,
    x: int,
    y: int
):
    if (
        z < MIN_ZOOM
        or z > MAX_ZOOM
    ):
        raise HTTPException(
            status_code=404,
            detail="Zoom outside supported range"
        )

    limit = 2 ** z

    if (
        x < 0
        or y < 0
        or x >= limit
        or y >= limit
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid tile"
        )

    key = f"az:parcels:{z}:{x}:{y}"

    cached = cache.get(key)

    if cached:
        return Response(
            content=cached["payload"],
            media_type=(
                "application/"
                "vnd.mapbox-vector-tile"
            ),
            headers={
                "Content-Encoding": "gzip",
                "Cache-Control":
                    "public, max-age=120",
                "X-AEM-Cache": "HIT",
                "X-AEM-Records":
                    str(cached["records"]),
                "X-AEM-Encoded":
                    str(cached["encoded"])
            }
        )

    started = time.perf_counter()

    try:
        result = await generate_tile(
            z,
            x,
            y
        )

    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=str(error)
        )

    total_ms = round(
        (
            time.perf_counter()
            - started
        ) * 1000,
        1
    )

    cache.set(
        key,
        result,
        expire=CACHE_TTL
    )

    return Response(
        content=result["payload"],
        media_type=(
            "application/"
            "vnd.mapbox-vector-tile"
        ),
        headers={
            "Content-Encoding": "gzip",
            "Cache-Control":
                "public, max-age=120",
            "X-AEM-Cache": "MISS",
            "X-AEM-Records":
                str(result["records"]),
            "X-AEM-Encoded":
                str(result["encoded"]),
            "X-AEM-Rejected":
                str(result["rejected"]),
            "X-AEM-Pages":
                str(result["pages"]),
            "X-AEM-Upstream-Ms":
                str(result["upstream_ms"]),
            "X-AEM-Encode-Ms":
                str(result["encode_ms"]),
            "X-AEM-Total-Ms":
                str(total_ms)
        }
    )



# === AEM UNIVERSAL PLSS V3 ===
# Nevada establishes the directory and naming standard.
# Arizona remains on its original legacy implementation.

import asyncio as _aem_asyncio
import sqlite3 as _aem_sqlite
from pathlib import Path as _AEMPath

_AEM_PLSS_ROOT = _AEMPath(__file__).resolve().parent / "data"


# Nevada selected PLSS deployment: canonical VM archive, no remote storage.
from functools import lru_cache as _aem_plss_lru
import json as _aem_plss_json

_AEM_NV_PLSS_KINDS = {
    "townships": ("plssTownships", "plss_townships"),
    "sections": ("plssSections", "plss_sections"),
    "government-lots": ("plssGovernmentLots", "plss_government_lots"),
    "special-surveys": ("plssSpecialSurveys", "plss_special_surveys"),
}
_AEM_NV_PLSS_ARCHIVE = _AEM_PLSS_ROOT / "nv/plss/tiles/nv-plss.mbtiles"

@_aem_plss_lru(maxsize=1)
def _aem_nv_plss_metadata(mtime_ns, size):
    with _aem_sqlite.connect("file:" + str(_AEM_NV_PLSS_ARCHIVE) + "?mode=ro", uri=True) as db:
        row = db.execute("SELECT value FROM metadata WHERE name='json'").fetchone()
    layers = {x["id"]: x for x in _aem_plss_json.loads(row[0])["vector_layers"]}
    expected = {value[1] for value in _AEM_NV_PLSS_KINDS.values()}
    if set(layers) != expected or any(int(layers[x]["maxzoom"]) != 16 for x in expected):
        raise ValueError("Nevada PLSS archive does not match selected verified scope")
    return layers

def _aem_nv_plss_datasets():
    try:
        stat = _AEM_NV_PLSS_ARCHIVE.stat()
        if stat.st_size <= 0:
            return {}
        layers = _aem_nv_plss_metadata(stat.st_mtime_ns, stat.st_size)
    except (OSError, _aem_sqlite.Error, ValueError, KeyError, TypeError):
        return {}
    return {
        key: {
            "tiles": ["https://tiles.americanexplorationmaps.com/nv/plss/" + kind + "/{z}/{x}/{y}.pbf"],
            "layer": layer,
            "minzoom": int(layers[layer]["minzoom"]),
            "maxzoom": int(layers[layer]["maxzoom"]),
        }
        for kind, (key, layer) in _AEM_NV_PLSS_KINDS.items()
    }

def _aem_discover_plss(state, kind):
    if state == "nv":
        if kind in _AEM_NV_PLSS_KINDS and _aem_nv_plss_datasets():
            return _AEM_NV_PLSS_ARCHIVE
        return None

    if not (
        len(state) == 2
        and state.isascii()
        and state.isalpha()
    ):
        return None

    if kind not in ("townships", "sections"):
        return None

    directory = (
        _AEM_PLSS_ROOT / state / "plss" / "tiles"
    )

    if not directory.is_dir():
        return None

    matches = sorted(
        p for p in directory.glob(
            "*-plss-" + kind + ".mbtiles"
        )
        if p.is_file() and p.stat().st_size > 0
    )

    # Never silently choose between conflicting datasets.
    if len(matches) != 1:
        return None

    return matches[0]


def _aem_read_plss(path, z, x, y):
    with _aem_sqlite.connect(
        "file:" + str(path) + "?mode=ro",
        uri=True,
        timeout=10
    ) as db:
        row = db.execute(
            "SELECT tile_data FROM tiles "
            "WHERE zoom_level=? "
            "AND tile_column=? "
            "AND tile_row=?",
            (z, x, (1 << z) - 1 - y)
        ).fetchone()

    return row[0] if row else None


@app.get("/{state}/plss/{kind}/{z}/{x}/{y}.pbf")
async def aem_shared_plss(
    state: str,
    kind: str,
    z: int,
    x: int,
    y: int
):
    state = state.lower()

    allowed_kinds = _AEM_NV_PLSS_KINDS if state == "nv" else ("townships", "sections")
    if kind not in allowed_kinds:
        raise HTTPException(status_code=404)
    if state == "nv" and not 0 <= z <= 16:
        raise HTTPException(status_code=404)

    if not (0 <= z <= 22):
        raise HTTPException(status_code=404)

    limit = 1 << z

    if not (0 <= x < limit and 0 <= y < limit):
        raise HTTPException(status_code=400)

    # Preserve Arizona's established behavior.
    if state == "az":
        return await az_polygon_response(
            "plss_" + kind, z, x, y
        )

    path = _aem_discover_plss(state, kind)

    if path is None:
        raise HTTPException(
            status_code=404,
            detail="PLSS dataset not registered"
        )

    try:
        data = await _aem_asyncio.to_thread(
            _aem_read_plss, path, z, x, y
        )
    except _aem_sqlite.Error:
        raise HTTPException(
            status_code=503,
            detail="PLSS database unavailable"
        )

    if data is None:
        raise HTTPException(status_code=404)

    headers = {
        "Cache-Control": "public, max-age=120"
    }

    if data[:2] == bytes((31, 139)):
        headers["Content-Encoding"] = "gzip"

    return Response(
        content=data,
        media_type="application/vnd.mapbox-vector-tile",
        headers=headers
    )


# === AEM UNIVERSAL PLSS DISCOVERY V1 ===
# Read-only discovery of Nevada-standard PLSS installations.
# Arizona is intentionally managed by its legacy configuration.

@app.get("/api/states/plss")
async def aem_plss_discovery():
    states = {}

    for directory in sorted(_AEM_PLSS_ROOT.iterdir()):
        if not directory.is_dir():
            continue

        state = directory.name.lower()

        if (
            state == "az"
            or len(state) != 2
            or not state.isascii()
            or not state.isalpha()
        ):
            continue

        if state == "nv":
            datasets = _aem_nv_plss_datasets()
            if datasets:
                states[state] = {"datasets": datasets}
            continue

        datasets = {}

        for kind, name in (
            ("townships", "plssTownships"),
            ("sections", "plssSections"),
        ):
            path = _aem_discover_plss(state, kind)

            if path is None:
                continue

            datasets[name] = {
                "tiles": [
                    "https://tiles.americanexplorationmaps.com/"
                    + state + "/plss/" + kind
                    + "/{z}/{x}/{y}.pbf"
                ],
                "layer": "plss_" + kind,
                "minzoom": 5,
                "maxzoom": 14,
            }

        if datasets:
            states[state] = {
                "datasets": datasets
            }

    return {
        "schemaVersion": 1,
        "states": states
    }


# AEM UNIVERSAL STATE DISCOVERY V1
import json as _aem_discovery_json

@app.get("/api/states/discover")
async def aem_discover_states():
    states = {}

    for folder in sorted(_AEM_PLSS_ROOT.iterdir()):
        code = folder.name.lower()

        if (
            not folder.is_dir()
            or code == "az"
            or len(code) != 2
            or not code.isascii()
            or not code.isalpha()
        ):
            continue

        manifest = folder / "state.json"
        if not manifest.is_file():
            continue

        try:
            state = _aem_discovery_json.loads(manifest.read_text())
            bounds = state["bounds"]
            datasets = state["datasets"]

            if not (
                isinstance(state.get("name"), str)
                and isinstance(bounds, list)
                and len(bounds) == 4
                and all(
                    type(v) in (int, float) for v in bounds
                )
                and -180 <= bounds[0] < bounds[2] <= 180
                and -90 <= bounds[1] < bounds[3] <= 90
                and isinstance(datasets, dict)
            ):
                continue

            state["datasets"] = dict(datasets)

            if code == "nv":
                state["datasets"].pop("plss", None)
                state["datasets"].update(_aem_nv_plss_datasets())
                states[code] = state
                continue

            for kind, key in (
                ("townships", "plssTownships"),
                ("sections", "plssSections")
            ):
                if _aem_discover_plss(code, kind):
                    state["datasets"][key] = {
                        "tiles": [
                            "https://tiles.americanexplorationmaps.com/"
                            + code + "/plss/" + kind
                            + "/{z}/{x}/{y}.pbf"
                        ],
                        "layer": "plss_" + kind,
                        "minzoom": 5,
                        "maxzoom": 14
                    }

            states[code] = state

        except (OSError, ValueError, KeyError, TypeError):
            continue

    return {"schemaVersion": 1, "states": states}

# AEM state-aware search API
from aem_search_service import router as aem_search_router
for aem_search_route in aem_search_router.routes:
    app.router.routes.append(aem_search_route)


# AEM UTAH MVT ROUTES V1
from aem_utah_layers import install as install_utah_layers
install_utah_layers(app)


