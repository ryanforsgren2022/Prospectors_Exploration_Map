# VM backend handoff

Prepared 2026-10-24. Local implementation is complete. Production is unchanged.

## Worker objective

Validate the prepared backend against the DigitalOcean VM, report the results, and stop before deployment unless the user gives separate deployment/restart approval. Do not move or delete MBTiles, do not upload parcels to R2, and do not create hiccup logs.

Canonical configured root:

```text
/root/arizona-naip-build/live-mvt/data
```

The audit says that path resolves to:

```text
/root/LIVE_SITE_CASHE/live-mvt/data
```

Resolve it again on the VM; do not assume the audit snapshot is still current.

## Prepared runtime files

These files form one backend change set and must be staged together:

```text
vm-review/aem_vm_discovery_v2.py
vm-review/aem_claims_classification.py
vm-review/aem_utah_layers.py
vm-review/parcels_service.py
vm-review/western-datasets.json
```

Read-only VM validation tools:

```text
vm-review/verify_backend_integration.py
vm-review/audit_claim_classifications.py
vm-review/verify_montana_archives.py
```

What the change set does:

- Registers 117 reviewed dataset groups from 98 archives across all 11 states.
- Preserves every registered PLSS sublayer and each archive's actual source-layer ID, zoom range, and bounds.
- Uses the dedicated Arizona township archive without rendering the combined township source twice.
- Keeps Idaho `claimsBlmLands` distinct from absent authoritative statewide claims.
- Selects `mt/claims/mt-claims.mbtiles`; no runtime code requires the historical duplicate filename.
- Filters claim features by normalized `CSE_DISP`: every named value except `Closed` is retained. Missing, null, blank, and invalid values are reported separately and omitted, never labeled Active.
- Applies that rule to discovery tile routes and the older Arizona and Utah compatibility routes.
- Understands both reviewed current archive paths and proposed standardized paths. If both exist, a standardized path wins only when it is the same filesystem object as the reviewed source; otherwise the reviewed current path remains selected. The two occupied Washington destinations are recorded as `canonicalPathBlocked`, not runtime candidates, so the excluded files cannot displace statewide BLM data.
- Leaves roads and historic mines on R2. Parcels remain on the VM and remain last in discovery/frontend ordering.

## Stage from the Chromebook

These commands create a separate staging directory; they do not alter the running service:

```bash
cd ~/Prospectors_Exploration_Map
ssh aem-vm 'install -d -m 700 /root/aem-backend-remediation-20261024'
scp \
  vm-review/aem_vm_discovery_v2.py \
  vm-review/aem_claims_classification.py \
  vm-review/aem_utah_layers.py \
  vm-review/parcels_service.py \
  vm-review/western-datasets.json \
  vm-review/verify_backend_integration.py \
  vm-review/audit_claim_classifications.py \
  vm-review/verify_montana_archives.py \
  aem-vm:/root/aem-backend-remediation-20261024/
```

## Read-only VM preflight

Run on the VM from the staging directory:

```bash
cd /root/aem-backend-remediation-20261024
readlink -f /root/arizona-naip-build/live-mvt/data
df -h /root/arizona-naip-build/live-mvt/data
python3 -m py_compile \
  aem_vm_discovery_v2.py \
  aem_claims_classification.py \
  aem_utah_layers.py \
  parcels_service.py \
  verify_backend_integration.py \
  audit_claim_classifications.py \
  verify_montana_archives.py
python3 verify_backend_integration.py \
  --data-root /root/arizona-naip-build/live-mvt/data \
  --registry /root/aem-backend-remediation-20261024/western-datasets.json
```

`verify_backend_integration.py` is read-only. PASS requires 11 states, 117 registrations, and 117 representative tile-handler requests. It additionally verifies the two statewide Washington BLM selections, the dedicated Arizona township archive, Idaho's BLM-only scope, and the canonical Montana registration. It prints JSON to stdout and writes nothing.

Run the full classification count separately because it scans every stored claim tile and can take substantially longer:

```bash
cd /root/aem-backend-remediation-20261024
python3 audit_claim_classifications.py \
  --audit /root/aem-data-audit/20261024-203228/mbtiles-audit.json \
  --registry /root/aem-backend-remediation-20261024/western-datasets.json
```

The count unit is tile-feature occurrences across tiles and zooms, not distinct legal claims. For every measured archive verify:

```text
before = after + closed + unknown
```

Report each state's normalized `byClassification`, `afterByClassification`, `closed`, and `unknownReasons` independently. Do not combine competing archives into a statewide total. Idaho must be labeled BLM-lands-only.

