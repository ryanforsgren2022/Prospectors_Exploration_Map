import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { VectorTile } from '@mapbox/vector-tile';
import geojsonvt from 'geojson-vt';
import { PbfReader } from 'pbf';
import { PMTiles } from 'pmtiles';
import polygonClipping from 'polygon-clipping';
import vtpbf from 'vt-pbf';

const app = await readFile(new URL('../source-dist/app.js', import.meta.url), 'utf8');
const roadUrl = app.match(/const CONTINUOUS_ROADS_URL = '([^']+)'/)?.[1];
if (!roadUrl) throw new Error('The published western roads source is missing.');
const discovery = 'https://tiles.americanexplorationmaps.com/api/states/discover-v2';
const output = new URL('../public/beta-404b87eaa6a7b90cc88f57111d565a25/data/western-overview-v1/', import.meta.url);
const states = ['az', 'ca', 'co', 'id', 'mt', 'nm', 'nv', 'or', 'ut', 'wa', 'wy'];
const bounds = [-125, 31, -102, 49.1];
const majorRoads = new Set(['motorway', 'trunk']);

function coveringTiles([west, south, east, north], z) {
  const n = 2 ** z;
  const x = lng => Math.floor((lng + 180) / 360 * n);
  const y = lat => Math.floor((1 - Math.asinh(Math.tan(lat * Math.PI / 180)) / Math.PI) / 2 * n);
  const tiles = [];
  for (let col = x(west); col <= x(east); col++) {
    for (let row = y(north); row <= y(south); row++) tiles.push([z, col, row]);
  }
  return tiles;
}

function tileRectangle(z, x, y) {
  const n = 2 ** z;
  const lng = col => col / n * 360 - 180;
  const lat = row => Math.atan(Math.sinh(Math.PI * (1 - 2 * row / n))) * 180 / Math.PI;
  return [[
    [lng(x), lat(y)], [lng(x + 1), lat(y)], [lng(x + 1), lat(y + 1)],
    [lng(x), lat(y + 1)], [lng(x), lat(y)]
  ]];
}

async function fetchTile(url) {
  const response = await fetch(url, { signal: AbortSignal.timeout(18000) });
  if (response.status === 404 || response.status === 204) return null;
  if (!response.ok) throw new Error(`Tile HTTP ${response.status}: ${url}`);
  return response.arrayBuffer();
}

function decode(tile, layerName, coordinates, include = () => true) {
  if (!tile?.byteLength) return [];
  const layer = new VectorTile(new PbfReader(new Uint8Array(tile))).layers[layerName];
  const features = [];
  for (let i = 0; i < (layer?.length ?? 0); i++) {
    const feature = layer.feature(i);
    if (include(feature.properties)) {
      const [z, x, y] = coordinates;
      features.push(feature.toGeoJSON(x, y, z));
    }
  }
  return features;
}

// Join degree-two endpoints before simplifying so short pieces of a highway
// are kept as one continuous line at the overview scales.
function joinRoads(features) {
  const groups = new Map();
  for (const { geometry, properties } of features) {
    const { highway, ref = '' } = properties;
    const key = JSON.stringify([highway, ref]);
    if (!groups.has(key)) groups.set(key, []);
    const lines = geometry.type === 'LineString' ? [geometry.coordinates] : geometry.coordinates;
    groups.get(key).push(...lines);
  }

  const result = [];
  const pointKey = point => point.map(value => value.toFixed(6)).join(',');
  for (const [key, lines] of groups) {
    const [highway, ref] = JSON.parse(key);
    const endpoints = new Map();
    const unique = new Map();
    for (const line of lines) {
      if (line.length < 2) continue;
      const forward = line.map(pointKey).join(' ');
      const reverse = line.map(pointKey).reverse().join(' ');
      unique.set(forward < reverse ? forward : reverse, line);
    }
    const segments = [...unique.values()];
    const ends = segments.map(line => [pointKey(line[0]), pointKey(line.at(-1))]);
    for (const [index, [start, finish]] of ends.entries()) {
      for (const end of new Set([start, finish])) {
        if (!endpoints.has(end)) endpoints.set(end, []);
        endpoints.get(end).push(index);
      }
    }
    const visited = new Set();
    function follow(end) {
      const coordinates = [];
      while (endpoints.get(end).length === 2) {
        const index = endpoints.get(end).find(candidate => !visited.has(candidate));
        if (index === undefined) break;
        visited.add(index);
        const [start, finish] = ends[index];
        const line = start === end ? segments[index] : [...segments[index]].reverse();
        coordinates.push(...line.slice(1));
        end = start === end ? finish : start;
      }
      return coordinates;
    }
    for (const [index, segment] of segments.entries()) {
      if (visited.has(index)) continue;
      visited.add(index);
      const [start, finish] = ends[index];
      const coordinates = [...follow(start).reverse(), ...segment, ...follow(finish)];
      result.push({
        type: 'Feature', properties: { highway, ref, 'tippecanoe:minimumzoom': 4 },
        geometry: { type: 'LineString', coordinates }
      });
    }
  }
  return result;
}

