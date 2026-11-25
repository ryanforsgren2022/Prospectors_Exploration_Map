/* Fresh point research shared by dropped, searched, and reopened saved pins. */
const BLM_MINING_CLAIMS_QUERY = 'https://nlsdbpubgis.blm.gov/arcgishub/rest/services/HUB/BLM_Natl_MLRS_Mining_Claims_Not_Closed/FeatureServer/0/query';

function blmClaimQueryUrl(filters) {
  const url = new URL(BLM_MINING_CLAIMS_QUERY);
  url.search = new URLSearchParams({
    ...filters,
    outFields: 'CSE_NR,LEG_CSE_NR,CSE_NAME,CSE_DISP,BLM_PROD,RCRD_ACRS',
    returnGeometry: 'false',
    f: 'html'
  });
  return url.href;
}

function blmClaimsAtPointUrl(lng, lat) {
  return blmClaimQueryUrl({
    where: '1=1',
    geometry: `${lng},${lat}`,
    geometryType: 'esriGeometryPoint',
    inSR: '4326',
    spatialRel: 'esriSpatialRelIntersects'
  });
}

function blmClaimRecordUrl(properties) {
  for (const field of ['CSE_NR', 'LEG_CSE_NR']) {
    const serial = String(properties[field] ?? '').trim().toUpperCase();
    if (/^[A-Z]{2,4} *[0-9][0-9A-Z-]*$/.test(serial)) {
      return blmClaimQueryUrl({ where: `${field}='${serial}'` });
    }
  }
  return '';
}

function researchDetailSection(title, nodes) {
  const section = document.createElement('details');
  section.className = 'research-location__detail-section';
  const heading = document.createElement('summary');
  heading.textContent = title;
  const results = document.createElement('div');
  results.className = 'research-location__results';
  results.append(...nodes);
  section.append(heading, results);
  return section;
}

function pinLandManager(properties = {}) {
  for (const [field, aliases] of Object.entries(SURFACE_MANAGEMENT_ALIASES)) {
    if (field === 'SMA_ID' && Object.keys(SURFACE_MANAGEMENT_ALIASES).some(
      key => key !== 'SMA_ID' && Object.hasOwn(properties, key)
    )) continue;
    const value = String(properties[field] ?? '').toUpperCase();
    if (Object.hasOwn(aliases, value)) return aliases[value];
  }
  return '';
}

function pinRecordCount(groups) {
  const available = groups.filter(group => group.status === 'ok');
  if (!available.length) {
    return groups.some(group => group.status === 'unavailable') ? 'Lookup unavailable' : 'No published coverage';
  }

  const count = available.reduce((total, group) => total + group.features.length, 0);
  if (available.length < groups.length) return count ? `${count} found · partial coverage` : 'Partial coverage';
  return count ? `${count} found` : 'None found';
}

