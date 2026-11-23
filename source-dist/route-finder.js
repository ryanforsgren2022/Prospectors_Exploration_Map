/* Route display is the gate for every corridor discovery request. */
const AEM_ROUTE_API = 'https://tiles.americanexplorationmaps.com/api/routes';
const AEM_ROUTE_RADII = [1, 3, 5, 10];
function aemValidRoutePoint(text) {
  const parts = text.split(',').map((value) => Number(value.trim()));
  if (parts.length !== 2 || !Number.isFinite(parts[0]) || !Number.isFinite(parts[1]) ||
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
function aemInstallRouteFinder(map) {
  const panel = document.createElement('details');
  panel.className = 'aem-route-panel aem-route-finder';
  panel.innerHTML = '<summary>Route Finder</summary><div class="aem-route-panel__body">' +
    '<label>Start latitude, longitude<input id="aem-route-origin" placeholder="33.4484, -112.0740"></label>' +
    '<button id="aem-route-origin-center" type="button">Use map center as start</button>' +
    '<label>Destination latitude, longitude<input id="aem-route-destination" placeholder="33.5641, -111.8869"></label>' +
    '<button id="aem-route-destination-center" type="button">Use map center as destination</button>' +
    '<label>Waypoints (optional, one latitude, longitude per line)<textarea id="aem-route-waypoint" rows="2" placeholder="33.5, -112.0"></textarea></label>' +
    '<label>Route type<select id="aem-route-plan-mode"><option value="driving">Driving</option>' +
    '<option value="hiking">Hiking</option></select></label>' +
    '<label>Discovery radius<select id="aem-route-radius"><option value="1">1 mile</option>' +
    '<option value="3" selected>3 miles</option><option value="5">5 miles</option>' +
    '<option value="10">10 miles</option><option value="custom">10+ miles</option></select></label>' +
    '<label id="aem-route-custom-wrap" hidden>Custom miles<input id="aem-route-custom" type="number" min="10" max="100" step="1" value="15"></label>' +
    '<button id="aem-route-plan" type="button">Plan route</button>' +
    '<p id="aem-route-plan-status" role="status">Choose a start and destination.</p>' +
    '<div id="aem-route-discovery" aria-live="polite"></div></div>';
  document.body.append(panel);
  const byId = (id) => panel.querySelector(`#${id}`);
  const origin = byId('aem-route-origin');
  const destination = byId('aem-route-destination');
  const waypoint = byId('aem-route-waypoint');
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
  function setCenter(input) {
    const center = map.getCenter();
    input.value = `${center.lat.toFixed(6)}, ${center.lng.toFixed(6)}`;
  }
  byId('aem-route-origin-center').addEventListener('click', () => setCenter(origin));
  byId('aem-route-destination-center').addEventListener('click', () => setCenter(destination));
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
      const qualifier = kind === 'Private parcels within 0.5 mile' ? '' : 'possible nearby ';
      row.textContent = `${kind}: ${features.length} ${qualifier}${features.length === 1 ? 'feature' : 'features'}` +
        (data.complete === false ? ' (partial coverage)' : '');
    } catch (error) {
      if (id !== requestId || error.name === 'AbortError') return;
      row.textContent = `${kind}: check unavailable — ${error.message}`;
    }
  }
  let controller = null;
  planButton.addEventListener('click', async () => {
    const points = [aemValidRoutePoint(origin.value)];
    if (waypoint.value.trim()) {
      points.push(...waypoint.value.trim().split(/\n+/).map(aemValidRoutePoint));
    }
    points.push(aemValidRoutePoint(destination.value));
    if (points.length > 12 || points.some((point) => !point)) {
      status.textContent = 'Enter coordinates as latitude, longitude.';
      return;
    }
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
      const data = await post('plan', { points, mode: mode.value }, controller.signal);
      if (id !== requestId) return;
      const feature = aemValidatePlannedRoute(data);
      feature.properties.mode = mode.value;
      route = feature;
      ensureLayer();
      const source = map.getSource('aem-planned-route');
      if (!source) throw new Error('Map is not ready to display the route.');
      source.setData(feature);
      const bounds = coordinatesBounds(feature.geometry.coordinates);
      map.fitBounds(bounds, { padding: 60, maxZoom: 14, duration: 500 });
      status.textContent = Number.isFinite(data.distance_meters)
        ? `Route displayed · ${(data.distance_meters / 1609.344).toFixed(1)} mi`
        : 'Route displayed';
      // Wait until the GeoJSON source has loaded and its line is actually on screen.
      const afterRouteRender = () => {
        if (id !== requestId) { map.off('render', afterRouteRender); return; }
        if (!map.isSourceLoaded('aem-planned-route') ||
            !map.queryRenderedFeatures({ layers: ['aem-planned-driving', 'aem-planned-hiking'] }).length) {
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
aemInstallRouteFinder(map);
