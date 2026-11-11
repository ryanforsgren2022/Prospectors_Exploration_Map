import asyncio
from fastapi import HTTPException
from aem_vm_discovery_v2 import registered_mbtiles_tile

FILES = {
    "boundary": "boundary",
    "claims": "claims",
    "surface-management": "surfaceManagement",
    "withdrawals-authorized": "withdrawalsAuthorized",
    "withdrawals-pending": "withdrawalsPending",
}

def install(app):
    @app.get("/ut/layers/{kind}/{z}/{x}/{y}.pbf")
    async def utah_tile(kind: str, z: int, x: int, y: int):
        if kind not in FILES:
            raise HTTPException(404)
        return await asyncio.to_thread(
            registered_mbtiles_tile,
            "ut",
            FILES[kind],
            z,
            x,
            y
        )
