/* Route display is the gate for every corridor discovery request. */
const AEM_ROUTE_API = 'https://tiles.americanexplorationmaps.com/api/routes';
const AEM_ROUTE_RADII = [1, 3, 5, 10];
const AEM_MAX_WAYPOINTS = 10;
function aemValidRoutePoint(text) {
  const values = text.split(',').map((value) => value.trim());
  if (values.length !== 2 || values.some((value) => !value)) return null;
  const parts = values.map(Number);
  if (!Number.isFinite(parts[0]) || !Number.isFinite(parts[1]) ||
      Math.abs(parts[0]) > 90 || Math.abs(parts[1]) > 180) return null;
  return [parts[1], parts[0]];
}
function aemValidatePlannedRoute(data) {
  const coordinates = data?.geometry?.coordinates;
  if (data?.geometry?.type !== 'LineString' || !Array.isArray(coordinates) ||
      coordinates.length < 2 || coordinates.length > 100000 ||
      !coordinates.every((point) => Array.isArray(point) && point.length >= 2 &&
        Number.isFinite(point[0]) && Number.isFinite(point[1]) &&
        Math.abs(point[0]) <= 180 && Math.abs(point[1]) <= 90)) {
    throw new Error('Routing service returned an invalid path.');
  }
  return { type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates } };
}
function aemInstallRouteFinder(map, panel, searchOptions, getSavedPins) {
  panel.innerHTML = `
    <div class="aem-route-pick" hidden>
      <p role="status">Tap a location on the map.</p>
      <button id="aem-route-cancel-pick" type="button">Cancel map pick</button>
    </div>
    <div class="aem-route-editor">
      <form id="aem-route-point-search" class="map-search" role="search" aria-label="Find a route point">
        <label id="aem-route-query-label" class="sr-only" for="aem-route-point-query">Search for a start</label>
        <div class="map-search__row">
          <input id="aem-route-point-query" type="search" autocomplete="off" placeholder="Search for a start">
          <button type="submit">Find</button>
        </div>
        <div id="aem-route-search-suggestions" hidden>
          <div id="aem-route-map-sources" class="aem-route-map-sources">
            <button id="aem-route-pick-point" type="button">Pick on map</button>
            <button id="aem-route-map-center" type="button">Use map center</button>
          </div>
          <div id="aem-route-pin-matches" class="map-search__choices" aria-label="Saved pins"></div>
        </div>
        <p id="aem-route-point-status" class="map-search__status" role="status"></p>
      </form>
      <div class="aem-route-stops" role="group" aria-label="Route points">
        <button id="aem-route-start-point" type="button" aria-pressed="true">Start</button>
        <ol id="aem-route-waypoints" aria-label="Waypoints in route order" hidden></ol>
        <button id="aem-route-destination-point" type="button" aria-pressed="false">Destination</button>
        <button id="aem-route-add-waypoint" type="button" aria-pressed="false" hidden>+ Add waypoint</button>
      </div>
      <button id="aem-route-plan" type="button" disabled>Plan route</button>
      <p id="aem-route-plan-status" role="status"></p>
      <details class="aem-route-options">
        <summary>Route options</summary>
        <label>Route type<select id="aem-route-plan-mode"><option value="driving">Driving</option>
          <option value="hiking">Hiking</option></select></label>
        <label>Discovery radius<select id="aem-route-radius"><option value="1">1 mile</option>
          <option value="3" selected>3 miles</option><option value="5">5 miles</option>
          <option value="10">10 miles</option><option value="custom">10+ miles</option></select></label>
        <label id="aem-route-custom-wrap" hidden>Custom miles<input id="aem-route-custom" type="number" min="11" max="100" step="1" value="15"></label>
        <p>Routes are advisory. Check legal access, closures, and passability before travel.</p>
      </details>
      <div id="aem-route-discovery" aria-live="polite"></div>
    </div>`;
  const byId = (id) => panel.querySelector(`#${id}`);
  const finderMenu = panel.closest('details');
  const pointForm = byId('aem-route-point-search');
  const pointQuery = byId('aem-route-point-query');
  const pointLabel = byId('aem-route-query-label');
  const pointStatus = byId('aem-route-point-status');
  const suggestions = byId('aem-route-search-suggestions');
  const mapSources = byId('aem-route-map-sources');
  const pinMatches = byId('aem-route-pin-matches');
  const startButton = byId('aem-route-start-point');
  const destinationButton = byId('aem-route-destination-point');
  const addWaypointButton = byId('aem-route-add-waypoint');
  const waypointList = byId('aem-route-waypoints');
  const pickButton = byId('aem-route-pick-point');
  const cancelPickButton = byId('aem-route-cancel-pick');
  const pickBanner = panel.querySelector('.aem-route-pick');
  const editor = panel.querySelector('.aem-route-editor');
  const endpoints = { start: null, destination: null };
  const waypoints = [];
  let target = 'start';
  let picking = false;
  const mode = byId('aem-route-plan-mode');
  const radius = byId('aem-route-radius');
  const custom = byId('aem-route-custom');
  const customWrap = byId('aem-route-custom-wrap');
  const planButton = byId('aem-route-plan');
  const status = byId('aem-route-plan-status');
  const discovery = byId('aem-route-discovery');
  let route = null;
  let requestId = 0;
  let planning = false;
  const empty = { type: 'FeatureCollection', features: [] };
  function ensureLayer() {
    if (!map.isStyleLoaded() || map.getSource('aem-planned-route')) return;
    map.addSource('aem-planned-route', { type: 'geojson', data: route || empty });
    map.addLayer({ id: 'aem-planned-driving', type: 'line', source: 'aem-planned-route',
      filter: ['==', ['get', 'mode'], 'driving'],
      paint: { 'line-color': '#ffd34e', 'line-width': 5, 'line-opacity': 0.95 } });
    map.addLayer({ id: 'aem-planned-hiking', type: 'line', source: 'aem-planned-route',
      filter: ['==', ['get', 'mode'], 'hiking'],
      paint: { 'line-color': '#a8ef80', 'line-width': 5, 'line-opacity': 0.95,
        'line-dasharray': [1.5, 1.5] } });
  }
  function formatPoint([lng, lat]) {
    return `${lat.toFixed(6)}, ${lng.toFixed(6)}`;
  }

  function setPointStatus(message, state = '') {
    pointStatus.textContent = message;
    pointStatus.className = `map-search__status ${state}`.trim();
  }

  function renderPoints() {
    const { start, destination } = endpoints;
    startButton.textContent = start ? `Start: ${start.name}` : 'Start';
    startButton.setAttribute('aria-pressed', String(target === 'start'));
    destinationButton.textContent = destination ? `Destination: ${destination.name}` : 'Destination';
    destinationButton.setAttribute('aria-pressed', String(target === 'destination'));
    addWaypointButton.hidden = !start || !destination || waypoints.length >= AEM_MAX_WAYPOINTS;
    addWaypointButton.setAttribute('aria-pressed', String(target === 'waypoint'));
    planButton.disabled = !start || !destination || planning;

    const prompt = target === 'start' ? 'Search for a start' :
      target === 'destination' ? 'Search for a destination' :
      target === 'waypoint' ? 'Search for a waypoint' : 'Search for a replacement waypoint';
    pointLabel.textContent = prompt;
    pointQuery.placeholder = prompt;
    waypointList.replaceChildren();
    waypointList.hidden = !waypoints.length;
    for (const waypoint of waypoints) {
      const row = document.createElement('li');
      const change = document.createElement('button');
      change.type = 'button';
      change.textContent = waypoint.name;
      change.setAttribute('aria-label', `Change waypoint ${waypoint.name}`);
      change.setAttribute('aria-pressed', String(target === waypoint));
      change.addEventListener('click', () => selectTarget(waypoint));
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.textContent = '×';
      remove.setAttribute('aria-label', `Remove waypoint ${waypoint.name}`);
      remove.addEventListener('click', () => {
        waypoints.splice(waypoints.indexOf(waypoint), 1);
        pointsChanged();
        selectTarget(nextTarget());
      });
      row.append(change, remove);
      waypointList.append(row);
    }
  }

  function nextTarget() {
    if (!endpoints.start) return 'start';
    if (!endpoints.destination) return 'destination';
    return 'waypoint';
  }

  function selectTarget(next) {
    pointSearch.cancel();
    target = next;
    pointQuery.value = '';
    setPointStatus('');
    renderPoints();
    pointQuery.focus();
    showSuggestions();
  }

  function pointsChanged() {
    if (route) status.textContent = 'Plan again to update the route.';
  }

  function usePoint(point, name = '') {
    if (!Array.isArray(point) || point.length !== 2 || !point.every(Number.isFinite) ||
        Math.abs(point[0]) > 180 || Math.abs(point[1]) > 90) {
      throw new Error('That location has invalid coordinates.');
    }
    const entry = { name: name || formatPoint(point), point };
    if (target === 'waypoint') {
      if (waypoints.length >= AEM_MAX_WAYPOINTS) throw new Error('A route can have up to 10 waypoints.');
      waypoints.push(entry);
    } else if (typeof target === 'string') {
      endpoints[target] = entry;
    } else {
      Object.assign(target, entry);
    }
    target = nextTarget();
    pointQuery.value = '';
    setPointStatus('');
    suggestions.hidden = true;
    pointsChanged();
    renderPoints();
  }

  function savedPinFeature(pin) {
    return {
      properties: { display_label: pin.name || formatPoint([pin.lng, pin.lat]), search_type: 'Saved pin' },
      geometry: { type: 'Point', coordinates: [pin.lng, pin.lat] }
    };
  }

  const pointSearch = installAemUnifiedSearch({
    ...searchOptions,
    form: pointForm,
    input: pointQuery,
    status: setPointStatus,
    emptyMessage: 'Enter a place, address, AEM feature, saved pin, or coordinates.',
    localMatches: (value) => getSavedPins()
      .filter((pin) => pin.name?.trim().toLowerCase() === value.toLowerCase())
      .map(savedPinFeature),
    navigate: (feature) => usePoint(feature.geometry?.coordinates, feature.properties?.display_label)
  });

  function showSuggestions() {
    const query = pointQuery.value.trim().toLowerCase();
    const matches = getSavedPins().filter((pin) => pin.name?.toLowerCase().includes(query));
    mapSources.hidden = Boolean(query);
    pinMatches.replaceChildren();
    for (const pin of matches) {
      const feature = savedPinFeature(pin);
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = `Saved pin · ${feature.properties.display_label}`;
      button.addEventListener('click', () => useShortcut(feature.geometry.coordinates, feature.properties.display_label));
      pinMatches.append(button);
    }
    suggestions.hidden = Boolean(query && !matches.length);
  }

  function useShortcut(point, name) {
    pointSearch.cancel();
    try { usePoint(point, name); }
    catch (error) { setPointStatus(error.message, 'error'); }
  }

  pointQuery.addEventListener('focus', showSuggestions);
  pointQuery.addEventListener('input', showSuggestions);
  pointForm.addEventListener('submit', () => { suggestions.hidden = true; });
  startButton.addEventListener('click', () => selectTarget('start'));
  destinationButton.addEventListener('click', () => selectTarget('destination'));
  addWaypointButton.addEventListener('click', () => selectTarget('waypoint'));
  byId('aem-route-map-center').addEventListener('click', () => {
    const { lng, lat } = map.getCenter().wrap();
    useShortcut([lng, lat]);
  });

  function finishPick(restoreFocus) {
    if (!picking) return;
    picking = false;
    map.getCanvas().classList.remove('aem-route-map-picking');
    pickBanner.hidden = true;
    editor.hidden = false;
    if (restoreFocus) pointQuery.focus();
  }

  pickButton.addEventListener('click', () => {
    pointSearch.cancel();
    picking = true;
    pickBanner.hidden = false;
    editor.hidden = true;
    map.getCanvas().classList.add('aem-route-map-picking');
    cancelPickButton.focus();
  });
  cancelPickButton.addEventListener('click', () => finishPick(true));
  map.on('click', ({ lngLat }) => {
    if (!picking || !finderMenu.open) return;
    const { lng, lat } = lngLat.wrap();
    useShortcut([lng, lat]);
    finishPick(false);
  });
  panel.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    if (picking) {
      event.preventDefault();
      finishPick(true);
    } else if (!suggestions.hidden) {
      event.preventDefault();
      suggestions.hidden = true;
    }
  });
  finderMenu.addEventListener('toggle', () => {
    if (finderMenu.open) return;
    finishPick(false);
    suggestions.hidden = true;
    pointSearch.cancel();
  });

  pointQuery.addEventListener('paste', (event) => {
    const lines = event.clipboardData?.getData('text').trim().split(/\r?\n/);
    if (target !== 'waypoint' || !lines || lines.length < 2) return;
    const points = lines.map(aemValidRoutePoint);
    if (points.some((point) => !point)) return;
    event.preventDefault();
    if (waypoints.length + points.length > AEM_MAX_WAYPOINTS) {
      setPointStatus('A route can have up to 10 waypoints.', 'error');
      return;
    }
    pointSearch.cancel();
    waypoints.push(...points.map((point) => ({ name: formatPoint(point), point })));
    pointQuery.value = '';
    suggestions.hidden = true;
    pointsChanged();
    renderPoints();
  });

  renderPoints();
  radius.addEventListener('change', () => { customWrap.hidden = radius.value !== 'custom'; });
  async function post(path, payload, signal) {
    const response = await fetch(`${AEM_ROUTE_API}/${path}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload), signal
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `${path} service unavailable (${response.status}).`);
    return data;
  }
  async function discover(kind, path, miles, id, signal) {
    const row = document.createElement('p');
    row.textContent = `${kind}: checking…`;
    discovery.append(row);
    try {
      const data = await post('discover', { kind, path, radius_miles: miles }, signal);
      if (id !== requestId) return;
      const features = Array.isArray(data.features) ? data.features : [];
      if (kind === 'Private parcels within 0.5 mile') {
        const crossed = features.filter((item) => item.relation === 'crossed').length;
        row.textContent = `${kind}: ${crossed} crossed, ${features.length - crossed} nearby` +
          (data.complete === false ? ' (partial coverage)' : '');
      } else {
        row.textContent = `${kind}: ${features.length} possible nearby ` +
          `${features.length === 1 ? 'feature' : 'features'}` +
          (data.complete === false ? ' (partial coverage)' : '');
      }
    } catch (error) {
      if (id !== requestId || error.name === 'AbortError') return;
      row.textContent = `${kind}: check unavailable — ${error.message}`;
    }
  }
  let controller = null;
  planButton.addEventListener('click', async () => {
    if (!endpoints.start || !endpoints.destination) return;
    suggestions.hidden = true;
    const points = [endpoints.start.point, ...waypoints.map(({ point }) => point), endpoints.destination.point];
    const travelMode = mode.value;
    const miles = radius.value === 'custom' ? Number(custom.value) : Number(radius.value);
    if (!Number.isFinite(miles) || miles < 1 || miles > 100 ||
        (radius.value === 'custom' && miles <= 10) ||
        (radius.value !== 'custom' && !AEM_ROUTE_RADII.includes(miles))) {
      status.textContent = 'Choose a valid discovery radius.';
      return;
    }
    controller?.abort();
    controller = new AbortController();
    const id = ++requestId;
    planning = true;
    planButton.disabled = true;
    status.textContent = 'Calculating route…';
    discovery.replaceChildren();
    try {
      const data = await post('plan', { points, mode: travelMode }, controller.signal);
      if (id !== requestId) return;
      const feature = aemValidatePlannedRoute(data);
      feature.properties.mode = travelMode;
      route = feature;
      window.aemPlannedRoute = {
        geometry: feature.geometry, mode: travelMode,
        distanceMeters: Number.isFinite(data.distance_meters) ? data.distance_meters : null,
        createdAt: Date.now()
      };
      ensureLayer();
      const source = map.getSource('aem-planned-route');
      if (!source) throw new Error('Map is not ready to display the route.');
      source.setData(feature);
      const bounds = coordinatesBounds(feature.geometry.coordinates);
      map.fitBounds(bounds, { padding: 60, maxZoom: 14, duration: 500 });
      status.textContent = Number.isFinite(data.distance_meters)
        ? `Route displayed · ${(data.distance_meters / 1609.344).toFixed(1)} mi`
        : 'Route displayed';
      const farthestSnap = Math.max(0, ...(data.snapped_points_meters || []));
      if (farthestSnap > 25) {
        status.textContent += ` · nearest road/trail is up to ${Math.round(farthestSnap)} m from a chosen point`;
      }
      // Wait until the GeoJSON source has loaded and its line is actually on screen.
      const afterRouteRender = () => {
        if (id !== requestId) { map.off('render', afterRouteRender); return; }
        if (!map.isSourceLoaded('aem-planned-route') ||
            !map.queryRenderedFeatures(undefined, { layers: ['aem-planned-driving', 'aem-planned-hiking'] }).length) {
          return;
        }
        map.off('render', afterRouteRender);
        status.textContent += ' · checking nearby features';
        void discover('Private parcels within 0.5 mile', feature.geometry.coordinates, 0.5, id, controller.signal);
        for (const kind of ['claims', 'historic-mines']) {
          void discover(kind, feature.geometry.coordinates, miles, id, controller.signal);
        }
      };
      map.on('render', afterRouteRender);
      map.triggerRepaint();
    } catch (error) {
      if (error.name !== 'AbortError' && id === requestId) status.textContent = error.message;
    } finally {
      if (id === requestId) {
        planning = false;
        planButton.disabled = false;
      }
    }
  });
  map.on('style.load', ensureLayer);
  if (map.isStyleLoaded()) ensureLayer();
}
function coordinatesBounds(coordinates) {
  const bounds = new maplibregl.LngLatBounds(coordinates[0], coordinates[0]);
  for (const point of coordinates.slice(1)) bounds.extend(point);
  return bounds;
}
aemInstallRouteFinder(map, document.querySelector('#routeFinderPanel .aem-route-panel__body'), {
  parseState: aemParseStateSearch,
  parseCoordinates,
  parsePlss,
  geocode: searchAddressCandidates,
  fetch: window.fetch.bind(window)
}, () => savedLocations);
