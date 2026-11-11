"""Finalize preservation-first storage plan. Documentation only; never migrates data."""
import csv
import hashlib
import importlib.util
import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


def main():
    spec = importlib.util.spec_from_file_location('inventory', BASE / 'scripts/inventory-mbtiles-naming.py')
    inventory = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inventory)
    inventory.main()
    path = BASE / 'docs/mbtiles-path-manifest.json'
    manifest = json.loads(path.read_text())
    oldroot, newroot = Path(manifest['auditResolvedRoot']), Path(manifest['configuredRoot'])
    excluded = []
    comparisons = []
    audit = json.loads((BASE / 'vm-review/mbtiles-audit.json').read_text())
    records = {r['real_path']: r for r in audit['archives']}
    for row in manifest['selectedArchiveMigrations']:
        row.pop('proposedCommandsDoNotExecute', None)
        if not row['destinationCollision']:
            continue
        oldpartial = row['destinationCollision']
        partial = next(r for r in manifest['allArchives'] if r['oldPath'] == oldpartial)
        excluded.append({**partial, 'scope': 'EXCLUDED — UNIQUENESS UNVERIFIED',
                         'newPath': oldpartial, 'proposedCanonicalPath': None,
                         'action': 'RETAIN PHYSICAL FILE UNCHANGED; no migration registration',
                         'deletionEligible': False})
        row.update({'destinationConflictDecision': 'Use statewide BLM only; physical target remains occupied by excluded file',
                    'destinationCollision': 'excluded-file-at-canonical-target',
                    'action': 'BLOCKED: excluded physical file still occupies canonical target'})
        for source in manifest['allArchives']:
            if source['oldPath'] == row['oldPath']:
                source['action'] = row['action']
                source['destinationCollision'] = row['destinationCollision']
        original = records[oldpartial]
        blm = records[row['oldPath']]
        def description(record):
            metadata = json.loads(record['metadata']['json'])
            layer = metadata['vector_layers'][0]
            stats = metadata['tilestats']['layers'][0]
            return {'path': record['real_path'], 'sourceLayer': layer['id'],
                    'auditReportedFeatureCount': stats['count'], 'bounds': record['metadata']['bounds'],
                    'fields': layer['fields'],
                    'provenance': {v['attribute']: v.get('values') for v in stats['attributes'] if v['attribute'] in
                                   ('AQUATIC_LAND_FLG', 'aem_source_layer', 'aem_source', 'STEWARD', 'STATEABBR')},
                    'sourceBuild': record['metadata'].get('generator_options')}
        a, b = description(original), description(blm)
        comparisons.append({'partial': a, 'statewideBlm': b,
                            'partialAdditionalFields': sorted(set(a['fields']) - set(b['fields'])),
                            'sharedFieldNamesNotProofOfIdentity': sorted(set(a['fields']) & set(b['fields'])),
                            'uniqueFeatures': 'BLOCKED: no feature geometries or cross-source identity mapping supplied',
                            'alreadyInStatewideData': 'BLOCKED: cannot establish feature equivalence from metadata',
                            'differentAuthoritativeDataset': 'Unverified source lineage; distinct schema/build inputs; no authority assertion',
                            'masterLayerRequirement': 'Not used by current selected master PLSS registry; BLM provides required rendering',
                            'decision': 'EXCLUDED — UNIQUENESS UNVERIFIED; retain physical file unchanged; no production layer'})
    assert len(excluded) == 2
    excluded_paths = {r['oldPath'] for r in excluded}
    manifest['allArchives'] = [r for r in manifest['allArchives'] if r['oldPath'] not in excluded_paths]
    for row in manifest['allArchives'] + manifest['selectedArchiveMigrations']:
        row['sameLayerAlternativesNotProvenDuplicates'] = [p for p in row['sameLayerAlternativesNotProvenDuplicates'] if p not in excluded_paths]
    manifest['inventoryRecordCount'] = len(manifest['allArchives'])
    manifest['auditInventoryRecordCount'] = audit['archive_count']
    manifest['excludedArchiveCount'] = 2
    # Link only selected production sources. Excluded partial files have no operations.
    operations = []
    for row in manifest['selectedArchiveMigrations']:
        source = str(Path(row['oldPath']).relative_to(oldroot))
        destination = str(Path(row['newPath']).relative_to(newroot))
        if source == destination:
            continue
        operations.append({'id': f'canonical-{len(operations)+1}', 'kind': 'link',
                           'source': source, 'destination': destination,
                           'expectedBytes': row['bytes'], 'expectedSourceLayers': row['sourceLayers'],
                           'executionBlocked': bool(row['destinationCollision'])})
    assert len({op['destination'] for op in operations}) == len(operations)
    moves = manifest['selectedArchiveMigrations']
    names = sum(r['currentFilename'] != r['proposedFilename'] for r in moves)
    dirs_only = sum(r['currentFilename'] == r['proposedFilename'] and
                    Path(r['oldPath']).relative_to(oldroot) != Path(r['newPath']).relative_to(newroot) for r in moves)
    dirs_all = sum(Path(r['oldPath']).relative_to(oldroot).parent != Path(r['newPath']).relative_to(newroot).parent for r in moves)
    manifest.update({'planVersion': 2, 'status': 'FINAL STORAGE PLAN; execution and backend integration not approved',
                     'operations': operations,
                     'counts': {'selectedArchives': len(moves), 'filenameChanges': names,
                                'directoryOnlyChanges': dirs_only, 'allParentDirectoryChanges': dirs_all,
                                'selectedPathChanges': len(operations),
                                'excludedArchives': 2, 'totalOperations': len(operations),
                                'readyAfterLiveChecks': sum(not op['executionBlocked'] for op in operations),
                                'unresolvedDestinationConflicts': sum(op['executionBlocked'] for op in operations)},
                     'excludedArchivesReport': 'washington-excluded-archives.json',
                     'rollbackPolicy': 'Restore every pre-existing path; retain all generated aliases under transaction-specific rollback retention paths; delete nothing',
                     'requiresApproval': ['production execution after dependency/symlink/service review',
                                          'separate handling of the two occupied Washington names, outside this production plan',
                                          'backend/path switch as a separate future task'],
                     'noDataLossBasis': 'All original selected archives and excluded files remain untouched. Migration only adds verified hard links into absent destinations. Rollback retains aliases. Occupied destinations block execution; live checks are mandatory.'})
    path.write_text(json.dumps(manifest, indent=2)+'\n')
    (BASE / 'docs/washington-excluded-archives.json').write_text(json.dumps(excluded, indent=2)+'\n')
    (BASE / 'docs/washington-partial-comparison.json').write_text(json.dumps(comparisons, indent=2)+'\n')
    def write_csv(filename, rows):
        with (BASE / 'docs' / filename).open('w', newline='') as stream:
            keys = list(dict.fromkeys(k for row in rows for k in row))
            writer = csv.DictWriter(stream, fieldnames=keys)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: json.dumps(value) if isinstance(value, (list, dict)) else value for key, value in row.items()})
    write_csv('mbtiles-inventory.csv', manifest['selectedArchiveMigrations'])
    write_csv('mbtiles-audit-inventory.csv', manifest['allArchives'] + excluded)
    lines = ['# Final uniform MBTiles storage plan', '',
             '**Storage migration remains planning-only. Local backend compatibility is prepared. No production operations were executed.**', '',
             'The audit has 168 historical path records. The production inventory has 98 selected archive paths. '
             'Two smaller Washington archives are listed separately as **EXCLUDED — UNIQUENESS UNVERIFIED**; '
             'neither is a production layer, migration source or deletion candidate.', '',
             'Canonical root: `/root/arizona-naip-build/live-mvt/data/`, historically resolved to '
             '`/root/LIVE_SITE_CASHE/live-mvt/data/`. Resolve the live symlink again before execution.', '',
             'Canonical structure: `{state}/{dataset}/tiles/{state}-{dataset}.mbtiles`. '
             'PLSS uses `{state}/plss/tiles/{state}-plss-{sublayer}.mbtiles`; combined PLSS stays '
             '`{state}/plss/tiles/{state}-plss.mbtiles`. Keep original source-layer IDs and all attributes. '
             'Roads and historic mines remain R2 PMTiles; parcels remain VM MBTiles.', '',
             '## Reconciled counts', '',
             '- 98 selected archives; 26 filename corrections; **6 directory-only changes**, not seven.',
             '- 15 parent-directory changes when including files whose names also change.',
             '- 32 selected path changes: 30 have no known occupied target; two Washington names remain physically occupied.',
             '- All 32 operations are additive hard links. No original file is renamed, moved, overwritten or deleted.', '',
             '## All-state summary', '',
             '| State | Selected | Filename corrections | Directory-only changes | Occupied targets |',
             '| --- | ---: | ---: | ---: | ---: |']
    for state in 'az ca co id mt nm nv or ut wa wy'.split():
        subset = [r for r in moves if r['state'] == state]
        names_count = sum(r['currentFilename'] != r['proposedFilename'] for r in subset)
        dirs_count = sum(r['currentFilename'] == r['proposedFilename'] and
                         Path(r['oldPath']).relative_to(oldroot) != Path(r['newPath']).relative_to(newroot) for r in subset)
        lines.append(f'| {state.upper()} | {len(subset)} | {names_count} | {dirs_count} | {sum(bool(r["destinationCollision"]) for r in subset)} |')
    lines += ['', '## Exact selected path corrections', '',
              '| Current path relative to data root | Canonical proposed path | Status |', '| --- | --- | --- |']
    for row in moves:
        source = Path(row['oldPath']).relative_to(oldroot)
        destination = Path(row['newPath']).relative_to(newroot)
        if source != destination:
            lines.append(f'| `{source}` | `{destination}` | {"BLOCKED: occupied filename" if row["destinationCollision"] else "Plan only; live checks pending"} |')
    lines += ['', 'Idaho corrections explicitly retain BLM-only scope and standardize the intersected-survey name. '
              'They do not convert restricted claims into statewide claims or change either vector source layer.', '',
              '## Washington — final selection and exclusions', '',
              'Keep `wa-plss-government-lots-blm-authoritative.mbtiles` (source layer `plss_government_lots`) '
              'and `wa-plss-quarter-quarter-sections-blm-authoritative.mbtiles` '
              '(source layer `plss_quarter_quarter_sections`) as canonical **data sources**. Their proposed standardized '
              'filenames remain occupied; no script overwrites or relocates the excluded occupants. '
              'All selected statewide special-survey and other PLSS archives remain included.', '',
              'The following exact paths are excluded from production and migration registration:', '',
              '| Excluded path under `/root/LIVE_SITE_CASHE/live-mvt/data/` | Audit-reported count | Status |',
              '| --- | ---: | --- |',
              '| `wa/plss/tiles/wa-plss-government-lots.mbtiles` | 26 | EXCLUDED — UNIQUENESS UNVERIFIED |',
              '| `wa/plss/tiles/wa-plss-quarter-quarter-sections.mbtiles` | 16 | EXCLUDED — UNIQUENESS UNVERIFIED |', '',
              'Both report `AQUATIC_LAND_FLG=N`; no aquatic-land authority is asserted. Counts are the audit’s '
              '`tilestats` counts, not an independent unique-feature recount. Extra attribute names do not establish '
              'unique features or a required additional production layer. Geometry overlap/redundancy cannot be '
              'proved from the supplied metadata. Neither physical file is marked for deletion.', '',
              '## Duplicates versus destination conflicts', '',
              'The Montana pair is a user-reported SHA-256-identical duplicate; only `mt-claims.mbtiles` is selected. '
              'No deletion is in this plan. The 13 same-file identity groups are aliases, not independent redundant '
              'copies. Washington’s occupied destinations are name conflicts, not verified duplicate data.', '',
              '## Files and executable scripts', '',
              '- [Production inventory CSV](mbtiles-inventory.csv): 98 selected archives, including all unchanged ones.',
              '- [Final old-to-new manifest](mbtiles-path-manifest.json): 98 canonical mappings, 32 link operations, '
              'and retained nonselected records; the two excluded records have been removed.',
              '- [Separate exclusions](washington-excluded-archives.json) and '
              '[Washington evidence](washington-partial-comparison.json).',
              '- [Full historical audit inventory](mbtiles-audit-inventory.csv): all 168 records, with exclusions labeled.',
              '- `scripts/mbtiles_migrate.py` and `scripts/mbtiles_rollback.py`: executable, read-only checks by default. '
              'They require explicit approval/review flags for filesystem changes; neither changes backend code or services.', '',
              'Read-only check from the repository on the VM:', '', '```bash',
              'python3 scripts/mbtiles_migrate.py --manifest docs/mbtiles-path-manifest.json', '```', '',
              'Future approved execution only (not authorized or run in this task):', '', '```bash',
              'python3 scripts/mbtiles_migrate.py --manifest docs/mbtiles-path-manifest.json \\'.replace('\\', '\\'),
              '  --receipt /tmp/aem-mbtiles-migration-receipt.json --apply \\'.replace('\\', '\\'),
              '  --approved-deployment --dependencies-reviewed',
              'python3 scripts/mbtiles_rollback.py --receipt /tmp/aem-mbtiles-migration-receipt.json',
              '# After approval and review, add --apply --approved-deployment --dependencies-reviewed to roll back.',
              '```', '',
              'Preflight checks every source/destination, strictly resolves the root, rejects nested symlinks and '
              'path escapes, detects active SQLite journals, checks integrity and exact source-layer sets, '
              'hashes each source before/after inspection, checks filesystem/device and free-space reserve, and refuses '
              'any occupied destination. Execution adds only verified same-filesystem hard links; originals remain. '
              'Rollback verifies hashes and originals, then moves only created aliases into transaction-specific '
              '`migration-rollback/tiles/` retention paths. It never deletes a file. The receipt is rollback state, not a hiccup log.', '',
              'A mid-operation pending receipt or changed file blocks automatic rollback for manual reconciliation. '
              'Cross-filesystem copying is intentionally unsupported until a separate verified copy plan is approved.', '',
              '## Validation and approval issues', '',
              'Six local storage tests pass, including actual synthetic apply/rollback, byte preservation, occupied-target '
              'refusal, symlink/path escape rejection, metadata/integrity failure, and final-manifest exclusions. '
              'The generator verifies all 11 states, 98 selected sources, both Idaho corrections, unique canonical '
              'destinations and retention of required statewide PLSS source layers.', '',
              'Remaining: live SHA-256/integrity and symlink/service/dependency review; approval for production execution; '
              'a separate approved resolution of the two occupied Washington names without deleting unique data; '
              'and deployment of the prepared backend as a separately approved task. No storage loss is introduced by this plan: originals '
              'and excluded files are retained, links are verified, and rollback retains aliases. Live preconditions '
              'must pass before an actual production safety claim can be made.', '']
    (BASE / 'docs/mbtiles-naming-plan.md').write_text('\n'.join(lines))
    print(json.dumps(manifest['counts']))


if __name__ == '__main__':
    main()
