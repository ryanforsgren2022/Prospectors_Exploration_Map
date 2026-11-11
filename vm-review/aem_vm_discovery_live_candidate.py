
import gzip
import json
import os
import re
import sqlite3
import struct
import time
from pathlib import Path
from aem_claims_classification import filter_claim_tile
from pmtiles.reader import Reader

from fastapi import HTTPException, Response, Request
from starlette.responses import StreamingResponse

DATA = Path(__file__).resolve().parent / "data"
HOST = "https://tiles.americanexplorationmaps.com"

ROAD_STATES = frozenset((
    "az", "ca", "co", "id", "mt", "nm",
    "nv", "or", "ut", "wa", "wy"
))

GROUPS = {
    "boundary": ("state_boundary", "boundary"),
    "claims": ("claims", "claims_not_closed", "mining_claims"),
    "surfaceManagement": ("surface_management",),
    "historicMines": ("historic_mines", "historic-mines"),
    "parcels": ("parcels",),
    "plssTownships": ("plss_townships", "nm_plss_townships"),
    "plssSections": ("plss_sections", "plss_first_division", "nm_plss_sections"),
    "plssGovernmentLots": ("plss_government_lots",),
    "plssSpecialSurveys": ("plss_special_surveys", "nm_plss_special-surveys"),
    "plssQuarterSections": ("plss_quarter_sections",),
    "plssQuarterQuarterSections": ("plss_quarter_quarter", "plss_quarter_quarter_sections"),
    "plssSurveyPoints": ("plss_survey_points", "nm_plss_survey-points"),
}

# Shared display thresholds for the detailed PLSS groups.
PLSS_DETAIL_MINZOOM = {
    "plssQuarterSections": 11,
    "plssQuarterQuarterSections": 12,
    "plssSurveyPoints": 12,
}

EXCLUDED = {
    "staging", "backups", "backup", "tmp", "temp",
    "raw", "parts", "intermediate", "archive",
    "archives", "cache"
}

CACHE_TIME = 0
CACHE_DATA = None


def archive_metadata(path):
    try:
        stat = path.stat()

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
            "format": path.suffix
        }

    except (
        OSError, sqlite3.Error, ValueError,
        TypeError, KeyError, EOFError
    ):
        return None


