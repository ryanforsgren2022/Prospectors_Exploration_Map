
import gzip
import json
import math
import os
import re
import sqlite3
import struct
import time
import zlib
from pathlib import Path

from fastapi import HTTPException, Response, Request
from starlette.responses import StreamingResponse
from aem_claims_classification import filter_claim_tile

DATA = (Path(__file__).resolve().parent / "data").resolve()
REGISTRY = Path(__file__).resolve().parent / "western-datasets.json"
HOST = "https://tiles.americanexplorationmaps.com"

ROAD_STATES = frozenset((
    "az", "ca", "co", "id", "mt", "nm",
    "nv", "or", "ut", "wa", "wy"
))

CACHE_TIME = 0
CACHE_DATA = None


def archive_metadata(path):
    try:
        stat = path.stat()

        wal = path.with_name(path.name + "-wal")
        if wal.exists() and wal.stat().st_size:
            return None

        if stat.st_size < 512:
            return None

        # Prevent discovery of archives still being uploaded.
        if time.time() - stat.st_mtime < 15:
            return None

        if path.suffix == ".mbtiles":
            db = sqlite3.connect(
                "file:" + str(path) + "?mode=ro&immutable=1",
                uri=True,
                timeout=3
            )

            try:
                meta = dict(
                    db.execute(
                        "SELECT name,value FROM metadata"
                    ).fetchall()
                )
                if not db.execute("SELECT 1 FROM tiles WHERE length(tile_data)>0 LIMIT 1").fetchone():
                    return None
            finally:
                db.close()

            if meta.get("format") not in ("pbf", "mvt"):
                return None

            layers = json.loads(
                meta.get("json", "{}")
            ).get("vector_layers", [])

            if not layers and meta.get("vector_layers"):
                layers = json.loads(meta["vector_layers"])

            minimum = int(meta.get("minzoom", 0))
            maximum = int(meta.get("maxzoom", 14))

        else:
            with path.open("rb") as f:
                header = f.read(127)

                if header[:8] != b"PMTiles\x03":
                    return None

                offset, length = struct.unpack_from(
                    "<QQ", header, 24
                )

                if (
                    offset + length > stat.st_size
                    or length > 10000000
                ):
                    return None

                f.seek(offset)
                payload = f.read(length)

            compression = header[97]

            if compression == 2:
                payload = gzip.decompress(payload)
            elif compression != 1:
                return None

            layers = json.loads(payload).get(
                "vector_layers", []
            )

            minimum = header[100]
            maximum = header[101]

        layer_ids = [
            item.get("id")
            for item in layers
            if isinstance(item, dict)
            and isinstance(item.get("id"), str)
        ]

        if not layer_ids or maximum < minimum:
            return None

        return {
            "path": path,
            "layers": layer_ids,
            "minzoom": minimum,
            "maxzoom": maximum,
            "format": path.suffix,
            "bytes": stat.st_size,
            "bounds": [float(x) for x in meta["bounds"].split(",")] if path.suffix == ".mbtiles" else None
        }

    except (
        OSError, sqlite3.Error, ValueError,
        TypeError, KeyError, EOFError
    ):
        return None


def _registry_path(state, relative):
    """Resolve a registry path without allowing it outside its state root."""
    if not isinstance(relative, str) or not relative:
        return None
    path = (DATA / relative).resolve()
    if not path.is_relative_to(DATA / state) or path.suffix != ".mbtiles":
        return None
    return path


def _matches_registration(archive, spec):
    return bool(
        archive
        and spec["sourceLayer"] in archive["layers"]
        and archive["minzoom"] <= spec["minzoom"]
        and archive["maxzoom"] >= spec["maxzoom"]
        and archive["bounds"] == spec["bounds"]
        and archive["bytes"] == spec["auditBytes"]
    )


def _select_registered_archive(state, spec, checked):
    """Select a reviewed current path or its verified canonical alias.

    When both paths exist, a canonical path wins only when it is the same
    filesystem object as the reviewed current path. This prevents an occupied
    standardized destination from displacing a reviewed source merely because
    its filename matches. Blocked destinations are not supplied as candidates.
    If only one candidate exists it must still match every audited invariant.
    """
    candidates = {}
    for label, key in (("current", "path"), ("canonical", "canonicalPath")):
        path = _registry_path(state, spec.get(key))
        if path is None:
            continue
        if path not in checked:
            checked[path] = archive_metadata(path)
        if _matches_registration(checked[path], spec):
            candidates[label] = checked[path]

    current = candidates.get("current")
    canonical = candidates.get("canonical")
    if current and canonical:
        try:
            if current["path"].samefile(canonical["path"]):
                return canonical
        except OSError:
            pass
        return current
    return current or canonical


