// Read PMTiles index ranges only; no road tile payloads or archive writes.
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { PMTiles, tileIdToZxy, zxyToTileId } from 'pmtiles';

const run = promisify(execFile);
const archiveUrl = 'https://data.americanexplorationmaps.com/prospectors/western-prospectors-roads-v3.pmtiles';
const maxZoom = Number(process.argv[2] ?? 9);
if (!Number.isInteger(maxZoom) || maxZoom < 4 || maxZoom > 15) {
  throw new Error('Usage: node scripts/audit-western-roads.mjs [maximum zoom 4–15]');
}

// curl uses the environment's configured proxy; require exact partial content.
const source = {
  getKey: () => archiveUrl,
  async getBytes(offset, length, signal, etag) {
    const args = ['--fail', '--silent', '--show-error', '--max-time', '60',
      '--range', `${offset}-${offset + length - 1}`, '--write-out', '%{stderr}%{http_code}'];
    if (etag) args.push('--header', `If-Match: ${etag}`);
    args.push(archiveUrl);
    const { stdout, stderr } = await run('curl', args, {
      encoding: 'buffer', maxBuffer: length + 65536, signal
    });
    if (stderr.toString().trim() !== '206' || stdout.length !== length) {
      throw new Error(`Unexpected range response for ${offset}+${length}: HTTP ${stderr.toString().trim()}, ${stdout.length} bytes`);
    }
    return { data: stdout.buffer.slice(stdout.byteOffset, stdout.byteOffset + stdout.byteLength) };
  }
};

const archive = new PMTiles(source);
const header = await archive.getHeader();
const metadata = await archive.getMetadata();
const root = await archive.cache.getDirectory(source, header.rootDirectoryOffset, header.rootDirectoryLength, header);
const limit = zxyToTileId(maxZoom + 1, 0, 0);
const buckets = new Map();
let leafCount = 0;

function record(entry) {
  if (!entry.runLength) return;
  const [zoom, x, y] = tileIdToZxy(entry.tileId);
  if (zoom < header.minZoom || zoom > maxZoom) return;
  if (!buckets.has(zoom)) buckets.set(zoom, []);
  buckets.get(zoom).push({ bytes: entry.length, tile: [zoom, x, y], runLength: entry.runLength });
}

for (const entry of root) {
  if (entry.tileId >= limit) break;
  if (entry.runLength) {
    record(entry);
    continue;
  }
  const leaf = await archive.cache.getDirectory(source, header.leafDirectoryOffset + entry.offset, entry.length, header);
  leafCount++;
  for (const tile of leaf) {
    if (tile.tileId >= limit) break;
    record(tile);
  }
}

const zooms = [...buckets].sort(([a], [b]) => a - b).map(([zoom, entries]) => {
  entries.sort((a, b) => a.bytes - b.bytes);
  const percentile = (fraction) => entries[Math.floor((entries.length - 1) * fraction)].bytes;
  return {
    zoom, directoryEntries: entries.length,
    medianBytes: percentile(0.5), p95Bytes: percentile(0.95), p99Bytes: percentile(0.99),
    largest: entries.at(-1)
  };
});

console.log(JSON.stringify({
  archiveUrl, maxZoomAudited: maxZoom, leafDirectoriesRead: leafCount,
  archive: {
    minZoom: header.minZoom, maxZoom: header.maxZoom, bounds: [header.minLon, header.minLat, header.maxLon, header.maxLat],
    tileDataBytes: header.tileDataLength, tileEntries: header.numTileEntries,
    generator: metadata.generator, generatorOptions: metadata.generator_options,
    layers: metadata.vector_layers?.map(({ id, fields }) => ({ id, fields: Object.keys(fields || {}) }))
  },
  zooms
}, null, 2));
