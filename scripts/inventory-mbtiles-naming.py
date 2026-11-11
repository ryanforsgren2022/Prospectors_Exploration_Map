"""Prepare documentation/manifests only; no archive or backend changes."""
import csv
import hashlib
import importlib.util
import json
import re
import shlex
import sys
from collections import Counter, defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / 'vm-review'))
from aem_archive_paths import STATES, canonical_relative_path

ROOT = '/root/arizona-naip-build/live-mvt/data'


def main():
    audit = json.loads((BASE / 'vm-review/mbtiles-audit.json').read_text())
    registry = json.loads((BASE / 'vm-review/western-datasets.json').read_text())
    analysis = json.loads((BASE / 'docs/western-audit-analysis.json').read_text())
    physical = Path(audit['canonical_data_root'])
    selected = defaultdict(list)
    for state, configuration in registry['states'].items():
        for group, spec in configuration['datasets'].items():
            selected[str(physical / spec['path'])].append((state, group))
    identities = defaultdict(list)
    competing = defaultdict(list)
    records = {record['real_path']: record for record in audit['archives']}
    for record in audit['archives']:
        identities[record.get('file_identity', record['real_path'])].append(record['path'])
        path = Path(record['real_path'])
        if path.is_relative_to(physical):
            state = path.relative_to(physical).parts[0]
            if not re.search(r'/staging/|/parts/|invalid|building|\.tmp\.', record['path'], re.I):
                for layer in record['source_layers']:
                    competing[state, layer].append(record['path'])
    # Use the same real source-layer vocabulary as the prior audit preparation.
    import importlib.util
    spec = importlib.util.spec_from_file_location('integration', BASE / 'scripts/prepare-western-integration.py')
    integration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(integration)
    layer_groups = {**integration.LAYER_GROUPS,
                    'state_routes': 'stateRoutes', 'historic_mines': 'historicMines',
                    'historic_mines_points': 'historicMines'}
    rows = []
    migrations = []
    for index, record in enumerate(audit['archives'], 1):
        old = Path(record['real_path'])
        inside = old.is_relative_to(physical)
        components = old.parts
        state = old.relative_to(physical).parts[0] if inside else next((v for v in components if v in STATES), None)
        if state is None:
            state = next((code for token, code in [('colorado-build', 'co'), ('utah-build', 'ut'), ('nevada-build', 'nv'), ('california-boundary-build', 'ca')]
                          if any(token in part for part in components)), None)
        if state is None and 'western-withdrawals' in old.name:
            state = 'western'  # Regional source: do not fabricate a per-state rename.
        groups = sorted({layer_groups[layer] for layer in record['source_layers'] if layer in layer_groups})
        registration = selected.get(str(old), [])
        selected_groups = [group for _, group in registration]
        identity_aliases = [p for p in identities[record.get('file_identity', record['real_path'])] if p != record['path']]
        scope = 'selected-local-registry' if registration else 'unselected-canonical-root' if inside else 'outside-canonical-root'
        if re.search(r'/staging/|/parts/|/rejected/|building|\.tmp\.|invalid', str(old), re.I):
            scope = 'build-staging-rejected-or-incomplete'
        if 'historicMines' in groups:
            scope = 'retained-VM-historic-source; frontend-is-R2'
        proposed_relative = None
        if state and groups:
            try:
                proposed_relative = canonical_relative_path(state, selected_groups or groups)
            except ValueError:
                pass
        # Scope must not disappear when normalizing a misleading filename.
        if state == 'id' and 'claims' in groups:
            proposed_relative = canonical_relative_path('id', ['claimsBlmLands'])
        target = str(Path(ROOT) / proposed_relative) if proposed_relative else None
        target_physical = str(physical / proposed_relative) if proposed_relative else None
        collision = records.get(target_physical)
        collision = collision if collision and collision.get('file_identity') != record.get('file_identity') else None
        routes = [f'/api/vm-data/{st}/{group}/{{z}}/{{x}}/{{y}}.pbf' for st, group in registration]
        duplicate = 'No content equivalence established'
        if identity_aliases:
            duplicate = 'Same inode/path aliases: ' + '; '.join(identity_aliases)
        if state == 'mt' and old.name in ('mt-claims.mbtiles', 'montana-claims-active.mbtiles'):
            duplicate = 'SHA-256 identical + integrity PASS reported by user; digest/live dependency recheck unavailable'
        alternatives = sorted({p for layer in record['source_layers'] for p in competing.get((state, layer), [])
                               if p != record['path'] and p not in identity_aliases})
        action = 'RETAIN; not a selected migration source'
        if registration:
            action = 'UNCHANGED' if target_physical == str(old) else 'PLAN ONLY; preserve old path'
            if collision:
                action = 'BLOCKED: proposed destination occupied by different file identity'
        row = {
            'id': index, 'state': state, 'currentFilename': old.name,
            'oldPath': str(old), 'auditPath': record['path'], 'scope': scope,
            'datasetGroups': selected_groups or groups, 'sourceLayers': record['source_layers'],
            'proposedFilename': Path(proposed_relative).name if proposed_relative else None,
            'proposedCanonicalPath': target,
            'namingBlocker': None if target else ('Regional aggregate retained; no per-state rename' if state == 'western' else 'Source metadata/state must be verified before proposing a production name'),
            'newPath': target if registration else str(old), 'action': action,
            'duplicates': duplicate, 'sameLayerAlternativesNotProvenDuplicates': alternatives,
            'backendReferences': ('Prepared local registry and unchanged discovery route' if registration
                                  else 'No selected local runtime registration'),
            'discoveryRoutes': routes, 'auditErrors': record['errors'],
            'sha256': None, 'sha256Status': 'Not measured: source archives unavailable locally',
            'fileIdentity': record.get('file_identity'), 'bytes': record['bytes'],
            'destinationCollision': collision['path'] if collision else None,
        }
        rows.append(row)
        if registration:
            change = target_physical != str(old)
            commands = None
            if change and not collision:
                # These are proposals in JSON, never executed by this script.
                commands = {
                    'preconditions': ['approved coordinated deployment', 'live service/dependency/symlink inventory complete',
                                      'source stable, SQLite integrity PASS, full SHA256 recorded',
                                      'destination absent; no overwrites; free-space/device check passed'],
                    'checkFreeSpace': f'df -P -- {shlex.quote(ROOT)}',
                    'prepareDirectory': f'mkdir -p -- {shlex.quote(str(Path(target).parent))}',
                    'sameFilesystemHardLink': f'ln -- {shlex.quote(str(old))} {shlex.quote(target)}',
                    'copyAlternativeDoNotRunBoth': f'cp --no-clobber --preserve=all --reflink=auto -- {shlex.quote(str(old))} {shlex.quote(target)}',
                    'verifyBothSha256': f'sha256sum -- {shlex.quote(str(old))} {shlex.quote(target)}',
                    'verifySameInodeForLink': f'stat -Lc "%d:%i %s %n" -- {shlex.quote(str(old))} {shlex.quote(target)}',
                }
            migrations.append({**row, 'proposedCommandsDoNotExecute': commands,
                               'rollback': {'restoreArchiveReferencesTo': str(old), 'retainNewPath': target,
                                            'deleteNothing': True, 'restartOrDeployAutomatically': False}})
    assert len(rows) == audit['archive_count'] == 168
    assert set(registry['states']) == STATES
    assert all(r['state'] for r in rows), 'State/region assignment incomplete'
    for row in migrations:
        relative = Path(row['newPath']).relative_to(ROOT).as_posix()
        assert re.fullmatch(r'[a-z]{2}/[a-z-]+/tiles/[a-z]{2}-[a-z-]+\.mbtiles', relative)
        assert Path(row['newPath']).name.startswith(row['state'] + '-')
    assert all(path in records for path in selected), 'Registry source absent from audit'
    targets = defaultdict(set)
    for row in migrations:
        targets[row['newPath']].add(row['oldPath'])
    assert all(len(sources) == 1 for sources in targets.values()), 'Selected sources collide with each other'
    document = {
        'status': 'FINAL LOCAL PLAN; backend compatibility prepared; no live migration or deployment performed',
        'configuredRoot': ROOT, 'auditResolvedRoot': str(physical),
        'liveRootAndSymlinkCheck': 'BLOCKED: VM SSH unavailable; audit resolution is historical evidence only',
        'naming': '{state}/{dataset}/tiles/{state}-{dataset}.mbtiles; PLSS under plss/tiles with plss-{sublayer}',
        'auditInputSha256': hashlib.sha256((BASE / 'vm-review/mbtiles-audit.json').read_bytes()).hexdigest(),
        'inventoryRecordCount': len(rows), 'selectedArchiveCount': len(migrations),
        'distinctAuditedFileIdentities': len(identities),
        'sameFileAliasGroups': [values for values in identities.values() if len(values) > 1],
        'knownContentDuplicate': 'Montana pair: user-confirmed matching SHA-256/integrity; numeric digests unavailable',
        'allArchives': rows, 'selectedArchiveMigrations': migrations,
        'livePreflight': ['resolve symlinks strictly; compare resolved paths', 'inventory all active service/config references',
                         'inspect symlinks, link counts, open file descriptors and writers',
                         'SHA256 and SQLite integrity for each source and existing target',
                         'verify discovery and representative tile payloads before/after approved switch',
                         'preserve old paths and source-layer names; rollback references without deleting files'],
    }
    (BASE / 'docs/mbtiles-path-manifest.json').write_text(json.dumps(document, indent=2) + '\n')
    with (BASE / 'docs/mbtiles-inventory.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value) if isinstance(value, (list, dict)) else value for key, value in row.items()})
    lines = ['# Uniform MBTiles naming plan', '',
             '**Inventory snapshot, not a live production census.** The supplied audit contains 168 path records across 11 states. '
             f'The current local registry selects {len(migrations)} physical archive paths. Local backend compatibility is prepared. '
             'Live service, symlink and SHA-256 checks are blocked by VM access.', '',
             'Use `/root/arizona-naip-build/live-mvt/data/{state}/{dataset}/tiles/{state}-{dataset}.mbtiles`. '
             'The audit resolved that root to `/root/LIVE_SITE_CASHE/live-mvt/data`. PLSS uses the `plss` directory and '
             '`{state}-plss-{sublayer}.mbtiles`; keep combined sources as `{state}-plss.mbtiles`. '
             'Combined withdrawals use `{state}-withdrawals.mbtiles`. Idaho BLM-only claims use '
             '`claims-blm-lands/tiles/id-claims-blm-lands.mbtiles`, separately from statewide `claims`.', '',
             'Static roads and historic mines stay in R2 as PMTiles. Existing VM historic-source MBTiles are inventoried and retained, '
             'not migrated into the production frontend plan. Parcels remain on the VM.', '',
             '## All-state summary', '',
             '| State | Selected archives | Filename changes | Directory-only changes | Destination conflicts |',
             '| --- | ---: | ---: | ---: | ---: |']
    for state in 'az ca co id mt nm nv or ut wa wy'.split():
        subset = [r for r in migrations if r['state'] == state]
        names = sum(r['currentFilename'] != r['proposedFilename'] for r in subset)
        dirs = sum(r['currentFilename'] == r['proposedFilename'] and r['action'] != 'UNCHANGED' for r in subset)
        blocks = sum(bool(r['destinationCollision']) for r in subset)
        lines.append(f'| {state.upper()} | {len(subset)} | {names} | {dirs} | {blocks} |')
    lines += ['', '## Selected files needing standardization', '',
              'Paths below are relative to the data root. This table includes filename and directory changes; unchanged selected '
              'archives and every unselected/build/outside path are included in the complete CSV and manifest.', '',
              '| State | Current path | Proposed path | Source layer(s) | Status |',
              '| --- | --- | --- | --- | --- |']
    for row in migrations:
        if row['action'] != 'UNCHANGED':
            lines.append(f"| {row['state'].upper()} | `{Path(row['oldPath']).relative_to(physical)}` | "
                         f"`{Path(row['newPath']).relative_to(ROOT)}` | {', '.join(row['sourceLayers'])} | "
                         f"{'BLOCKED: occupied target' if row['destinationCollision'] else 'Plan only'} |")
    lines += ['', '## Duplicates and conflicts', '',
              '- Same-file identity groups are aliases/hard links, not proven redundant physical copies. All 13 groups remain unchanged.',
              '- Montana’s two claims files are user-confirmed content duplicates. The canonical selection is `mt-claims.mbtiles`; '
              'the new proposed location adds `claims/tiles/`. No deletion occurred. Live dependencies and an immediate rehash remain prerequisites.',
              '- Washington’s statewide BLM government-lots and quarter-quarter archives propose filenames currently occupied by '
              'smaller alternate-source archives whose uniqueness is unverified. They are not deletable duplicates. Both targets are blocked. '
              'Keep statewide BLM selections and physically retain the excluded files; any future path switch requires dependency review.',
              '- Shared source layers in Arizona, Nevada and Utah do not establish duplicate content. Combined archives remain intact; '
              'no splitting or rebuilding is proposed. No SHA equality is inferred from matching metadata, size, date or layer IDs.', '',
              '## Manifest, commands and rollback', '',
              '- [Complete inventory CSV](mbtiles-inventory.csv): all 168 records with filename, dataset/source layers, proposed filename, '
              'aliases/competitors, prepared backend-reference status, and known local discovery routes.',
              '- [Old-to-new manifest](mbtiles-path-manifest.json): every audited record plus one migration entry per selected archive. '
              'Unselected sources have identity old→new mappings (retain in place). Staging/rejected files are not promoted.',
              '- Commands are inert strings in the manifest. They require approved deployment, live dependency/symlink checks, integrity/SHA '
              'verification, absence of the destination, and free-space/device checks. Prefer same-filesystem hard links to preserve old paths; '
              'a no-clobber byte-copy alternative requires enough disk space and matching SHA-256 afterward. Do not execute both alternatives.',
              '- No commands are supplied for an occupied destination. No overwrite, unlink, removal, move, service restart or deployment command '
              'is generated. Rollback restores old references and retains both paths; it deletes nothing.', '',
              '## Validation and limits', '',
              'The generator checked 168/168 records, all 11 states, every selected source against the audit, canonical naming syntax, and '
              'unique destinations among selected sources. Existing destination collisions are explicitly blocked. Source-layer IDs and '
              'attributes are only recorded; no MBTiles were opened, changed, rebuilt, renamed, copied or deleted. Live archive SHA-256 '
              'and current production status cannot be established from this snapshot. Dataset absence is reported separately in the '
              'state/layer checklist; a naming difference is not a missing dataset. Backend compatibility is prepared locally; deployment is pending.', '']
    (BASE / 'docs/mbtiles-naming-plan.md').write_text('\n'.join(lines))
    print(json.dumps({'auditedPaths': len(rows), 'selectedArchivePaths': len(migrations),
                      'standardizationNeeded': sum(r['action'] != 'UNCHANGED' for r in migrations),
                      'occupiedTargets': sum(bool(r['destinationCollision']) for r in migrations),
                      'liveChanges': False}))


if __name__ == '__main__':
    # Preserve final exclusions even when callers use the original inventory CLI.
    specification = importlib.util.spec_from_file_location(
        'final_storage_plan', BASE / 'scripts/finalize-mbtiles-plan.py')
    finalizer = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(finalizer)
    finalizer.main()