def discover_vm_data():
    global CACHE_TIME, CACHE_DATA

    if (
        CACHE_DATA is not None
        and time.monotonic() - CACHE_TIME < 20
    ):
        return CACHE_DATA

    states = {}
    paths = {}

    if not DATA.is_dir():
        return states, paths

    for folder in sorted(DATA.iterdir()):
        code = folder.name.lower()

        if (
            not folder.is_dir()
            or not re.fullmatch("[a-z]{2}", code)
        ):
            continue

        manifest = folder / "state.json"

        if not manifest.is_file():
            continue

        try:
            original = json.loads(
                manifest.read_text()
            )

            bounds = original["bounds"]

            if (
                not isinstance(bounds, list)
                or len(bounds) != 4
                or not all(
                    isinstance(x, (int, float))
                    for x in bounds
                )
            ):
                continue

        except (
            OSError, ValueError, KeyError, TypeError
        ):
            continue

        archives = []

        for current, directories, files in os.walk(
            folder, followlinks=False
        ):
            directories[:] = [
                name for name in directories
                if name.lower() not in EXCLUDED
                and not name.startswith(".")
                and not (
                    Path(current) / name
                ).is_symlink()
            ]

            for filename in files:
                lower = filename.lower()

                if not lower.endswith(
                    (".mbtiles", ".pmtiles")
                ):
                    continue

                if "road" in lower or "route" in lower:
                    continue

                path = Path(current) / filename

                if path.is_symlink():
                    continue

                metadata = archive_metadata(path)

                if metadata:
                    archives.append(metadata)

        def select(layer_names):
            matches = [
                archive for archive in archives
                if any(
                    name in archive["layers"]
                    for name in layer_names
                )
            ]

            return max(
                matches,
                key=lambda item: (
                    item["maxzoom"],
                    item["format"] == ".pmtiles",
                    item["path"].stat().st_mtime
                ),
                default=None
            )

        datasets = {}

        def publish(group, archive, layer):
            paths[(code, group)] = {**archive, "sourceLayer": layer}

            url = (
                HOST
                + "/api/vm-data/"
                + code
                + "/"
                + group
            )

            entry = {
                "minzoom": max(archive["minzoom"], PLSS_DETAIL_MINZOOM.get(group, 0)),
                "maxzoom": archive["maxzoom"],
                "sourceLayer": layer,
                "layer": layer
            }

            if group in ("claims", "claimsBlmLands"):
                entry["semantics"] = "notClosed"
                entry["classificationFilter"] = {"rule": "notClosed", "field": "CSE_DISP", "normalization": "unicode-whitespace-casefold", "unknownPolicy": "report-separately"}
                entry["tiles"] = [url + "/{z}/{x}/{y}.pbf"]
            elif archive["format"] == ".pmtiles":
                entry["url"] = (
                    "pmtiles://" + url + ".pmtiles"
                )
            else:
                entry["tiles"] = [
                    url + "/{z}/{x}/{y}.pbf"
                ]

            return entry

        for group, names in GROUPS.items():
            archive = select(names)

            # Some published claim packages use a different
            # vector-layer name from the legacy registry.
            if group == "claims" and archive is None:
                candidates = [
                    item for item in archives
                    if item["path"].name.lower() == "claims.pmtiles"
                    and item["layers"]
                ]
                archive = max(
                    candidates,
                    key=lambda item: (
                        item["maxzoom"],
                        item["path"].stat().st_mtime
                    ),
                    default=None
                )

            if not archive:
                continue

            layer = next(
                (
                    name for name in names
                    if name in archive["layers"]
                ),
                None
            )

            if group == "claims" and not layer:
                old_claims = (
                    original.get("datasets") or {}
                ).get("claims") or {}

                preferred = old_claims.get("sourceLayer")

                if preferred in archive["layers"]:
                    layer = preferred
                else:
                    matching = [
                        name for name in archive["layers"]
                        if "claim" in name.lower()
                    ]

                    if len(matching) == 1:
                        layer = matching[0]
                    elif len(archive["layers"]) == 1:
                        layer = archive["layers"][0]

            if layer:
                datasets[group] = publish(
                    group, archive, layer
                )

        authorized = select(
            ("withdrawals_authorized",)
        )

        pending = select(
            ("withdrawals_pending",)
        )

        if (
            authorized
            and "withdrawals_pending"
            in authorized["layers"]
        ):
            entry = publish(
                "withdrawals",
                authorized,
                "withdrawals_authorized"
            )

            entry["authorizedLayer"] = (
                "withdrawals_authorized"
            )
            entry["pendingLayer"] = (
                "withdrawals_pending"
            )

            datasets["withdrawals"] = entry

        elif authorized and pending:
            datasets["withdrawals"] = {
                "authorized": publish(
                    "withdrawalsAuthorized",
                    authorized,
                    "withdrawals_authorized"
                ),
                "pending": publish(
                    "withdrawalsPending",
                    pending,
                    "withdrawals_pending"
                )
            }

        # Retain state metadata, but exclude legacy
        # R2 base URLs and old dataset file mappings.
        state = {
            key: value
            for key, value in original.items()
            if key not in ("base", "datasets")
        }

        state["datasets"] = datasets
        states[code] = state

    CACHE_TIME = time.monotonic()
    CACHE_DATA = (states, paths)

    return CACHE_DATA


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
        archive = discover_vm_data()[1].get(
            (state, group)
        )

        if (
            not archive
            or (archive["format"] != ".mbtiles" and group != "claims")
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
            if archive["format"] == ".pmtiles":
                with archive["path"].open("rb") as stream:
                    def read_range(offset, length):
                        stream.seek(offset)
                        return stream.read(length)
                    data = Reader(read_range).get(z, x, y)
                    result = (data,) if data is not None else None
            else:
                db = sqlite3.connect(
                    "file:" + str(archive["path"]) + "?mode=ro&immutable=1",
                    uri=True, timeout=3
                )
                try:
                    result = db.execute(
                        "SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                        (z, x, (1 << z) - 1 - y)
                    ).fetchone()
                finally:
                    db.close()
        except (sqlite3.Error, OSError, ValueError, EOFError, struct.error):
            raise HTTPException(503)

        headers = {
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=120"
        }

        if not result:
            return Response(
                status_code=204,
                headers=headers
            )

        tile = result[0]
        if group == "claims":
            try:
                tile, counts = filter_claim_tile(tile, archive["sourceLayer"], "CSE_DISP")
            except (ValueError, OSError, UnicodeError, EOFError, struct.error) as error:
                raise HTTPException(503, "Claims classification failed") from error
            headers.update({
                "X-AEM-Claims-Before": str(counts["before"]),
                "X-AEM-Claims-After": str(counts["after"]),
                "X-AEM-Claims-Closed": str(counts["closed"]),
                "X-AEM-Claims-Unknown": str(counts["unknown"]),
                "Access-Control-Expose-Headers": "X-AEM-Claims-Before, X-AEM-Claims-After, X-AEM-Claims-Closed, X-AEM-Claims-Unknown"
            })

        if tile[:2] == b"\x1f\x8b":
            headers["Content-Encoding"] = "gzip"

        return Response(
            tile,
            media_type="application/x-protobuf",
            headers=headers
        )

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
