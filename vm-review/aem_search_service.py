import asyncio
import json
import re
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/search", tags=["AEM Search"])

BASE = Path("/root/arizona-naip-build/live-mvt/data")
NV_CLAIMS = Path(
    "/root/nevada-build/source/mining-claims/not-closed/"
    "nevada-mining-claims-not-closed.gpkg"
)

def dataset(state, kind):
    if state == "nv" and kind in ("townships", "sections"):
        return (
            BASE / "nv" / "plss" /
            f"nevada-plss-{kind}.gpkg",
            f"nevada_plss_{kind}"
        )
    if state == "nv" and kind == "claims":
        return NV_CLAIMS, "nevada_mining_claims"
    raise HTTPException(404, "Search dataset not registered")

def first_feature(path, layer, where):
    if not path.is_file():
        raise HTTPException(503, "Search data unavailable")

    args = [
        "ogr2ogr", "-f", "GeoJSON",
        "/vsistdout/", str(path), layer,
        "-where", where,
        "-limit", "1",
        "-t_srs", "EPSG:4326"
    ]

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=25,
            check=True
        )
        features = json.loads(result.stdout).get("features", [])
    except (subprocess.SubprocessError, ValueError) as error:
        raise HTTPException(503, "Search query failed") from error

    return features[0] if features else None

async def lookup(path, layer, where):
    return await asyncio.to_thread(
        first_feature, path, layer, where
    )

@router.get("/{state}/plss")
async def search_plss(
    state: str,
    township: int = Query(ge=1, le=999),
    township_dir: str = Query(pattern="^[NS]$"),
    range_num: int = Query(ge=1, le=999),
    range_dir: str = Query(pattern="^[EW]$"),
    section: int | None = Query(default=None, ge=1, le=36)
):
    state = state.lower()
    township_dir = township_dir.upper()
    range_dir = range_dir.upper()

    path, layer = dataset(state, "townships")
    where = (
        f"CAST(TWNSHPNO AS INTEGER) = {township} "
        f"AND TWNSHPDIR = '{township_dir}' "
        f"AND CAST(RANGENO AS INTEGER) = {range_num} "
        f"AND RANGEDIR = '{range_dir}'"
    )

    feature = await lookup(path, layer, where)

    if not feature:
        raise HTTPException(404, "Township not found")

    if section is not None:
        plssid = str(feature.get("properties", {}).get("PLSSID", ""))
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", plssid):
            raise HTTPException(503, "Invalid township identifier")

        path, layer = dataset(state, "sections")
        feature = await lookup(
            path, layer,
            f"PLSSID = '{plssid}' "
            f"AND CAST(FRSTDIVNO AS INTEGER) = {section}"
        )
        if not feature:
            raise HTTPException(404, "Section not found")

    return {
        "type": "FeatureCollection",
        "features": [feature],
        "state": state
    }

@router.get("/{state}/claims")
async def search_claims(
    state: str,
    value: str = Query(min_length=2, max_length=60)
):
    state = state.lower()
    path, layer = dataset(state, "claims")

    value = value.strip().upper()
    if not re.fullmatch(r"[A-Z0-9 \-]{2,60}", value):
        raise HTTPException(400, "Invalid claim search")

    escaped = value.replace("'", "''")
    compact = re.sub(r"\s+", "", escaped)

    where = (
        f"UPPER(CSE_NR) = '{compact}' OR "
        f"UPPER(CSE_NAME) = '{escaped}' OR "
        f"UPPER(LEG_CSE_NR) = '{compact}'"
    )

    feature = await lookup(path, layer, where)

    if not feature:
        raise HTTPException(404, "Claim not found")

    return {
        "type": "FeatureCollection",
        "features": [feature],
        "state": state
    }
