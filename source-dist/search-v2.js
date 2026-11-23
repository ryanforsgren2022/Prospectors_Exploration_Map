/* Shared search interaction: resolve, choose, navigate, then research a fresh pin. */
function aemUnifiedQuery(value, parsePlss) {
  const match = value.match(/^(APN|PARCEL|CLAIM|BLM|CASE|ROAD|MINE)(?:\s*[:#]\s*|\s+)(.+)$/i);
  const kinds = { APN: 'parcels', PARCEL: 'parcels', CLAIM: 'claims', BLM: 'claims', CASE: 'claims', ROAD: 'roads', MINE: 'historic-mines' };
  if (match) return { q: match[2].trim(), kind: kinds[match[1].toUpperCase()] };
  const plss = parsePlss(value);
  if (plss) return { q: `T${plss.township}${plss.townshipDirection} R${plss.range}${plss.rangeDirection}${plss.section ? ` S${plss.section}` : ''}`, kind: plss.section ? 'sections' : 'townships' };
  return { q: value };
}

function installAemUnifiedSearch(options) {
  const { form, input, status, parseState, parseCoordinates, parsePlss, geocode, navigate } = options;
  const choices = document.createElement('div');
  choices.className = 'map-search__choices';
  choices.setAttribute('aria-label', 'Matching locations');
  form.append(choices);
  let sequence = 0;
  let controller = null;
  const cancel = () => { sequence++; controller?.abort(); choices.replaceChildren(); input.disabled = false; };
  input.addEventListener('input', cancel);
  options.map?.on('dragstart', cancel);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    cancel();
    const current = sequence;
    const isCurrent = () => sequence === current;
    const raw = input.value.trim();
    if (!raw) return status('Enter a parcel/APN, claim, PLSS reference, road, mine, address, or coordinates.', 'error');
    controller = new AbortController();
    input.disabled = true;
    status('Searching…');
    try {
      await options.prepare();
      if (!isCurrent()) return;
      const context = parseState(raw);
      const query = aemUnifiedQuery(context.value, parsePlss);
      const coordinates = !query.kind && parseCoordinates(context.value);
      if (coordinates) {
        await navigate({ type: 'Feature', properties: { display_label: context.value }, geometry: { type: 'Point', coordinates: [coordinates.longitude, coordinates.latitude] } }, isCurrent);
        return;
      }
      const url = new URL('https://tiles.americanexplorationmaps.com/api/search-v2/find');
      url.searchParams.set('q', query.q);
      if (query.kind) url.searchParams.set('kind', query.kind);
      const state = context.explicitState ? context.state : options.stateSelect?.value;
      if (state) url.searchParams.set('state', state);
      if (options.countyInput?.value.trim()) url.searchParams.set('county', options.countyInput.value.trim());
      const response = await options.fetch(url, { signal: controller.signal });
      if (!response.ok) throw new Error('Search is temporarily unavailable. Please try again.');
      const result = await response.json();
      if (!isCurrent()) return;
      const features = result.features || [];
      if (features.length === 1 && !result.truncated) {
        await navigate(features[0], isCurrent);
      } else if (features.length) {
        for (const feature of features) {
          const p = feature.properties || {};
          const button = document.createElement('button');
          button.type = 'button';
          button.textContent = [p.display_label, p.search_type, p.county, p.PRINMER || p.PRINMERCD, p.state_code?.toUpperCase()].filter(Boolean).join(' · ');
          button.addEventListener('click', async () => {
            if (!isCurrent()) return;
            choices.replaceChildren();
            try { await navigate(feature, isCurrent); }
            catch (error) { if (isCurrent()) status(error.message, 'error'); }
          });
          choices.append(button);
        }
        status(result.truncated ? 'Choose a match; add a state or a more specific reference to narrow the results.' : 'Choose the location you mean.');
      } else {
        // Explicit references must never silently become an unrelated address.
        if (query.kind) throw new Error(result.pending?.length ? 'This search category is still being indexed. Please try again when it is ready.' : 'No matching record found. Check the state and reference.');
        const address = await geocode(context.value);
        if (!isCurrent()) return;
        if (!address?.location) throw new Error(result.pending?.length ? 'Some datasets are still indexing; no address match was found.' : 'No matching location found.');
        await navigate({ type: 'Feature', properties: { display_label: address.attributes?.LongLabel || address.address || raw }, geometry: { type: 'Point', coordinates: [address.location.x, address.location.y] } }, isCurrent);
      }
    } catch (error) {
      if (isCurrent() && error.name !== 'AbortError') status(error.message || 'Search is temporarily unavailable.', 'error');
    } finally {
      if (isCurrent()) input.disabled = false;
    }
  });
  return { cancel };
}
