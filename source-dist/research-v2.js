/* Fresh point research shared by dropped, searched, and reopened saved pins. */
async function aemOpenResearchV2(lngLat, selectedFeature = null) {
  const request = ++researchLocationRequest;
  const lng = Number(lngLat.lng), lat = Number(lngLat.lat);
  activeResearchLocation = { lng, lat, name: selectedFeature?.properties?.display_label || 'Location research' };
  researchLocationCard.hidden = false;
  researchCoordinates.textContent = `${lat.toFixed(5)}, ${lng.toFixed(5)}`;
  researchResults.textContent = 'Researching location…';
  const url = new URL('https://tiles.americanexplorationmaps.com/api/search-v2/identify');
  url.searchParams.set('lng', lng);
  url.searchParams.set('lat', lat);
  if (selectedFeature?.properties?.state_code) url.searchParams.set('state', selectedFeature.properties.state_code);
  const kind = selectedFeature?.properties?.search_type;
  const fetchRecord = kind === 'roads' || kind === 'historic-mines';
  const recordUrl = new URL('record', url);
  if (fetchRecord) {
    recordUrl.search = url.search;
    recordUrl.searchParams.set('identity', selectedFeature.id);
    recordUrl.searchParams.set('kind', kind);
  }
  const checks = await Promise.allSettled([
    fetch(url).then(response => { if (!response.ok) throw new Error('Location research is temporarily unavailable.'); return response.json(); }),
    countyAtPoint(lngLat),
    fetchRecord ? fetch(recordUrl).then(response => { if (!response.ok) throw new Error(); return response.json(); }) : null
  ]);
  if (request !== researchLocationRequest) return;
  const data = checks[0].status === 'fulfilled' ? checks[0].value : null;
  const groups = data?.groups || {};
  const county = checks[1].status === 'fulfilled' ? checks[1].value : '';
  const group = name => groups[name] || { status: 'not_published', features: [] };
  const props = name => group(name).features[0]?.properties || {};
  const unavailable = name => group(name).status === 'unavailable' ? 'Lookup unavailable; try again.' : 'No published coverage for this location.';
  const nodes = [[], [], [], []];
  const [location, claims, land, property] = nodes;
  location.push(researchTextResult('Coordinates', `${lat.toFixed(5)}, ${lng.toFixed(5)}`));
  if (!data || data.status !== 'ok') {
    location.push(researchTextResult('Location research', data?.status === 'outside_supported_states' ? 'Outside supported state coverage.' : 'Lookup unavailable; this does not mean there are no records at this location.'));
  }
  const parcel = props('parcels');
  location.push(researchTextResult('County', county || parcel.county || parcel.countyName || parcel.County));
  location.push(researchTextResult('City / Place', firstResearchValue(parcel, ['city', 'situs_city', 'AZ_PlaceName'])));
  const township = props('plssTownships'), section = props('plssSections');
  location.push(researchTextResult('Principal Meridian', formatMeridian(township) || formatMeridian(section)));
  location.push(researchTextResult('Township', formatTownship(township) || unavailable('plssTownships')));
  location.push(researchTextResult('Range', formatRange(township) || unavailable('plssTownships')));
  location.push(researchTextResult('Section', formatSection(section) || unavailable('plssSections')));
  for (const [key, label] of [['plssQuarterSections', 'Quarter section'], ['plssQuarterQuarterSections', 'Quarter-quarter section'], ['plssGovernmentLots', 'Government lot'], ['plssSpecialSurveys', 'Special survey']]) {
    const g = group(key);
    const labels = g.features.map(f => firstResearchValue(f.properties, ['SECDIVLAB', 'SECDIVTXT', 'SECDIVNO', 'FRSTDIVLAB', 'FRSTDIVNO', 'SURVTYP', 'SURVNAME'])).filter(Boolean);
    location.push(researchTextResult(label, labels.join(' · ') || (g.status === 'ok' ? 'None found at pin.' : unavailable(key))));
  }
  if (group('claims').status === 'ok') appendClaimResults(claims, group('claims').features.map(f => ({ attributes: f.properties })));
  else claims.push(researchTextResult('Claims at pin', unavailable('claims')));
  const legal = [formatMeridian(township) || formatMeridian(section), formatTownship(township), formatRange(township), formatSection(section)].filter(Boolean).join(' · ');
  claims.push(researchTextResult('Search location', legal));
  claims.push(researchLinkResult('BLM records', 'Open MLRS Mining Claims Geographic Report', MLRS_GEOGRAPHIC_REPORT_URL));
  const addGroup = (target, key, label) => {
    const g = group(key);
    target.push(researchTextResult(label, g.status === 'ok' ? `${g.features.length} record${g.features.length === 1 ? '' : 's'} at pin` : unavailable(key)));
    g.features.forEach((f, index) => {
      for (const [name, value] of Object.entries(f.properties || {})) {
        if (value == null || value === '' || name.startsWith('_') || ['source_details', 'CSE_META'].includes(name)) continue;
        target.push(researchTextResult(`${label} ${index + 1} · ${name}`, typeof value === 'object' ? JSON.stringify(value) : String(value)));
      }
    });
  };
  addGroup(land, 'surfaceManagement', 'Surface management');
  const withdrawals = group('withdrawals');
  if (withdrawals.status !== 'not_published') addGroup(land, 'withdrawals', 'Withdrawals');
  else {
    addGroup(land, 'withdrawalsAuthorized', 'Authorized / Interim withdrawals');
    addGroup(land, 'withdrawalsPending', 'Pending withdrawals');
  }
  const parcels = group('parcels');
  property.push(researchTextResult('Parcels at pin', parcels.status === 'ok' ? String(parcels.features.length) : unavailable('parcels')));
  parcels.features.forEach((feature, index) => {
    const p = feature.properties || {}, details = aemParcelPinDetails(p);
    property.push(researchTextResult(`Parcel ${index + 1} APN`, details.parcelId));
    property.push(researchTextResult('Address', details.address));
    property.push(researchTextResult('County', county || details.county));
    for (const [label, names] of [['Owner', ['owner_name', 'owner', 'OWNER', 'OWNER_NAME']], ['Acreage', ['landAcres', 'Acres', 'acres', 'acreage', 'GISACRE']]]) property.push(researchTextResult(label, firstResearchValue(p, names)));
    if (details.propertyRecordsUrl) property.push(researchLinkResult('Parcel records', 'Open property records', details.propertyRecordsUrl));
  });
  researchPages = [{ title: 'Location / PLSS', nodes: location }, { title: 'MLRS / BLM', nodes: claims }, { title: 'Land Status', nodes: land }, { title: 'Property', nodes: property }];
  if (selectedFeature) {
    const selected = [];
    if (fetchRecord && checks[2].status === 'rejected') selected.push(researchTextResult('Source record', 'Live details unavailable.'));
    const fields = checks[2].value?.properties || selectedFeature.properties || {};
    for (const [key, value] of Object.entries(fields)) {
      if (value == null || value === '' || ['search_rank', 'source_details', 'CSE_META'].includes(key)) continue;
      selected.push(researchTextResult(key.replaceAll('_', ' '), String(value)));
    }
    researchPages.push({ title: 'Selected result', nodes: selected });
  }
  researchPageIndex = 0;
  renderResearchPage();
}
