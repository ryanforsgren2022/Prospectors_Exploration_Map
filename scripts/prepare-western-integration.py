"""Build a reviewable registry from the supplied audit; never touch VM archives."""
import json
import re
from collections import defaultdict
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parents[1]
AUDIT = BASE / 'vm-review/mbtiles-audit.json'
sys.path.insert(0, str(BASE / 'vm-review'))
from aem_archive_paths import canonical_relative_path
LAYER_GROUPS = {
    'state_boundary': 'boundary', 'boundary': 'boundary',
    'surface_management': 'surfaceManagement', 'parcels': 'parcels',
    'claims_not_closed': 'claims', 'claims': 'claims', 'mining_claims': 'claims',
    'withdrawals_authorized': 'withdrawalsAuthorized', 'withdrawals_pending': 'withdrawalsPending',
    'plss_townships': 'plssTownships', 'plss_sections': 'plssSections',
    'plss_first_division': 'plssSections', 'plss_government_lots': 'plssGovernmentLots',
    'plss_special_surveys': 'plssSpecialSurveys', 'plss_quarter_sections': 'plssQuarterSections',
    'plss_quarter_quarter': 'plssQuarterQuarterSections',
    'plss_quarter_quarter_sections': 'plssQuarterQuarterSections',
    'plss_survey_points': 'plssSurveyPoints', 'plss_intersected': 'plssIntersected',
    'plss_second_division': 'plssSecondDivision',
    'nm_plss_townships': 'plssTownships', 'nm_plss_sections': 'plssSections',
    'nm_plss_special-surveys': 'plssSpecialSurveys', 'nm_plss_survey-points': 'plssSurveyPoints',
    'nm_plss_second-divisions': 'plssSecondDivision', 'nm_plss_intersected-surveys': 'plssIntersected',
}
EXCLUDED = re.compile(r'(?:staging|parts|rejected|backup|invalid|building|\.tmp\.|patch|recovery)', re.I)
# Explicit selections: source/schema evidence for AZ/WA; copied production readers for NV/UT.
PREFERRED = {
    # User reports matching SHA-256 and passing integrity checks for both files,
    # and explicitly selects this canonical path. Deletion still requires live checks.
    ('mt', 'claims'): 'mt/claims/mt-claims.mbtiles',
    ("az", "plssTownships"): "az/plss/tiles/az-plss-townships.mbtiles",
    ("wa", "plssGovernmentLots"): "wa/plss/tiles/wa-plss-government-lots-blm-authoritative.mbtiles",
    ("wa", "plssQuarterQuarterSections"): "wa/plss/tiles/wa-plss-quarter-quarter-sections-blm-authoritative.mbtiles",
    **{('nv', group): 'nv/plss/tiles/nv-plss.mbtiles' for group in
       ['plssTownships', 'plssSections', 'plssGovernmentLots', 'plssSpecialSurveys']},
    **{('ut', group): f'ut/plss/tiles/utah-plss-{kind}.mbtiles' for group, kind in
       [('plssTownships', 'townships'), ('plssSections', 'sections')]},
    **{('ut', group): 'ut/withdrawals/tiles/ut-withdrawals.mbtiles' for group in
       ['withdrawalsAuthorized', 'withdrawalsPending']},
}
BLOCKED_CANONICAL_DESTINATIONS = {
    ('wa', 'plssGovernmentLots'),
    ('wa', 'plssQuarterQuarterSections'),
}