def discover_vm_data():
    """Only publish explicit audit-reviewed MBTiles; never rank competitors by age/size."""
    global CACHE_TIME, CACHE_DATA
    if CACHE_DATA is not None and time.monotonic() - CACHE_TIME < 20:
        return CACHE_DATA
    states, paths = {}, {}
    if not DATA.is_dir() or not REGISTRY.is_file():
        return states, paths
    registry = json.loads(REGISTRY.read_text())
    if registry.get("schemaVersion") != 1:
        raise ValueError("Unsupported Western dataset registry")
    checked = {}
    for code, configuration in registry.get("states", {}).items():
        if code not in ROAD_STATES:
            continue
        manifest = DATA / code / "state.json"
        original = json.loads(manifest.read_text()) if manifest.is_file() else configuration
        state = {key: value for key, value in original.items()
                 if key not in ("datasets", "base", "baseUrl", "autoLayers")}
        state["bounds"] = original.get("bounds", configuration.get("bounds"))
        bounds = state["bounds"]
        if (not isinstance(bounds, list) or len(bounds) != 4 or
                not all(isinstance(x, (float, int)) and math.isfinite(x) for x in bounds) or
                bounds[0] >= bounds[2] or bounds[1] >= bounds[3]):
            continue
        datasets = {}
        for group, spec in configuration.get("datasets", {}).items():
            # Roads and mines are R2-only; explicit parcel registrations run last in the frontend.
            if group in ("roads", "historicMines"):
                continue
            if group in ("claims", "claimsBlmLands") and spec.get("semantics") != "notClosed":
                continue
            archive = _select_registered_archive(code, spec, checked)
            if not archive:
                continue
            entry = {key: spec[key] for key in ("sourceLayer", "minzoom", "maxzoom", "bounds")}
            entry["layer"] = spec["sourceLayer"]
            entry["tiles"] = [HOST + f"/api/vm-data/{code}/{group}/{{z}}/{{x}}/{{y}}.pbf"]
            if group in ("claims", "claimsBlmLands"):
                entry["semantics"] = "notClosed"
                entry["classificationFilter"] = {
                    "rule": "notClosed", "field": spec.get("classificationField", "CSE_DISP"),
                    "normalization": "unicode-whitespace-casefold", "unknownPolicy": "report-separately"
                }
                if "coverage" in spec:
                    entry["coverage"] = spec["coverage"]
            datasets[group] = entry
            paths[(code, group)] = {**archive, "minzoom": spec["minzoom"], "maxzoom": spec["maxzoom"],
                                      "sourceLayer": spec["sourceLayer"],
                                      "classificationField": spec.get("classificationField", "CSE_DISP")}
        # Use independent sources so authorized/pending may come from one or two archives.
        withdrawal = {}
        for kind in ("authorized", "pending"):
            entry = datasets.pop("withdrawals" + kind.title(), None)
            if entry:
                withdrawal[kind] = entry
        if withdrawal:
            datasets["withdrawals"] = withdrawal
        # Preserve the dedicated parcel reader and its overlays as the final family.
        parcel = (original.get("datasets") or {}).get("parcels")
        if parcel and all(url.startswith(HOST + "/") for url in parcel.get("tiles", [])) and parcel.get("tiles"):
            datasets["parcels"] = parcel
        state["datasets"] = datasets
        states[code] = state
    CACHE_TIME = time.monotonic()
    CACHE_DATA = (states, paths)
    return CACHE_DATA


