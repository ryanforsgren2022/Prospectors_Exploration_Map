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
      append() {}, replaceChildren() {},
    });
    return controls.get(id);
  };
  const panel = {
    innerHTML: '', className: '', querySelector(selector) { return control(selector.slice(1)); },
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
  const browserWindow = {};
  const context = vm.createContext({
    map, window: browserWindow, document: { createElement: (tag) => tag === 'details' ? panel : { textContent: '' },
      body: { append() {} } },
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
  control('aem-route-origin').value = '33, -112';
  control('aem-route-destination').value = '33, -111.99';
  control('aem-route-plan-mode').value = 'driving';
  control('aem-route-radius').value = '3';
  await control('aem-route-plan').listeners.click();
  assert.equal(requests.length, 1);
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
