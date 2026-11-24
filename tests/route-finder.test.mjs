import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

test('planned route renders before parcel and feature discovery, without PLSS changes', async () => {
  const controls = new Map();
  const control = (id) => {
    if (!controls.has(id)) controls.set(id, {
      value: '', disabled: false, hidden: false, textContent: '',
      listeners: {}, addEventListener(name, callback) { this.listeners[name] = callback; },
      append() {}, replaceChildren() {}, focus() {}, setAttribute() {},
    });
    return controls.get(id);
  };
  const panel = {
    innerHTML: '', className: '',
    querySelector(selector) { return control(selector.slice(1)); },
    closest() { return control('finder-menu'); },
    addEventListener() {},

  };
  const requests = [];
  const layers = [];
  const source = { setData(value) { this.data = value; } };
  let render;
  let sourceLoaded = false;
  const map = {
    isStyleLoaded: () => true,
    getSource: () => layers.length ? source : null,
    addSource() { layers.push('source'); },
    addLayer(layer) { layers.push(layer.id); },
    getCenter: () => ({ lng: -112, lat: 33 }),
    fitBounds() {}, triggerRepaint() {},
    on(event, callback) { if (event === 'render') render = callback; },
    off(event, callback) { if (event === 'render' && render === callback) render = null; },
    isSourceLoaded: () => sourceLoaded,
    queryRenderedFeatures: () => [{ id: 1 }],
  };
  const browserWindow = { fetch() {} };
  let chooseSearchResult;
  const context = vm.createContext({
    map, window: browserWindow,
    aemParseStateSearch() {}, parseCoordinates() {}, parsePlss() {}, searchAddressCandidates() {},
    installAemUnifiedSearch(options) {
      chooseSearchResult = options.navigate;
      return { cancel() {} };
    },
    document: {
      querySelector(selector) {
        assert.equal(selector, '#routeFinderPanel .aem-route-panel__body');
        return panel;
      },
      createElement: () => ({ textContent: '', append() {}, addEventListener() {}, setAttribute() {} }),
    },
    maplibregl: { LngLatBounds: class { constructor() {} extend() {} } },
    AbortController,
    fetch: async (url, options) => {
      requests.push({ url, body: JSON.parse(options.body) });
      return { ok: true, json: async () => url.endsWith('/plan')
        ? { geometry: { type: 'LineString', coordinates: [[-112, 33], [-111.99, 33]] }, distance_meters: 934 }
        : { features: [], complete: true } };
    },
  });
  vm.runInContext(readFileSync(new URL('../source-dist/route-finder.js', import.meta.url), 'utf8'), context);
  const choose = (name, lng, lat) => chooseSearchResult({
    properties: { display_label: name }, geometry: { coordinates: [lng, lat] }
  });
  assert.equal(control('aem-route-point-query').placeholder, 'Search for a start');
  choose('Start', -112, 33);
  assert.equal(control('aem-route-point-query').placeholder, 'Search for a destination');
  choose('Destination', -111.99, 33);
  assert.equal(control('aem-route-plan').disabled, false);
  choose('Copper Mine', -111.995, 33);
  control('aem-route-point-query').listeners.paste({
    clipboardData: { getData: () => '33, -111.993\n33, -111.991' }, preventDefault() {}
  });
  control('aem-route-plan-mode').value = 'driving';
  control('aem-route-radius').value = '3';
  await control('aem-route-plan').listeners.click();
  assert.equal(requests.length, 1);
  assert.deepEqual(requests[0].body.points, [[-112, 33], [-111.995, 33], [-111.993, 33], [-111.991, 33], [-111.99, 33]]);
  assert.ok(source.data);
  assert.equal(browserWindow.aemPlannedRoute.mode, 'driving');
  assert.equal(typeof render, 'function');
  render();
  assert.equal(requests.length, 1);
  sourceLoaded = true;
  render();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(requests[1].body.kind, 'Private parcels within 0.5 mile');
  assert.equal(requests[1].body.radius_miles, 0.5);
  assert.ok(requests.every((request) => !request.body.kind?.includes('plss')));
});