Montana equivalence check, still read-only:

```bash
cd /root/aem-backend-remediation-20261024
python3 verify_montana_archives.py
```

Do not delete either Montana file during this handoff. Record the exact SHA-256 digest if the result is `IDENTICAL`.

## Inspect the running dependency before any deployment

Use read-only commands and report exact results:

```bash
pgrep -af 'uvicorn|gunicorn|parcels_service|aem_vm_discovery'
systemctl list-units --type=service --all | grep -Ei 'aem|parcel|mvt|tile|uvicorn|gunicorn'
find /etc/systemd/system /lib/systemd/system -maxdepth 2 -type f \
  -exec grep -IlE 'parcels_service|live-mvt|uvicorn|gunicorn' {} + 2>/dev/null
rg -n --glob '*.py' --glob '*.json' --glob '*.service' \
  'montana-claims-active|mt-claims|western-datasets|aem_vm_discovery' \
  /root/LIVE_SITE_CASHE/live-mvt /etc/systemd/system
find /root/arizona-naip-build/live-mvt/data/mt/claims \
  -maxdepth 1 \( -type l -o -type f \) -printf '%y %i %n %p -> %l\n'
```

For every candidate service unit, run `systemctl cat UNIT` and `systemctl show UNIT -p FragmentPath -p ExecStart -p WorkingDirectory -p User`. Confirm the actual source directory and Python environment. Also check open references:

```bash
lsof /root/arizona-naip-build/live-mvt/data/mt/claims/mt-claims.mbtiles \
     /root/arizona-naip-build/live-mvt/data/mt/claims/montana-claims-active.mbtiles 2>/dev/null
```

The prepared entrypoint is `parcels_service.py`. If the active unit instead starts `parcels_service_nv_plss_candidate.py` or another entrypoint, report `BLOCKED` and reconcile that source before deployment; do not substitute or overwrite it automatically.

## Approval-gated deployment phase

Do not perform this phase merely because preflight passes. It requires explicit user approval to update production files and restart the identified service.

Before copying, preserve the currently installed Python/JSON files in a new timestamped backup directory outside the data tree, then compare the staged and installed files. Copy all five runtime files as one coordinated change. Do not touch any MBTiles archive. Run `python3 -m py_compile` in the actual service environment before restart. Restart only the exact unit established by the dependency inspection; never guess a service name.

After an approved restart, validate:

```bash
curl -fsS https://tiles.americanexplorationmaps.com/api/states/discover-v2
curl -sS -D - -o /dev/null \
  https://tiles.americanexplorationmaps.com/api/vm-data/az/claims/6/11/24.pbf
curl -sS -D - -o /dev/null \
  https://tiles.americanexplorationmaps.com/api/vm-data/id/claimsBlmLands/8/42/90.pbf
curl -sS -D - -o /dev/null \
  https://tiles.americanexplorationmaps.com/api/vm-data/mt/claims/6/13/23.pbf
```

Use tile coordinates returned by `verify_backend_integration.py` if any example above is empty or outside current coverage. Claims responses must expose the `X-AEM-Claims-*` headers. Confirm discovery still returns all available PLSS sublayers and that `roads` and `historicMines` are absent from VM registrations.

## Work intentionally left separate

- Do not execute the 32-path MBTiles naming migration. The two Washington standardized destinations remain occupied by excluded, uniqueness-unverified files.
- Do not move or delete either excluded Washington archive.
- Do not delete the Montana duplicate in this handoff.
- Do not rebuild MBTiles.
- Do not upload parcels, roads, or historic mines.
- Do not modify R2 objects.

## Known data gaps, not backend failures

- No claims MBTiles were found for Colorado, Nevada, or Wyoming.
- Idaho has BLM-lands-only claims and lacks an authoritative statewide archive.
- Arizona boundary exists but lacks the metadata required for reviewed registration.
- Nevada boundary and surface management and Oregon surface management were absent from the supplied audit.
- Oregon and Wyoming have the PLSS gaps recorded in `docs/western-prospectors-checklist.md`.
- Actual production claim counts remain BLOCKED until the VM scanner completes.

## Local evidence

Local validation passed 23 Python tests plus the frontend integration suite. The tests exercised every registration, both Washington collision behaviors, the Arizona/Idaho/Montana decisions, classification normalization and unknown handling, the Utah compatibility route, storage safety, and the standalone VM verifier. FastAPI was unavailable locally, so route tests called the actual handlers through a response/decorator shim; ASGI and public HTTP transport remain VM validation items.