def conflict_evidence(audit, root):
    decisions = []
    for (state, group), path in PREFERRED.items():
        alternatives = []
        for record in audit['archives']:
            real = Path(record['real_path'])
            if not real.is_relative_to(root / state) or EXCLUDED.search(str(real.relative_to(root))):
                continue
            for layer in record['source_layers']:
                if LAYER_GROUPS.get(layer) == group:
                    meta = record['metadata']
                    data = json.loads(meta.get('json', '{}'))
                    alternatives.append({'path': str(real.relative_to(root)), 'bounds': meta.get('bounds'),
                        'sourceBuild': meta.get('generator_options'), 'errors': record['errors'],
                        'sampleTile': record.get('sample_tile'),
                        'layerMetadata': [v for v in data.get('vector_layers', []) if v['id'] == layer],
                        'statistics': [{
                            'layer': v['layer'], 'count': v.get('count'), 'geometry': v.get('geometry'),
                            'provenance': [a for a in v.get('attributes', []) if a['attribute'] in
                                           ('STATEABBR', 'STEWARD', 'aem_source', 'aem_source_layer')]
                        } for v in data.get('tilestats', {}).get('layers', []) if v['layer'] == layer]})
        if len(alternatives) > 1:
            reason = 'Preserve archive explicitly used by copied production reader; no newest/largest ranking.'
            if state == 'wa':
                reason = ('BLM source input and cadastral schema span the state; competing clipped alternate-source schema '
                          'covers only a small northwest subset. Bounds, schema, source build, nonempty sample and '
                          'audit errors are recorded below. Statistics alone do not establish completeness.')
            elif state == 'mt':
                reason = ('User confirmed identical SHA-256 and passing SQLite integrity for both archives; '
                          'explicitly retain mt/claims/mt-claims.mbtiles. Exact digest not provided locally; '
                          'duplicate removal remains conditional on live reference and hash checks.')
            elif state == 'az':
                reason = ('Dedicated township source retains GlobalID, STATEABBR and PRINMER, with Arizona-wide '
                          'coverage and a nonempty audit tile. Combined converted/tile-joined archive loses those '
                          'fields; retain it for its other sublayers. This is a source/schema choice, not a date, '
                          'file size or zoom ranking. Full feature-level coverage cannot be proven by this audit.')
            decisions.append({'state': state, 'group': group, 'selectedPath': path,
                              'reason': reason, 'evidence': alternatives,
                              'verificationLimit': 'Audit metadata and sample only; live payload/hash verification pending'})
    return decisions


