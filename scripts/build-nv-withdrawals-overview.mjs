import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { PMTiles } from 'pmtiles';
import { VectorTile } from '@mapbox/vector-tile';
import Pbf from 'pbf';
import geojsonvt from 'geojson-vt';
import vtpbf from 'vt-pbf';

const archive = new PMTiles(
  'https://tiles.americanexplorationmaps.com/api/vm-data/nv/withdrawals.pmtiles'
);
const collections = {
  withdrawals_authorized: [],
  withdrawals_pending: []
};

// Nevada occupies these five zoom-6 tiles. They contain the complete published
// withdrawal features needed to derive a small, generalized zoom-4 overview.
for (const [x, y] of [[10, 23], [10, 24], [11, 23], [11, 24], [11, 25]]) {
  const tile = await archive.getZxy(6, x, y);
  if (!tile?.data) continue;
  const vectorTile = new VectorTile(new Pbf(tile.data));
  for (const name of Object.keys(collections)) {
    const layer = vectorTile.layers[name];
    if (!layer) continue;
    for (let index = 0; index < layer.length; index += 1) {
      collections[name].push(layer.feature(index).toGeoJSON(x, y, 6));
    }
  }
}

const output = join(process.cwd(), 'source-dist/data/nv-withdrawals-overview/4');
await mkdir(output, { recursive: true });

const indexes = Object.fromEntries(Object.entries(collections).map(([name, features]) => [
  name,
  geojsonvt({ type: 'FeatureCollection', features }, {
    maxZoom: 4,
    indexMaxZoom: 4,
    indexMaxPoints: 0,
    tolerance: 3,
    buffer: 64
  })
]));

for (const x of [2, 3]) {
  for (const y of [5, 6]) {
    const layers = Object.fromEntries(Object.entries(indexes)
      .map(([name, index]) => [name, index.getTile(4, x, y)])
      .filter(([, tile]) => tile?.features.length));
    if (!Object.keys(layers).length) continue;
    const directory = join(output, String(x));
    await mkdir(directory, { recursive: true });
    await writeFile(join(directory, `${y}.pbf`), vtpbf.fromGeojsonVt(layers));
  }
}