const roadArchive = new PMTiles(roadUrl);
const stateResponse = await fetch(discovery, { signal: AbortSignal.timeout(18000) });
if (!stateResponse.ok) throw new Error(`State discovery HTTP ${stateResponse.status}`);
const registry = (await stateResponse.json()).states;
const roads = (await Promise.all(coveringTiles(bounds, 4).map(async coordinate => {
  const tile = await roadArchive.getZxy(...coordinate);
  return decode(tile?.data, 'roads', coordinate, props => majorRoads.has(props.highway));
}))).flat();
if (!roads.length) throw new Error('No roads found in the overview source.');

const borders = await Promise.all(states.map(async state => {
  const entry = registry[state];
  const dataset = entry?.datasets?.boundary;
  if (!dataset) throw new Error(`Missing boundary source for ${state}`);
  const archive = dataset.url?.startsWith('pmtiles://') ? new PMTiles(dataset.url.slice(10)) : null;
  const z = Math.max(4, dataset.minzoom);
  const lines = [];
  const polygons = [];
  const parts = await Promise.all(coveringTiles(entry.bounds, z).map(async coordinate => {
    const [z, x, y] = coordinate;
    const tile = archive
      ? (await archive.getZxy(z, x, y))?.data
      : await fetchTile(dataset.tiles[0].replace('{z}', z).replace('{x}', x).replace('{y}', y));
    return { coordinate, features: decode(tile, dataset.sourceLayer, coordinate) };
  }));
  for (const { coordinate, features } of parts) {
    for (const { geometry } of features) {
      if (geometry.type === 'LineString' || geometry.type === 'MultiLineString') {
        lines.push({ type: 'Feature', properties: { state }, geometry });
      } else if (geometry.type === 'Polygon' || geometry.type === 'MultiPolygon') {
        const clipped = polygonClipping.intersection(geometry.coordinates, tileRectangle(...coordinate));
        if (clipped.length) polygons.push(clipped);
      }
    }
  }
  if (polygons.length) {
    lines.push({
      type: 'Feature',
      properties: { state },
      geometry: { type: 'MultiPolygon', coordinates: polygonClipping.union(...polygons) }
    });
  }
  if (!lines.length) throw new Error(`No boundary features decoded for ${state}`);
  return lines;
}));

const createIndex = features => geojsonvt({ type: 'FeatureCollection', features }, { maxZoom: 4, indexMaxZoom: 3, extent: 4096 });
const roadIndex = createIndex(joinRoads(roads));
const boundaryIndex = createIndex(borders.flat());
for (const zoom of [2, 3]) {
  for (const [z, x, y] of coveringTiles(bounds, zoom)) {
    const layers = {};
    const roadTile = roadIndex.getTile(z, x, y);
    const boundaryTile = boundaryIndex.getTile(z, x, y);
    if (roadTile?.features.length) layers.roads = roadTile;
    if (boundaryTile?.features.length) layers.boundary = boundaryTile;
    const path = join(output.pathname, String(z), String(x), `${y}.pbf`);
    await mkdir(dirname(path), { recursive: true });
    await writeFile(path, vtpbf.fromGeojsonVt(layers, { version: 2, extent: 4096 }));
    console.log(z, x, y, Object.keys(layers).join(','));
  }
}
