import { VectorTile } from '@mapbox/vector-tile';
import { PbfReader } from 'pbf';

const MAX_ACCESS_METERS = 1609.344;
const ROAD_TYPES = new Set([
  'motorway', 'motorway_link', 'trunk', 'trunk_link', 'primary', 'primary_link',
  'secondary', 'secondary_link', 'tertiary', 'tertiary_link', 'unclassified',
  'residential', 'living_street', 'service', 'track', 'road'
]);
const TRAIL_TYPES = new Set(['path', 'footway', 'pedestrian', 'steps', 'bridleway', 'cycleway']);
const NO_ACCESS = new Set(['no', 'private']);

function allowed(properties, mode) {
  if (NO_ACCESS.has(properties.access)) return false;
  const highway = properties.highway;
  if (mode === 'driving') {
    return ROAD_TYPES.has(highway) &&
      ![properties.motor_vehicle, properties.motorcar, properties.vehicle].some(value => NO_ACCESS.has(value));
  }
  return (ROAD_TYPES.has(highway) || TRAIL_TYPES.has(highway)) &&
    !/^(motorway|trunk)(_|$)/.test(highway) && !NO_ACCESS.has(properties.foot);
}

function tileXY([lng, lat], z) {
  const scale = 2 ** z;
  const radians = Math.max(-85.05112878, Math.min(85.05112878, lat)) * Math.PI / 180;
  const clamp = value => Math.max(0, Math.min(scale - 1, Math.floor(value)));
  return [
    clamp((lng + 180) / 360 * scale),
    clamp((1 - Math.asinh(Math.tan(radians)) / Math.PI) / 2 * scale)
  ];
}

function distanceScale(lat) {
  return [111195 * Math.max(0.01, Math.cos(lat * Math.PI / 180)), 111195];
}

function closestOnSegment(point, start, end, [lngScale, latScale]) {
  const x = (start[0] - point[0]) * lngScale;
  const y = (start[1] - point[1]) * latScale;
  const dx = (end[0] - start[0]) * lngScale;
  const dy = (end[1] - start[1]) * latScale;
  const squared = dx * dx + dy * dy;
  const t = squared ? Math.max(0, Math.min(1, -(x * dx + y * dy) / squared)) : 0;
  return {
    point: [start[0] + (end[0] - start[0]) * t, start[1] + (end[1] - start[1]) * t],
    meters: Math.hypot(x + t * dx, y + t * dy)
  };
}

async function accessCandidates(archive, point, mode, z, tiles, signal) {
  const scale = distanceScale(point[1]);
  const lngOffset = MAX_ACCESS_METERS / scale[0];
  const latOffset = MAX_ACCESS_METERS / scale[1];
  const [west, north] = tileXY([point[0] - lngOffset, point[1] + latOffset], z);
  const [east, south] = tileXY([point[0] + lngOffset, point[1] - latOffset], z);
  const nearby = [];
  for (let x = west; x <= east; x++) {
    for (let y = north; y <= south; y++) {
      const key = `${x}/${y}`;
      if (!tiles.has(key)) {
        tiles.set(key, archive.getZxy(z, x, y, signal).then(tile => {
          if (!tile) return [];
          const layer = new VectorTile(new PbfReader(new Uint8Array(tile.data))).layers.roads;
          return Array.from({ length: layer?.length ?? 0 }, (_, i) => layer.feature(i))
            .filter(feature => feature.type === 2 && allowed(feature.properties, mode))
            .map(feature => ({
              id: feature.properties.osm_id ?? feature.id,
              geometry: feature.toGeoJSON(x, y, z).geometry
            }));
        }));
      }
      nearby.push(tiles.get(key));
    }
  }
  const byRoad = new Map();
  for (const { id, geometry } of (await Promise.all(nearby)).flat()) {
    const lines = geometry.type === 'LineString' ? [geometry.coordinates] : geometry.coordinates;
    const key = id ?? geometry;
    let best = byRoad.get(key);
    for (const line of lines) {
      for (let i = 1; i < line.length; i++) {
        const candidate = closestOnSegment(point, line[i - 1], line[i], scale);
        if (candidate.meters <= MAX_ACCESS_METERS && (!best || candidate.meters < best.meters)) best = candidate;
      }
    }
    if (best) byRoad.set(key, best);
  }
  return [...byRoad.values()].sort((a, b) => a.meters - b.meters).slice(0, 3);
}

export async function planViaNearbyNetwork(archive, points, mode, plan, signal) {
  const z = Math.min(13, (await archive.getHeader()).maxZoom);
  const tiles = new Map();
  const candidates = await Promise.all(points.map(point => accessCandidates(archive, point, mode, z, tiles, signal)));
  const snapLimit = mode === 'driving' ? 150 : 200;
  const preferred = candidates.map((items, index) => items[0]?.meters > snapLimit ? items[0].point : points[index]);
  const nearest = candidates.map((items, index) => items[0]?.point ?? points[index]);
  const alternate = candidates.map((items, index) => items[0]?.meters > snapLimit
    ? (items[1] ?? items[0]).point : nearest[index]);
  const seen = new Set([JSON.stringify(points)]);
  for (const adjusted of [preferred, nearest, alternate]) {
    signal.throwIfAborted();
    const key = JSON.stringify(adjusted);
    if (seen.has(key)) continue;
    seen.add(key);
    try {
      const data = await plan(adjusted);
      const changed = adjusted.map((point, index) => JSON.stringify(point) !== JSON.stringify(points[index]));
      return { data, adjusted, changed };
    } catch (error) {
      if (![
        'No connected road or trail near a route point',
        'No connected route found in the available network',
        'Route points resolve to the same road or trail node'
      ].includes(error.message)) throw error;
    }
  }
  return null;
}

export function routeAccessGaps(points, { adjusted, changed }, coordinates) {
  const gaps = [];
  for (let index = 0; index < points.length; index++) {
    if (!changed[index]) continue;
    const point = points[index];
    const candidate = adjusted[index];
    const [lngScale, latScale] = distanceScale(candidate[1]);
    function distance(position, origin) {
      return Math.hypot((position[0] - origin[0]) * lngScale, (position[1] - origin[1]) * latScale);
    }
    let reached = index === 0 ? coordinates[0] : coordinates.at(-1);
    if (index > 0 && index < points.length - 1) {
      let nearest = Infinity;
      for (const position of coordinates) {
        const meters = distance(position, candidate);
        if (meters >= nearest) continue;
        reached = position;
        nearest = meters;
      }
    }
    const meters = distance(point, reached);
    if (meters > 25) gaps.push({ index, point, reached, meters });
  }
  return gaps;
}