async function aemOpenResearchV2(lngLat, selectedFeature = null) {
  const request = ++researchLocationRequest;
  const lng = Number(lngLat.lng), lat = Number(lngLat.lat);
  activeResearchLocation = { lng, lat, name: selectedFeature?.properties?.display_label || 'Location research' };
  researchLocationTitle.textContent = selectedFeature?.properties?.display_label || 'Pinned location';
  researchDetails.open = false;
  researchDetails.hidden = true;
  researchDetailSections.replaceChildren();
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
  const withdrawals = group('withdrawals').status === 'not_published'
    ? [['withdrawalsAuthorized', 'Authorized / Interim withdrawals'], ['withdrawalsPending', 'Pending withdrawals']]
    : [['withdrawals', 'Withdrawals']];
  const claimGroup = group('claims');
  const claimsAtPin = blmClaimsAtPointUrl(lng, lat);
  if (data?.status === 'ok') {
    const surface = group('surfaceManagement');
    const managers = [...new Set(surface.features.map(feature => pinLandManager(feature.properties)).filter(Boolean))];
    const landManager = surface.status === 'ok' && surface.features.length
      ? managers.join(' · ') || 'See land status details'
      : pinRecordCount([surface]);
    const claimCount = pinRecordCount([claimGroup]);
    const claimSummary = claimGroup.status === 'ok' && claimGroup.features.length
      ? researchLinkResult('Mining claims', `${claimCount} · View BLM records`, claimsAtPin)
      : researchTextResult('Mining claims', claimCount);
    researchResults.replaceChildren(
      researchTextResult('Land manager', landManager),
      claimSummary,
      researchTextResult('Withdrawals', pinRecordCount(withdrawals.map(([key]) => group(key)))),
      researchTextResult('Parcels', pinRecordCount([group('parcels')]))
    );
  } else {
    researchResults.textContent = data?.status === 'outside_supported_states'
      ? 'Outside supported map coverage.'
      : 'Map records could not be loaded.';
  }

  const location = [];
  const parcel = group('parcels').features[0]?.properties || {};
  const countyName = county || parcel.county || parcel.countyName || parcel.County;
  const place = firstResearchValue(parcel, ['city', 'situs_city', 'AZ_PlaceName']);
  if (countyName) location.push(researchTextResult('County', countyName));
  if (place) location.push(researchTextResult('City / place', place));
  const sections = [];
  if (selectedFeature) {
    const selected = [];
    if (fetchRecord && checks[2].status === 'rejected') selected.push(researchTextResult('Source record', 'Live details unavailable.'));
    const fields = checks[2].value?.properties || selectedFeature.properties || {};
    if (kind === 'claims') {
      const claimUrl = blmClaimRecordUrl(fields);
      if (claimUrl) selected.push(researchLinkResult('BLM', 'View this claim', claimUrl));
    }
    if (kind === 'historic-mines') selected.push(researchLinkResult('BLM', 'View claims at this mine', claimsAtPin));
    for (const [key, value] of Object.entries(fields)) {
      if (value == null || value === '' || ['search_rank', 'source_details', 'CSE_META'].includes(key)) continue;
      selected.push(researchTextResult(key.replaceAll('_', ' '), String(value)));
    }
    if (selected.length) sections.push(researchDetailSection('Selected result', selected));
  }
  if (data?.status === 'ok') {
    sections.push(...pinRecordSections(group, withdrawals, location, county));
  } else if (location.length) {
    sections.push(researchDetailSection('Location', location));
  }
  researchDetailSections.replaceChildren(...sections);
  researchDetails.hidden = !sections.length;
}

function pinRecordSections(group, withdrawals, location, county) {
  const claims = [], land = [], property = [];
  const props = name => group(name).features[0]?.properties || {};
  const unavailable = name => group(name).status === 'unavailable' ? 'Lookup unavailable; try again.' : 'No published coverage for this location.';
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
  const claimGroup = group('claims');
  if (claimGroup.status === 'ok') {
    claims.push(researchTextResult('Claims at pin', pinRecordCount([claimGroup])));
    claimGroup.features.forEach((feature, index) => {
      const properties = feature.properties || {};
      const parts = [
        properties.CSE_NAME || 'Unnamed claim',
        properties.CSE_NR || properties.LEG_CSE_NR || 'No case number',
        properties.CSE_DISP || 'Status not listed'
      ];
      if (properties.RCRD_ACRS) parts.push(`${properties.RCRD_ACRS} acres`);
      const label = `Claim ${index + 1}`;
      const description = parts.join(' · ');
      const recordUrl = blmClaimRecordUrl(properties);
      claims.push(recordUrl ? researchLinkResult(label, description, recordUrl) : researchTextResult(label, description));
    });
  } else {
    claims.push(researchTextResult('Claims at pin', unavailable('claims')));
  }
  const legal = [formatMeridian(township) || formatMeridian(section), formatTownship(township), formatRange(township), formatSection(section)].filter(Boolean).join(' · ');
  claims.push(researchTextResult('Search location', legal));
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
  for (const [key, label] of withdrawals) addGroup(land, key, label);
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
  return [
    researchDetailSection('Land status', land),
    researchDetailSection('Mining claims', claims),
    researchDetailSection('Property', property),
    researchDetailSection('Location / PLSS', location)
  ];
}
