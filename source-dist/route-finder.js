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
      <label>Start coordinates<input id="aem-route-origin" placeholder="33.4484, -112.0740"></label>
      <button id="aem-route-origin-center" type="button">Use map center as start</button>
      <label>Destination coordinates<input id="aem-route-destination" placeholder="33.5641, -111.8869"></label>
      <button id="aem-route-destination-center" type="button">Use map center as destination</button>
      <fieldset class="aem-route-points">
        <legend>Find a route point</legend>
        <label>Use as<select id="aem-route-point-target">
          <option value="waypoint">Waypoint</option><option value="start">Start</option><option value="destination">Destination</option>
        </select></label>
        <form id="aem-route-point-search" class="map-search" role="search" aria-label="Find a route point">
          <label for="aem-route-point-query">Place, address, AEM feature, or coordinates</label>
          <div class="map-search__row">
            <input id="aem-route-point-query" type="search" autocomplete="off" placeholder="Kanab, UT or MINE Gold King">
            <button type="submit">Find</button>
          </div>
          <p id="aem-route-point-status" class="map-search__status" role="status"></p>
        </form>
        <button id="aem-route-pick-point" type="button">Pick on map</button>
        <label>Use a saved pin<select id="aem-route-saved-pin"></select></label>
      </fieldset>
      <details class="aem-route-coordinates">
        <summary>Add waypoint coordinates in bulk</summary>
        <label>Latitude, longitude (one pair per line)
          <textarea id="aem-route-waypoint" rows="2" placeholder="33.5, -112.0"></textarea>
        </label>
        <button id="aem-route-add-coordinates" type="button">Add waypoints</button>
        <p id="aem-route-coordinate-status" role="status"></p>
      </details>
      <ol id="aem-route-waypoints" aria-label="Waypoints in route order" hidden></ol>
      <label>Route type<select id="aem-route-plan-mode"><option value="driving">Driving</option>
        <option value="hiking">Hiking</option></select></label>
      <label>Discovery radius<select id="aem-route-radius"><option value="1">1 mile</option>
        <option value="3" selected>3 miles</option><option value="5">5 miles</option>
        <option value="10">10 miles</option><option value="custom">10+ miles</option></select></label>
      <label id="aem-route-custom-wrap" hidden>Custom miles<input id="aem-route-custom" type="number" min="10" max="100" step="1" value="15"></label>
      <button id="aem-route-plan" type="button">Plan route</button>
      <p id="aem-route-plan-status" role="status">Choose a start and destination.</p>
      <p>Routes are advisory. Check legal access, closures, and passability before travel.</p>
      <div id="aem-route-discovery" aria-live="polite"></div>
    </div>`;
  const byId = (id) => panel.querySelector(`#${id}`);
  const finderMenu = panel.closest('details');
  const origin = byId('aem-route-origin');
  const destination = byId('aem-route-destination');
  const bulkWaypoints = byId('aem-route-waypoint');
  const waypointList = byId('aem-route-waypoints');
  const pointTarget = byId('aem-route-point-target');
  const pointQuery = byId('aem-route-point-query');
  const pointStatus = byId('aem-route-point-status');
  const coordinateStatus = byId('aem-route-coordinate-status');
  const savedPin = byId('aem-route-saved-pin');
  const pickButton = byId('aem-route-pick-point');
  const cancelPickButton = byId('aem-route-cancel-pick');
  const pickBanner = panel.querySelector('.aem-route-pick');
  const editor = panel.querySelector('.aem-route-editor');
  const waypoints = [];
  let savedPins = [];
  let pickingFor = null;
  const mode = byId('aem-route-plan-mode');
  const radius = byId('aem-route-radius');
  const custom = byId('aem-route-custom');
  const customWrap = byId('aem-route-custom-wrap');
  const planButton = byId('aem-route-plan');
  const status = byId('aem-route-plan-status');
  const discovery = byId('aem-route-discovery');
  let route = null;
  let requestId = 0;
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

  function renderWaypoints() {
    waypointList.replaceChildren();
    waypointList.hidden = !waypoints.length;
    for (const waypoint of waypoints) {
      const row = document.createElement('li');
      const name = document.createElement('span');
      name.textContent = waypoint.name;
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.textContent = 'Remove';
      remove.setAttribute('aria-label', `Remove waypoint ${waypoint.name}`);
      remove.addEventListener('click', () => {
        waypoints.splice(waypoints.indexOf(waypoint), 1);
        renderWaypoints();
        setPointStatus(`Removed ${waypoint.name}.`);
        pointQuery.focus();
      });
      row.append(name, remove);
      waypointList.append(row);
    }
  }

  function usePoint(point, name = '', target = pointTarget.value) {
    if (!Array.isArray(point) || point.length !== 2 || !point.every(Number.isFinite) ||
        Math.abs(point[0]) > 180 || Math.abs(point[1]) > 90) {
      throw new Error('That location has invalid coordinates.');
    }
    const label = name || formatPoint(point);
    if (target === 'waypoint') {
      if (waypoints.length >= AEM_MAX_WAYPOINTS) throw new Error('A route can have up to 10 waypoints.');
      waypoints.push({ name: label, point });
      renderWaypoints();
      setPointStatus(`Added ${label}.`, 'success');
    } else {
      const isStart = target === 'start';
      (isStart ? origin : destination).value = formatPoint(point);
      setPointStatus(`${isStart ? 'Start' : 'Destination'} set to ${label}.`, 'success');
    }
  }

  const pointSearch = installAemUnifiedSearch({
    ...searchOptions,
    form: byId('aem-route-point-search'),
    input: pointQuery,
    status: setPointStatus,
    emptyMessage: 'Enter a place, address, AEM feature, or coordinates.',
    navigate: (feature) => {
      usePoint(feature.geometry?.coordinates, feature.properties?.display_label);
      pointQuery.value = '';
    }
  });

  function setFromMap(target, location) {
    const { lng, lat } = location.wrap();
    usePoint([lng, lat], '', target);
  }

  byId('aem-route-origin-center').addEventListener('click', () => setFromMap('start', map.getCenter()));
  byId('aem-route-destination-center').addEventListener('click', () => setFromMap('destination', map.getCenter()));
  pointTarget.addEventListener('change', () => {
    pointSearch.cancel();
    setPointStatus('');
  });

  function finishPick(restoreFocus) {
    if (!pickingFor) return;
    pickingFor = null;
    map.getCanvas().classList.remove('aem-route-map-picking');
    pickBanner.hidden = true;
    editor.hidden = false;
    if (restoreFocus) pickButton.focus();
  }

  pickButton.addEventListener('click', () => {
    pointSearch.cancel();
    pickingFor = pointTarget.value;
    pickBanner.hidden = false;
    editor.hidden = true;
    map.getCanvas().classList.add('aem-route-map-picking');
    cancelPickButton.focus();
  });
  cancelPickButton.addEventListener('click', () => finishPick(true));
  map.on('click', ({ lngLat }) => {
    if (!pickingFor || !finderMenu.open) return;
    try { setFromMap(pickingFor, lngLat); }
    catch (error) { setPointStatus(error.message, 'error'); }
    finishPick(true);
  });
  panel.addEventListener('keydown', (event) => {
    if (!pickingFor || event.key !== 'Escape') return;
    event.preventDefault();
    finishPick(true);
  });
  finderMenu.addEventListener('toggle', () => {
    if (!finderMenu.open) {
      finishPick(false);
      pointSearch.cancel();
      return;
    }
    savedPins = getSavedPins();
    savedPin.replaceChildren(new Option(savedPins.length ? 'Choose a saved pin' : 'No saved pins yet', ''));
    savedPins.forEach((pin, index) => {
      savedPin.add(new Option(pin.name || formatPoint([pin.lng, pin.lat]), String(index)));
    });
    savedPin.disabled = !savedPins.length;
  });
  savedPin.addEventListener('change', () => {
    if (savedPin.value === '') return;
    const pin = savedPins[Number(savedPin.value)];
    pointSearch.cancel();
    try { usePoint([pin.lng, pin.lat], pin.name); }
    catch (error) { setPointStatus(error.message, 'error'); }
    savedPin.value = '';
  });

  function addBulkWaypoints() {
    if (!bulkWaypoints.value.trim()) return true;
    const points = bulkWaypoints.value.trim().split(/\n+/).map(aemValidRoutePoint);
    if (points.some((point) => !point)) {
      coordinateStatus.textContent = 'Enter one valid latitude, longitude pair per line.';
      return false;
    }
    if (waypoints.length + points.length > AEM_MAX_WAYPOINTS) {
      coordinateStatus.textContent = 'A route can have up to 10 waypoints.';
      return false;
    }
    waypoints.push(...points.map((point) => ({ name: formatPoint(point), point })));
    renderWaypoints();
    bulkWaypoints.value = '';
    coordinateStatus.textContent = `Added ${points.length} ${points.length === 1 ? 'waypoint' : 'waypoints'}.`;
    return true;
  }

  byId('aem-route-add-coordinates').addEventListener('click', addBulkWaypoints);
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
    if (!addBulkWaypoints()) {
      status.textContent = 'Check your waypoint coordinates.';
      return;
    }
    const start = aemValidRoutePoint(origin.value);
    const end = aemValidRoutePoint(destination.value);
    if (!start || !end) {
      status.textContent = 'Choose a valid start and destination.';
      return;
    }
    const points = [start, ...waypoints.map(({ point }) => point), end];
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
      if (id === requestId) planButton.disabled = false;
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
