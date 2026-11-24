import { classifyRings, VectorTile } from '@mapbox/vector-tile';
import geojsonvt from 'geojson-vt';
import { PbfReader } from 'pbf';
import { PMTiles } from 'pmtiles';
import polygonClipping from 'polygon-clipping';
import vtpbf from 'vt-pbf';

const origin = 'https://tiles.americanexplorationmaps.com';
const states = new Set(['az', 'ca', 'co', 'id', 'mt', 'nm', 'nv', 'or', 'ut', 'wa', 'wy']);
const archives = new Map();
const extent = 4096;
const clip = [[[0, 0], [extent, 0], [extent, extent], [0, extent], [0, 0]]];
let discovery;
let expires = 0;

function getStates() {
  if (!discovery || Date.now() >= expires) {
    expires = Date.now() + 300000;
    discovery = fetch(`${origin}/api/states/discover-v2`).then(response => {
      if (!response.ok) throw new Error('State discovery unavailable');
      return response.json();
    }).then(data => data.states).catch(error => {
      expires = 0;
      throw error;
    });
  }
  return discovery;
}

function tileBounds(z, x, y) {
  const width = 2 ** z;
  const lng = col => col / width * 360 - 180;
  const lat = row => Math.atan(Math.sinh(Math.PI * (1 - 2 * row / width))) * 180 / Math.PI;
  return [lng(x), lat(y + 1), lng(x + 1), lat(y)];
}

async function childTile(dataset, z, x, y) {
  if (dataset.url?.startsWith('pmtiles://')) {
    const url = new URL(dataset.url.slice('pmtiles://'.length));
    if (url.origin !== origin) throw new Error('Unexpected archive origin');
    if (!archives.has(url.href)) archives.set(url.href, new PMTiles(url.href));
    return (await archives.get(url.href).getZxy(z, x, y))?.data;
  }

  const url = new URL(dataset.tiles[0].replace('{z}', z).replace('{x}', x).replace('{y}', y));
  if (url.origin !== origin) throw new Error('Unexpected tile origin');
  const response = await fetch(url, { signal: AbortSignal.timeout(12000) });
  if (response.status === 404 || response.status === 204) return null;
  if (!response.ok) throw new Error(`Surface Management tile returned ${response.status}`);
  return response.arrayBuffer();
}

async function childFeatures(dataset, z, x, y) {
  const data = await childTile(dataset, z, x, y);
  if (!data?.byteLength) return [];
  const layer = new VectorTile(new PbfReader(new Uint8Array(data))).layers[dataset.sourceLayer];
  if (!layer) return [];

  const scale = extent / layer.extent;
  const width = 2 ** z;
  const unproject = ([px, py]) => [
    (x + px / extent) / width * 360 - 180,
    Math.atan(Math.sinh(Math.PI * (1 - 2 * (y + py / extent) / width))) * 180 / Math.PI
  ];
  const features = [];
  for (let i = 0; i < layer.length; i++) {
    const feature = layer.feature(i);
    if (feature.type !== 3) continue;
    const projected = classifyRings(feature.loadGeometry()).map(polygon =>
      polygon.map(ring => ring.map(({ x, y }) => [x * scale, y * scale])));
    // Take only the owning child tile's extent so its buffer doesn't duplicate fills.
    const clipped = polygonClipping.intersection(projected, clip);
    if (!clipped.length) continue;
    features.push({
      type: 'Feature', properties: feature.properties,
      geometry: { type: 'MultiPolygon', coordinates: clipped.map(polygon =>
        polygon.map(ring => ring.map(unproject))) }
    });
  }
  return features;
}

export default async function handler(req, res) {
  if (req.method !== 'GET') return res.status(405).end();
  const state = req.query.state;
  const [z, x, y] = ['z', 'x', 'y'].map(key =>
    /^\d+$/.test(req.query[key] ?? '') ? Number(req.query[key]) : NaN);
  if (!states.has(state) || ![4, 5].includes(z) ||
      ![x, y].every(value => Number.isInteger(value) && value >= 0 && value < 2 ** z)) {
    return res.status(400).end();
  }

  try {
    const entry = (await getStates())[state];
    const dataset = entry?.datasets?.surfaceManagement;
    if (!dataset || !Number.isInteger(dataset.minzoom) || dataset.minzoom <= z || dataset.minzoom > 6) {
      return res.status(404).end();
    }
    const childZoom = dataset.minzoom;
    const factor = 2 ** (childZoom - z);
    const [west, south, east, north] = entry.bounds;
    const children = [];
    for (let col = x * factor; col < (x + 1) * factor; col++) {
      for (let row = y * factor; row < (y + 1) * factor; row++) {
        const [left, bottom, right, top] = tileBounds(childZoom, col, row);
        if (left > east || right < west || bottom > north || top < south) continue;
        children.push(childFeatures(dataset, childZoom, col, row));
      }
    }
    const features = (await Promise.all(children)).flat();
    res.setHeader('Vercel-CDN-Cache-Control', 'public, s-maxage=86400, stale-while-revalidate=86400');
    const index = geojsonvt({ type: 'FeatureCollection', features }, { maxZoom: z, indexMaxZoom: 0, extent });
    const tile = index.getTile(z, x, y);
    if (!tile?.features.length) return res.status(204).end();

    res.setHeader('Content-Type', 'application/vnd.mapbox-vector-tile');
    return res.status(200).send(Buffer.from(vtpbf.fromGeojsonVt({ [dataset.sourceLayer]: tile }, { extent, version: 2 })));
  } catch (error) {
    console.error('Surface Management overview:', state, z, x, y, error.message);
    return res.status(502).end();
  }
}
