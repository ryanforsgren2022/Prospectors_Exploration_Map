"""Pure naming proposals for the inventory; not connected to backend services."""

STATES = frozenset('az ca co id mt nm nv or ut wa wy'.split())
DATASET_NAMES = {
    'boundary': 'boundary', 'claims': 'claims', 'claimsBlmLands': 'claims-blm-lands',
    'surfaceManagement': 'surface-management', 'parcels': 'parcels',
    'stateRoutes': 'state-routes', 'historicMines': 'historic-mines',
    'withdrawalsAuthorized': 'withdrawals-authorized', 'withdrawalsPending': 'withdrawals-pending',
    'plssTownships': 'plss-townships', 'plssSections': 'plss-sections',
    'plssGovernmentLots': 'plss-government-lots', 'plssSpecialSurveys': 'plss-special-surveys',
    'plssQuarterSections': 'plss-quarter-sections',
    'plssQuarterQuarterSections': 'plss-quarter-quarter-sections',
    'plssSurveyPoints': 'plss-survey-points', 'plssIntersected': 'plss-intersected-surveys',
    'plssSecondDivision': 'plss-second-divisions'
}


def canonical_relative_path(state, groups):
    if state not in STATES or not groups:
        raise ValueError('Unknown state or missing dataset')
    names = {DATASET_NAMES[group] for group in groups}
    if all(name.startswith('plss-') for name in names):
        directory = 'plss'
        dataset = next(iter(names)) if len(names) == 1 else 'plss'
    elif names <= {'withdrawals-authorized', 'withdrawals-pending'}:
        directory = 'withdrawals'
        dataset = next(iter(names)) if len(names) == 1 else 'withdrawals'
    elif len(names) == 1:
        directory = dataset = next(iter(names))
    else:
        raise ValueError('Unrelated datasets must not be merged by a naming migration')
    return f'{state}/{directory}/tiles/{state}-{dataset}.mbtiles'
