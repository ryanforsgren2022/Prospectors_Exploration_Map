import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { test } from 'node:test';

class Element {
  constructor() { this.children = []; this.listeners = {}; this.value = ''; }
  append(...children) { this.children.push(...children); }
  setAttribute() {}
  replaceChildren(...children) { this.children = children; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
}
function harness(features = [], overrides = {}) {
  const form = new Element(), input = new Element(), navigations = [], messages = [], calls = [];
  let geocodes = 0;
  const context = vm.createContext({ URL, AbortController, document: { createElement: () => new Element() } });
  vm.runInContext(readFileSync(new URL('../source-dist/search-v2.js', import.meta.url), 'utf8'), context);
  const options = {
    form, input, status: (...args) => messages.push(args), prepare: async () => {},
    parseState: value => ({ value, state: 'az', explicitState: false }),
    parseCoordinates: () => null, parsePlss: () => null,
    stateSelect: { value: '' }, countyInput: { value: '' },
    fetch: async url => { calls.push(url); return { ok: true, json: async () => ({ features }) }; },
    geocode: async () => { geocodes++; return null; }, navigate: async f => navigations.push(f), ...overrides
  };
  context.installAemUnifiedSearch(options);
  return { ...options, calls, messages, navigations, geocodes: () => geocodes,
    submit: async value => { input.value = value; await form.listeners.submit({ preventDefault() {} }); } };
}
const feature = id => ({ type: 'Feature', id, properties: { display_label: '001-020', county: id, state_code: 'az', search_type: 'parcels' }, geometry: { type: 'Point', coordinates: [-111, 32] } });
test('a single match navigates automatically; APN punctuation and leading zeros reach the API intact', async () => {
  const h = harness([feature('Pima')]);
  await h.submit('APN:001-020');
  assert.equal(h.calls[0].searchParams.get('q'), '001-020');
  assert.equal(h.calls[0].searchParams.get('kind'), 'parcels');
  assert.equal(h.calls[0].searchParams.has('state'), false);
  assert.equal(h.navigations.length, 1);
});
test('duplicate APNs wait for the user to choose the correct county', async () => {
  const h = harness([feature('Pima'), feature('Yavapai')]);
  await h.submit('APN 001-020');
  assert.equal(h.navigations.length, 0);
  const buttons = h.form.children[0].children;
  assert.equal(buttons.length, 2);assert.match(buttons[1].textContent, /Yavapai/);
  await buttons[1].listeners.click();assert.equal(h.navigations[0].id, 'Yavapai');
});
test('ambiguous place or address matches can be selected by the route point picker', async () => {
  const h = harness([], { geocode: async () => [
    { address: 'Center Street, Arizona', location: { x: -111, y: 32 } },
    { address: 'Center Street, Utah', location: { x: -112, y: 38 } },
  ] });
  await h.submit('Center Street');
  assert.equal(h.navigations.length, 0);
  const buttons = h.form.children[0].children;
  assert.deepEqual(buttons.map(button => button.textContent), ['Center Street, Arizona', 'Center Street, Utah']);
  await buttons[1].listeners.click();
  assert.deepEqual(Array.from(h.navigations[0].geometry.coordinates), [-112, 38]);
});
test('a matching local saved pin can be found from the same search field', async () => {
  const pin = feature('Saved pin');
  const h = harness([], { localMatches: value => value === 'Trailhead' ? [pin] : [] });
  await h.submit('Trailhead');
  assert.equal(h.calls.length, 0);
  assert.equal(h.navigations[0], pin);
});
test('explicit APNs never fall through to address geocoding when their index is pending', async () => {
  const h = harness([], { fetch: async () => ({ ok: true, json: async () => ({ features: [], pending: [{ state: 'az' }] }) }) });
  await h.submit('APN 001-020');assert.equal(h.geocodes(), 0);assert.match(h.messages.at(-1)[0], /still being indexed/);
});
test('state and county filters are shared for all supported states', async () => {
  for (const state of ['az','ca','co','id','mt','nm','nv','or','ut','wa','wy']) {
    const h = harness([feature('Example')], { stateSelect: { value: state }, countyInput: { value: 'Example County' } });
    await h.submit('APN 001');assert.equal(h.calls[0].searchParams.get('state'), state);assert.equal(h.calls[0].searchParams.get('county'), 'Example County');
  }
});
test('a missing claim serial uses the state lookup before considering an address', async () => {
  const claim = { ...feature('Nevada claim'), properties: { search_type: 'claims' } };
  const lookups = [];
  const h = harness([], {
    findClaimBySerial: async (serial, state) => {
      lookups.push([serial, state]);
      return claim;
    }
  });
  await h.submit('NV105216280');
  assert.equal(h.calls[0].searchParams.get('kind'), 'claims');
  assert.deepEqual(lookups, [['NV105216280', '']]);
  assert.deepEqual(h.navigations, [claim]);
  assert.equal(h.geocodes(), 0);
});

test('late search responses cannot navigate after the user changes the query', async () => {
  let release;
  const h = harness([], { fetch: () => new Promise(resolve => { release = () => resolve({ ok: true, json: async () => ({ features: [feature('Old')] }) }); }) });
  const pending = h.submit('APN 001');await new Promise(resolve => setImmediate(resolve));
  h.input.listeners.input();release();await pending;assert.equal(h.navigations.length, 0);
});
test('a pin opens with a fresh summary and keeps full records collapsed without saving a snapshot', async () => {
  let writes = 0;
  const groups = {
    parcels: { status: 'unavailable', features: [] },
    claims: { status: 'ok', features: [] },
    surfaceManagement: { status: 'ok', features: [{ properties: { MGMT_AGNCY: 'BLM', OBJECTID: 456 } }] },
    withdrawalsAuthorized: { status: 'ok', features: [{ properties: { CSE_NR: 'ABC123' } }] }
  };
  const context = vm.createContext({ URL, URLSearchParams, Number, Object, String, Promise,
    document: { createElement: () => new Element() },
    researchLocationRequest: 0, researchLocationCard: {}, researchCoordinates: {}, researchLocationTitle: {},
    researchResults: new Element(), researchDetails: { open: true }, researchDetailSections: new Element(),
    SURFACE_MANAGEMENT_ALIASES: { MGMT_AGNCY: { BLM: 'BLM' } },
    localStorage: { setItem() { writes++; } },
    fetch: async () => ({ ok: true, json: async () => ({ status: 'ok', groups }) }), countyAtPoint: async () => 'Pima',
    researchTextResult: (label, value) => ({ label, value }), researchLinkResult: (label, value, href) => ({ label, value, href }),
    firstResearchValue: (p, keys) => keys.map(k => p[k]).find(Boolean) || '',
    formatMeridian: () => '', formatTownship: () => '', formatRange: () => '', formatSection: () => '',
    aemParcelPinDetails: () => ({})
  });
  vm.runInContext(readFileSync(new URL('../source-dist/research-v2.js', import.meta.url), 'utf8'), context);
  await context.aemOpenResearchV2({ lng: -111, lat: 32 });
  assert.equal(writes, 0);
  assert.deepEqual(Object.keys(context.activeResearchLocation).sort(), ['lat', 'lng', 'name']);
  assert.equal(context.researchCoordinates.textContent, '32.00000, -111.00000');
  assert.deepEqual(context.researchResults.children, [
    { label: 'Land manager', value: 'BLM' },
    { label: 'Mining claims', value: 'None found' },
    { label: 'Withdrawals', value: '1 found · partial coverage' },
    { label: 'Parcels', value: 'Lookup unavailable' }
  ]);
  assert.equal(context.researchDetails.open, false);
  assert.equal(context.researchDetails.hidden, false);
  const sections = context.researchDetailSections.children;
  assert.deepEqual(sections.map(section => section.children[0].textContent),
    ['Land status', 'Mining claims', 'Property', 'Location / PLSS']);
  assert.equal(sections[0].children[1].children.find(row => row.label.endsWith('OBJECTID')).value, '456');
  assert.match(sections[2].children[1].children[0].value, /unavailable/);

  groups.claims.features = [
    { id: 1, properties: { CSE_NR: 'NV105216280', CSE_NAME: 'WR 195', CSE_DISP: 'Active' } },
    { id: 2, properties: { CSE_DISP: 'Active' } }
  ];
  await context.aemOpenResearchV2({ lng: -114.043913, lat: 41.745461 });
  const claimSummary = context.researchResults.children[1];
  assert.equal(claimSummary.value, '2 found · View BLM records');
  const pointQuery = new URL(claimSummary.href);
  assert.equal(pointQuery.hostname, 'nlsdbpubgis.blm.gov');
  assert.equal(pointQuery.searchParams.get('geometry'), '-114.043913,41.745461');
  assert.equal(pointQuery.searchParams.get('spatialRel'), 'esriSpatialRelIntersects');
  assert.equal(pointQuery.searchParams.get('f'), 'html');
  const claimRows = context.researchDetailSections.children[1].children[1].children;
  assert.equal(new URL(claimRows[1].href).searchParams.get('where'), "CSE_NR='NV105216280'");
  assert.equal(claimRows[2].href, undefined);
  assert.equal(new URL(context.blmClaimRecordUrl({ LEG_CSE_NR: 'AMC 012345' })).searchParams.get('where'),
    "LEG_CSE_NR='AMC 012345'");
  assert.equal(context.blmClaimRecordUrl({ CSE_NR: "NV' OR 1=1" }), '');

  context.researchDetails.open = true;
  context.fetch = async () => ({ ok: true, json: async () => ({ status: 'outside_supported_states' }) });
  await context.aemOpenResearchV2({ lng: -112, lat: 33 }, feature('Pima'));
  assert.equal(context.researchLocationTitle.textContent, '001-020');
  assert.equal(context.researchResults.textContent, 'Outside supported map coverage.');
  assert.equal(context.researchDetails.open, false);
  assert.deepEqual(context.researchDetailSections.children.map(section => section.children[0].textContent),
    ['Selected result', 'Location']);
});