def main():
    audit = json.loads(AUDIT.read_text())
    root = Path(audit['canonical_data_root'])  # Already resolved by the VM audit.
    identities = defaultdict(list)
    candidates = defaultdict(list)
    invalid, outside, excluded = [], [], []
    for record in audit['archives']:
        identities[record.get('file_identity', record['real_path'])].append(record['path'])
        path = Path(record['real_path'])
        inside = path.is_relative_to(root)
        if not inside:
            outside.append(record)
        meta = record.get('metadata', {})
        if record['errors'] or not record['source_layers'] or not meta.get('bounds'):
            invalid.append({'path': record['path'], 'errors': record['errors'] or ['Missing vector metadata/bounds']})
            continue
        if not inside or EXCLUDED.search(str(path.relative_to(root))):
            excluded.append(record['path'])
            continue
        relative = path.relative_to(root).as_posix()
        state = relative.split('/')[0]
        for layer in record['source_layers']:
            group = LAYER_GROUPS.get(layer)
            if not group:
                continue
            candidates[state, group].append((record, layer, relative))
    states, conflicts, claims_review = {}, [], []
    for (state, group), options in sorted(candidates.items()):
        unique = {}
        for record, layer, relative in options:
            unique.setdefault((record.get('file_identity', record['real_path']), layer), (record, layer, relative))
        options = list(unique.values())
        # Classification is filtered per feature in the read-only tile reader.
        # An archive containing Closed/unknown values must not lose its valid non-closed records.
        preferred = PREFERRED.get((state, group))
        preferred_options = [o for o in options if o[2] == preferred]
        if preferred_options:
            selected = preferred_options[0]
            if state == 'wa':
                # Verify source/coverage evidence, not the 'authoritative' filename.
                meta = selected[0]['metadata']
                payload = json.loads(meta['json'])
                stats = next(v for v in payload['tilestats']['layers'] if v['layer'] == selected[1])
                provenance = {a['attribute']: a.get('values', []) for a in stats['attributes']}
                extent = [float(v) for v in meta['bounds'].split(',')]
                assert provenance.get('STATEABBR') == ['WA']
                assert 'BLM_Natl_PLSS_CadNSDI_MapServer_3' in provenance.get('aem_source', [])
                assert any('BLM Cadastral' in value for value in provenance.get('STEWARD', []))
                assert extent[0] < -124 and extent[2] > -117 and extent[1] < 46 and extent[3] > 49
                for competitor in options:
                    if competitor == selected:
                        continue
                    other = [float(v) for v in competitor[0]['metadata']['bounds'].split(',')]
                    assert extent[0] <= other[0] and extent[1] <= other[1] and extent[2] >= other[2] and extent[3] >= other[3]
            elif state == 'az' and group == 'plssTownships':
                payload = json.loads(selected[0]['metadata']['json'])
                vector = next(v for v in payload['vector_layers'] if v['id'] == selected[1])
                assert {'GlobalID', 'STATEABBR', 'PLSSID', 'PRINMER'} <= vector['fields'].keys()
                extent = [float(v) for v in selected[0]['metadata']['bounds'].split(',')]
                assert extent[0] < -114 and extent[2] > -110 and extent[1] < 32 and extent[3] > 37
                assert selected[0].get('sample_tile') and not selected[0]['errors']
        elif len(options) == 1:
            selected = options[0]
        else:
            if options:
                conflicts.append({'state': state, 'group': group, 'paths': [o[2] for o in options]})
            continue
        record, layer, relative = selected
        meta = record['metadata']
        vector = next((item for item in json.loads(meta.get('json', '{}')).get('vector_layers', []) if item['id'] == layer), {})
        entry = {'path': relative, 'sourceLayer': layer,
                 'minzoom': int(vector.get('minzoom', meta['minzoom'])),
                 'maxzoom': int(vector.get('maxzoom', meta['maxzoom'])),
                 'bounds': [float(v) for v in meta['bounds'].split(',')],
                 'auditFileIdentity': record.get('file_identity'),
                 'auditBytes': record['bytes'], 'sampleTile': record.get('sample_tile')}
        if group == 'claims':
            entry['semantics'] = 'notClosed'
            entry['classificationField'] = 'CSE_DISP'
        if state == 'id' and group == 'claims':
            group = 'claimsBlmLands'
            entry['coverage'] = 'BLM lands only; not authoritative statewide coverage'
        states.setdefault(state, {'datasets': {}})['datasets'][group] = entry
    names = dict(zip('az ca co id mt nm nv or ut wa wy'.split(),
                     ['Arizona', 'California', 'Colorado', 'Idaho', 'Montana', 'New Mexico', 'Nevada', 'Oregon', 'Utah', 'Washington', 'Wyoming']))
    boundaries = json.loads((BASE / 'source-dist/data/western-state-boundaries.geojson').read_text())
    def positions(value):
        if isinstance(value[0], (float, int)):
            yield value
        else:
            for child in value:
                yield from positions(child)
    for feature in boundaries['features']:
        code = feature['properties']['code'].lower()
        if code in states:
            points = list(positions(feature['geometry']['coordinates']))
            states[code]['name'] = names[code]
            states[code]['bounds'] = [min(p[0] for p in points), min(p[1] for p in points),
                                     max(p[0] for p in points), max(p[1] for p in points)]
    # Keep the reviewed live path and the standardized destination together.
    # Discovery can therefore accept the current archive before migration and
    # a verified hard-link alias afterward without changing public routes.
    groups_by_archive = defaultdict(list)
    for code, state in states.items():
        for group, entry in state['datasets'].items():
            groups_by_archive[(code, entry['path'])].append(group)
    for (code, path), groups in groups_by_archive.items():
        canonical = canonical_relative_path(code, groups)
        for group in groups:
            key = ('canonicalPathBlocked' if (code, group) in BLOCKED_CANONICAL_DESTINATIONS
                   else 'canonicalPath')
            states[code]['datasets'][group][key] = canonical
    registry = {'schemaVersion': 1, 'canonicalDataRoot': str(root), 'states': states}
    aliases = [paths for paths in identities.values() if len(paths) > 1]
    inside_ids = {a.get('file_identity') for a in audit['archives'] if Path(a['real_path']).is_relative_to(root)}
    report = {'archiveCount': audit['archive_count'], 'outsideCount': len(outside),
              'conflictEvidence': conflict_evidence(audit, root),
              'auditErrorCount': sum(bool(a['errors']) for a in audit['archives']),
              'aliases': aliases, 'invalidOrUnverifiedMetadata': invalid,
              'unresolvedCompetitors': conflicts, 'explicitPreferences': [
                  {'state': key[0], 'group': key[1], 'path': value} for key, value in PREFERRED.items()], 'claimsScopeReview': claims_review,
              'outside': [{'path': a['path'], 'layers': a['source_layers'], 'errors': a['errors'],
                           'alreadyRepresentedByIdentity': a.get('file_identity') in inside_ids,
                           'needsVerificationBeforeConsolidation': True} for a in outside]}
    (BASE / 'vm-review/western-datasets.json').write_text(json.dumps(registry, indent=2) + '\n')
    (BASE / 'docs/western-audit-analysis.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f'{sum(len(s["datasets"]) for s in states.values())} explicit dataset registrations; '
          f'{len(aliases)} alias groups; {len(conflicts)} unresolved competitors; '
          f'{len(invalid)} invalid or incomplete metadata records')


if __name__ == '__main__':
    main()
