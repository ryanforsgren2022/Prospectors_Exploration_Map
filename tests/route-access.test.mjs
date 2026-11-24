import assert from 'node:assert/strict';
import test from 'node:test';
import { PbfWriter } from 'pbf';
import { planViaNearbyNetwork, routeAccessGaps } from '../source-dist/route-access.mjs';

const start = [-112.5254274, 33.9691604];
const mine = [-112.51407, 33.99839];

function archiveWithRoads(roads) {
  const z = 13;
  const extent = 4096;
  const project = ([lng, lat]) => [
    (lng + 180) / 360 * 2 ** z,
    (1 - Math.asinh(Math.tan(lat * Math.PI / 180)) / Math.PI) / 2 * 2 ** z
  ];
  const [x, y] = project(mine).map(Math.floor);
  const encodePoint = point => project(point).map((coord, axis) =>
    Math.round((coord - [x, y][axis]) * extent));
  const zigzag = value => value < 0 ? -2 * value - 1 : 2 * value;
  const tile = new PbfWriter();
  tile.writeMessage(3, (features, layer) => {
    layer.writeStringField(1, 'roads');
    for (const [index, feature] of features.entries()) {
      layer.writeMessage(2, (item, writer) => {
        writer.writeVarintField(1, index + 1);
        writer.writePackedVarint(2, [0, index * 2, 1, index * 2 + 1]);
        writer.writeVarintField(3, 2);
        const [a, b] = item.points.map(encodePoint);
        writer.writePackedVarint(4, [9, ...a.map(zigzag), 10,
          zigzag(b[0] - a[0]), zigzag(b[1] - a[1])]);
      }, feature);
    }
    layer.writeStringField(3, 'highway');
    layer.writeStringField(3, 'access');
    for (const feature of features) {
      for (const value of [feature.highway, feature.access]) {
        layer.writeMessage(4, (text, writer) => writer.writeStringField(1, text), value);
      }
    }
    layer.writeVarintField(5, extent);
    layer.writeVarintField(15, 2);
  }, roads);
  const data = tile.finish();
  return {
    async getHeader() { return { maxZoom: z }; },
    async getZxy(zoom, col, row) { return zoom === z && col === x && row === y ? { data } : null; }
  };
}

test('off-network destination plans to a connected road and reports the gap separately', async () => {
  const roads = archiveWithRoads([
    { highway: 'track', access: 'private', points: [[-112.516, 33.997], [-112.512, 33.997]] },
    { highway: 'path', access: '', points: [[-112.516, 33.995], [-112.512, 33.995]] },
    { highway: 'track', access: '', points: [[-112.519, 33.991], [-112.515, 33.991]] },
    { highway: 'track', access: '', points: [[-112.519, 33.989], [-112.515, 33.989]] }
  ]);
  const points = [start, mine];
  const attempts = [];
  const result = await planViaNearbyNetwork(roads, points, 'driving', async adjusted => {
    attempts.push(adjusted);
    if (attempts.length === 1) throw new Error('No connected route found in the available network');
    return { geometry: { type: 'LineString', coordinates: adjusted } };
  }, new AbortController().signal);

  assert.equal(attempts.length, 2);
  assert.deepEqual(attempts[0][0], start);
  assert(Math.abs(attempts[0][1][1] - 33.991) < 0.00002);
  assert(Math.abs(result.adjusted[1][1] - 33.989) < 0.00002);
  const [gap] = routeAccessGaps(points, result, result.data.geometry.coordinates);
  assert.equal(gap.index, 1);
  assert.deepEqual(gap.point, mine);
  assert.deepEqual(gap.reached, result.adjusted[1]);
  assert(gap.meters > 1000);
  assert.deepEqual(points, [start, mine]);
});

test('no nearby candidate does not retry the unchanged route', async () => {
  const result = await planViaNearbyNetwork(archiveWithRoads([]), [start, mine], 'hiking', () => {
    assert.fail('unchanged points should not be sent again');
  }, new AbortController().signal);
  assert.equal(result, null);
});