def registered_mbtiles_tile(state, group, z, x, y):
    """Read a registered XYZ tile; shared by v2 and compatibility routes."""
    archive = discover_vm_data()[1].get((state, group))

    if (
        not archive
        or archive["format"] != ".mbtiles"
        or z < archive["minzoom"]
        or z > archive["maxzoom"]
        or z < 0
        or x < 0
        or y < 0
        or x >= 2 ** z
        or y >= 2 ** z
    ):
        raise HTTPException(404)

    try:
        db = sqlite3.connect(
            "file:" + str(archive["path"]) + "?mode=ro&immutable=1",
            uri=True,
            timeout=3
        )
        try:
            result = db.execute(
                "SELECT tile_data FROM tiles WHERE zoom_level=? "
                "AND tile_column=? AND tile_row=?",
                (z, x, (1 << z) - 1 - y)
            ).fetchone()
        finally:
            db.close()
    except sqlite3.Error as error:
        raise HTTPException(503, "Tile archive unavailable") from error

    headers = {
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "public, max-age=120"
    }
    if not result:
        return Response(status_code=204, headers=headers)

    tile = result[0]
    if group in ("claims", "claimsBlmLands"):
        try:
            tile, counts = filter_claim_tile(
                tile, archive["sourceLayer"], archive["classificationField"]
            )
        except (ValueError, OSError, UnicodeError, EOFError, struct.error, zlib.error) as error:
            raise HTTPException(503, "Claims tile classification could not be validated") from error
        headers.update({
            "X-AEM-Claims-Before": str(counts["before"]),
            "X-AEM-Claims-After": str(counts["after"]),
            "X-AEM-Claims-Closed": str(counts["closed"]),
            "X-AEM-Claims-Unknown": str(counts["unknown"]),
            "X-AEM-Claims-By-Classification": json.dumps(counts["byClassification"], ensure_ascii=True),
            "X-AEM-Claims-After-By-Classification": json.dumps(counts["afterByClassification"], ensure_ascii=True),
            "X-AEM-Claims-Unknown-Reasons": json.dumps(counts["unknownReasons"], ensure_ascii=True),
            "Access-Control-Expose-Headers": "X-AEM-Claims-Before,X-AEM-Claims-After,"
                "X-AEM-Claims-Closed,X-AEM-Claims-Unknown,X-AEM-Claims-By-Classification,"
                "X-AEM-Claims-After-By-Classification,X-AEM-Claims-Unknown-Reasons"
        })
        if counts["after"] == 0:
            return Response(status_code=204, headers=headers)

    if tile[:2] == b"\x1f\x8b":
        headers["Content-Encoding"] = "gzip"
    return Response(tile, media_type="application/x-protobuf", headers=headers)


def install_aem_vm_discovery_v2(app):

    @app.get("/api/states/discover-v2")
    def discover_v2():
        states, _ = discover_vm_data()

        return Response(
            json.dumps({
                "schemaVersion": 2,
                "states": states
            }),
            media_type="application/json",
            headers={
                "Cache-Control": "no-store",
                "Access-Control-Allow-Origin": "*"
            }
        )

    @app.get(
        "/api/vm-data/{state}/{group}/{z}/{x}/{y}.pbf"
    )
    def get_mbtiles_tile(
        state: str,
        group: str,
        z: int,
        x: int,
        y: int
    ):
        return registered_mbtiles_tile(state, group, z, x, y)

    @app.get(
        "/api/vm-data/{state}/{group}.pmtiles"
    )
    def get_pmtiles_archive(
        state: str,
        group: str,
        request: Request
    ):
        if group == "roads":
            state_code = state.lower()

            if state_code not in ROAD_STATES:
                raise HTTPException(404)

            road_path = (
                DATA / state_code / "roads" / "roads.pmtiles"
            )

            if (
                not road_path.is_file()
                or road_path.stat().st_size < 512
            ):
                raise HTTPException(404)

            archive = {
                "path": road_path,
                "format": ".pmtiles"
            }
        else:
            archive = discover_vm_data()[1].get(
                (state, group)
            )

        if (
            not archive
            or archive["format"] != ".pmtiles"
        ):
            raise HTTPException(404)

        size = archive["path"].stat().st_size
        requested_range = request.headers.get(
            "range", ""
        )

        match = re.fullmatch(
            r"bytes=(\d+)-(\d*)",
            requested_range
        )

        if not match:
            raise HTTPException(
                416, "Byte range required"
            )

        start = int(match.group(1))

        end = min(
            int(match.group(2))
            if match.group(2)
            else size - 1,
            size - 1
        )

        if start > end or start >= size:
            raise HTTPException(416)

        def stream():
            with archive["path"].open("rb") as f:
                f.seek(start)
                remaining = end - start + 1

                while remaining:
                    chunk = f.read(
                        min(262144, remaining)
                    )

                    if not chunk:
                        break

                    remaining -= len(chunk)
                    yield chunk

        return StreamingResponse(
            stream(),
            status_code=206,
            media_type="application/octet-stream",
            headers={
                "Content-Range":
                    f"bytes {start}-{end}/{size}",
                "Accept-Ranges": "bytes",
                "Content-Length":
                    str(end - start + 1),
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Expose-Headers":
                    "Content-Range,Accept-Ranges,Content-Length",
                "Cache-Control":
                    "public, max-age=120"
            }
        )
