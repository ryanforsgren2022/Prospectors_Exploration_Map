/* Route recording is deliberately independent of routing and discovery requests. */
const AEM_ROUTE_STORAGE_KEY = 'aem-route-trips-v1';
const aemRouteRadians = (degrees) => degrees * Math.PI / 180;
function aemRouteDistanceMeters(a, b) {
  const earth = 6371008.8;
  const latitude = aemRouteRadians(b.lat - a.lat);
  const longitude = aemRouteRadians(b.lng - a.lng);
  const arc = Math.sin(latitude / 2) ** 2 +
    Math.cos(aemRouteRadians(a.lat)) * Math.cos(aemRouteRadians(b.lat)) *
    Math.sin(longitude / 2) ** 2;
  return 2 * earth * Math.atan2(Math.sqrt(arc), Math.sqrt(1 - arc));
}
function aemRouteFormatDuration(milliseconds) {
  const seconds = Math.floor(milliseconds / 1000);
  return [Math.floor(seconds / 3600), Math.floor(seconds % 3600 / 60), seconds % 60]
    .map((part) => String(part).padStart(2, '0')).join(':');
}
function aemRouteReadTrips() {
  try {
    const value = JSON.parse(localStorage.getItem(AEM_ROUTE_STORAGE_KEY) || '[]');
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}
function aemRouteFeatureCollection(trip) {
  const features = [];
  for (const segment of trip?.segments || []) {
    if (segment.points.length < 2) continue;
    features.push({
      type: 'Feature',
      properties: { mode: segment.mode },
      geometry: {
        type: 'LineString',
        coordinates: segment.points.map((point) => [point.lng, point.lat])
      }
    });
  }
  return { type: 'FeatureCollection', features };
}
function aemRouteCreateTrip(mode = 'driving') {
  return {
    id: globalThis.crypto?.randomUUID?.() || String(Date.now()),
    name: '',
    startedAt: Date.now(),
    finishedAt: null,
    elapsedMs: 0,
    distanceMeters: 0,
    elevationGainMeters: 0,
    elevationLossMeters: 0,
    lowElevationMeters: null,
    highElevationMeters: null,
    segments: [{ mode, points: [] }]
  };
}
function aemRouteSetMode(trip, mode) {
  if (!['driving', 'hiking'].includes(mode)) return;
  const last = trip.segments.at(-1);
  if (last?.mode === mode) return;
  trip.segments.push({ mode, points: [] });
}
function aemRouteAddPoint(trip, point) {
  if (!Number.isFinite(point.lng) || !Number.isFinite(point.lat) ||
      !Number.isFinite(point.time) || point.accuracy > 100) return false;
  const segment = trip.segments.at(-1);
  const prior = [...trip.segments].reverse().find((part) => part.points.length)?.points.at(-1);
  if (prior) {
    const meters = aemRouteDistanceMeters(prior, point);
    const seconds = (point.time - prior.time) / 1000;
    if (seconds <= 0 || meters < 2 || meters / seconds > 60) return false;
    trip.distanceMeters += meters;
    if (Number.isFinite(point.elevation) && Number.isFinite(prior.elevation)) {
      const difference = point.elevation - prior.elevation;
      // Ignore vertical GPS noise below five meters.
      if (difference >= 5) trip.elevationGainMeters += difference;
      if (difference <= -5) trip.elevationLossMeters -= difference;
    }
  }
  if (Number.isFinite(point.elevation)) {
    trip.lowElevationMeters = Math.min(trip.lowElevationMeters ?? point.elevation, point.elevation);
    trip.highElevationMeters = Math.max(trip.highElevationMeters ?? point.elevation, point.elevation);
  }
  segment.points.push(point);
  return true;
}
function aemRouteAutoMode(speedMetersPerSecond, currentMode, candidate) {
  // Require sustained motion; a traffic stop never switches to hiking.
  const proposed = speedMetersPerSecond >= 3.2 ? 'driving' :
    speedMetersPerSecond >= 0.4 && speedMetersPerSecond <= 2.3 ? 'hiking' : null;
  if (!proposed || proposed === currentMode) return { mode: currentMode, candidate: null };
  const next = candidate?.mode === proposed
    ? { mode: proposed, samples: candidate.samples + 1 }
    : { mode: proposed, samples: 1 };
  return { mode: next.samples >= 4 ? proposed : currentMode, candidate: next.samples >= 4 ? null : next };
}
function aemInstallRouteTracker(map) {
  const panel = document.createElement('details');
  panel.className = 'aem-route-panel';
  panel.innerHTML = '<summary>Route Tracker</summary>' +
    '<div class="aem-route-panel__body">' +
    '<p id="aem-route-status" role="status">Ready to record.</p>' +
    '<div class="aem-route-actions"><button id="aem-route-start" type="button">Start</button>' +
    '<button id="aem-route-pause" type="button" disabled>Pause</button>' +
    '<button id="aem-route-stop" type="button" disabled>Stop & save</button></div>' +
    '<label>Travel mode <select id="aem-route-mode"><option value="auto">Auto</option>' +
    '<option value="driving">Driving</option><option value="hiking">Hiking</option></select></label>' +
    '<div id="aem-route-stats" aria-live="polite">0.00 mi · 00:00:00 · ↑ 0 ft · ↓ 0 ft</div>' +
    '<label>Saved trips <select id="aem-route-saved"><option value="">Select a trip</option></select></label>' +
    '</div>';
  document.body.append(panel);
  const startButton = panel.querySelector('#aem-route-start');
  const pauseButton = panel.querySelector('#aem-route-pause');
  const stopButton = panel.querySelector('#aem-route-stop');
  const modeSelect = panel.querySelector('#aem-route-mode');
  const savedSelect = panel.querySelector('#aem-route-saved');
  const status = panel.querySelector('#aem-route-status');
  const stats = panel.querySelector('#aem-route-stats');
  let trip = null;
  let watchId = null;
  let recordingStarted = 0;
  let paused = false;
  let candidate = null;
  let shownSaved = null;
  function ensureLayer() {
    if (!map.isStyleLoaded()) return;
    if (!map.getSource('aem-tracked-route')) {
      map.addSource('aem-tracked-route', { type: 'geojson', data: aemRouteFeatureCollection(null) });
      map.addLayer({ id: 'aem-tracked-driving', type: 'line', source: 'aem-tracked-route',
        filter: ['==', ['get', 'mode'], 'driving'],
        paint: { 'line-color': '#32b8ff', 'line-width': 5, 'line-opacity': 0.95 } });
      map.addLayer({ id: 'aem-tracked-hiking', type: 'line', source: 'aem-tracked-route',
        filter: ['==', ['get', 'mode'], 'hiking'],
        paint: { 'line-color': '#67e39a', 'line-width': 5, 'line-dasharray': [1.5, 1.5] } });
    }
    draw();
  }
  function draw() {
    map.getSource('aem-tracked-route')?.setData(aemRouteFeatureCollection(trip || shownSaved));
  }
  function elapsed() {
    return trip ? trip.elapsedMs + (recordingStarted ? Date.now() - recordingStarted : 0) : 0;
  }
  function render() {
    const current = trip || shownSaved;
    stats.textContent = current
      ? \`\${(current.distanceMeters / 1609.344).toFixed(2)} mi · \${aemRouteFormatDuration(trip ? elapsed() : current.elapsedMs)} · ↑ \${Math.round(current.elevationGainMeters * 3.28084)} ft · ↓ \${Math.round(current.elevationLossMeters * 3.28084)} ft\`
      : '0.00 mi · 00:00:00 · ↑ 0 ft · ↓ 0 ft';
    startButton.disabled = Boolean(trip);
    pauseButton.disabled = !trip;
    stopButton.disabled = !trip;
    pauseButton.textContent = paused ? 'Resume' : 'Pause';
    draw();
  }
  function refreshSaved() {
    savedSelect.replaceChildren(new Option('Select a trip', ''));
    for (const item of aemRouteReadTrips()) {
      savedSelect.add(new Option(item.name || new Date(item.startedAt).toLocaleString(), item.id));
    }
  }
  function stopWatch() {
    if (watchId !== null) navigator.geolocation.clearWatch(watchId);
    watchId = null;
  }
  function beginWatch() {
    watchId = navigator.geolocation.watchPosition((position) => {
      if (!trip || paused) return;
      const coords = position.coords;
      const point = {
        lng: coords.longitude, lat: coords.latitude,
        elevation: Number.isFinite(coords.altitude) ? coords.altitude : null,
        accuracy: coords.accuracy, time: position.timestamp
      };
      if (modeSelect.value === 'auto') {
        const prior = [...trip.segments].reverse().find((part) => part.points.length)?.points.at(-1);
        const computed = prior ? aemRouteDistanceMeters(prior, point) / ((point.time - prior.time) / 1000) : null;
        const speed = Number.isFinite(coords.speed) ? coords.speed : computed;
        if (Number.isFinite(speed)) {
          const result = aemRouteAutoMode(speed, trip.segments.at(-1).mode, candidate);
          candidate = result.candidate;
          aemRouteSetMode(trip, result.mode);
        }
      }
      if (aemRouteAddPoint(trip, point)) {
        status.textContent = \`Recording \${trip.segments.at(-1).mode} · GPS ±\${Math.round(coords.accuracy)} m\`;
        render();
      }
    }, (error) => {
      status.textContent = \`GPS unavailable: \${error.message}\`;
      // Keep the trip and controls available if location service fails.
    }, { enableHighAccuracy: true, maximumAge: 0, timeout: 20000 });
  }
  startButton.addEventListener('click', () => {
    if (!navigator.geolocation) { status.textContent = 'This browser does not support GPS.'; return; }
    trip = aemRouteCreateTrip(modeSelect.value === 'hiking' ? 'hiking' : 'driving');
    shownSaved = null;
    recordingStarted = Date.now();
    paused = false;
    candidate = null;
    beginWatch();
    status.textContent = 'Waiting for GPS…';
    render();
  });
  pauseButton.addEventListener('click', () => {
    if (!trip) return;
    if (paused) {
      paused = false;
      recordingStarted = Date.now();
      beginWatch();
      status.textContent = 'Recording resumed.';
    } else {
      trip.elapsedMs += Date.now() - recordingStarted;
      recordingStarted = 0;
      paused = true;
      stopWatch();
      status.textContent = 'Recording paused.';
    }
    render();
  });
  stopButton.addEventListener('click', () => {
    if (!trip) return;
    if (!paused) trip.elapsedMs += Date.now() - recordingStarted;
    stopWatch();
    trip.finishedAt = Date.now();
    trip.name = window.prompt('Name this trip', new Date(trip.startedAt).toLocaleString()) ||
      new Date(trip.startedAt).toLocaleString();
    try {
      localStorage.setItem(AEM_ROUTE_STORAGE_KEY, JSON.stringify([trip, ...aemRouteReadTrips()]));
      status.textContent = 'Trip saved on this device.';
    } catch {
      status.textContent = 'Storage is full. Trip remains visible but was not saved.';
    }
    shownSaved = trip;
    trip = null;
    recordingStarted = 0;
    paused = false;
    refreshSaved();
    render();
  });
  modeSelect.addEventListener('change', () => {
    if (!trip) return;
    candidate = null;
    if (modeSelect.value !== 'auto') aemRouteSetMode(trip, modeSelect.value);
    render();
  });
  savedSelect.addEventListener('change', () => {
    if (trip) return;
    shownSaved = aemRouteReadTrips().find((item) => item.id === savedSelect.value) || null;
    render();
  });
  map.on('style.load', ensureLayer);
  if (map.isStyleLoaded()) ensureLayer();
  refreshSaved();
  window.setInterval(() => { if (trip && !paused) render(); }, 1000);
}
aemInstallRouteTracker(map);
