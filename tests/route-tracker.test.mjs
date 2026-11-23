import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../source-dist/route-tracker.js', import.meta.url), 'utf8')
  .replace(/aemInstallRouteTracker\(map\);\s*$/, '');
const context = vm.createContext({ Date, Math, crypto: { randomUUID: () => 'trip-1' } });
vm.runInContext(source, context);
const get = (expression) => vm.runInContext(expression, context);

test('one trip keeps driving and hiking segments and distance', () => {
  const trip = get('aemRouteCreateTrip()');
  const add = get('aemRouteAddPoint');
  const mode = get('aemRouteSetMode');
  assert.equal(add(trip, { lng: -111, lat: 33, time: 1000, accuracy: 5, elevation: 100 }), true);
  assert.equal(add(trip, { lng: -110.999, lat: 33, time: 11000, accuracy: 5, elevation: 110 }), true);
  mode(trip, 'hiking');
  assert.equal(add(trip, { lng: -110.998, lat: 33, time: 21000, accuracy: 5, elevation: 103 }), true);
  assert.equal(trip.segments.map((part) => part.mode).join(','), 'driving,hiking');
  assert.ok(trip.distanceMeters > 150);
  assert.equal(trip.elevationGainMeters, 10);
  assert.equal(trip.elevationLossMeters, 7);
  assert.equal(trip.lowElevationMeters, 100);
  assert.equal(trip.highElevationMeters, 110);
});

test('auto mode requires sustained motion and ignores stopped traffic', () => {
  const auto = get('aemRouteAutoMode');
  assert.equal(auto(0, 'driving', null).mode, 'driving');
  let candidate = null, mode = 'driving';
  for (let sample = 0; sample < 8; sample++) {
    const result = auto(1.2, mode, candidate, sample * 10000);
    mode = result.mode;
    candidate = result.candidate;
  }
  assert.equal(mode, 'hiking');
});

test('rejects poor GPS fixes and impossible jumps', () => {
  const trip = get('aemRouteCreateTrip()');
  const add = get('aemRouteAddPoint');
  assert.equal(add(trip, { lng: -111, lat: 33, time: 1000, accuracy: 120 }), false);
  assert.equal(add(trip, { lng: -111, lat: 33, time: 1000, accuracy: 5 }), true);
  assert.equal(add(trip, { lng: -110, lat: 33, time: 2000, accuracy: 5 }), false);
  assert.equal(trip.distanceMeters, 0);
});
