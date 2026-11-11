#!/usr/bin/env python3
"""Build candidate z4–6 MBTiles by filtering existing MVT features in place.

The existing tile geometry, IDs, and attributes are copied without re-tiling.
Only features whose recorded minimum zoom exceeds the tile zoom are removed.
"""
import gzip
import json
import os
import sqlite3
import struct
import sys
from collections import Counter


def varint(data, pos):
    value = shift = 0
    while True:
        if pos >= len(data) or shift > 63:
            raise ValueError('Invalid protobuf varint')
        byte = data[pos]
        pos += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value, pos
        shift += 7


def encode_varint(value):
    out = bytearray()
    while value >= 128:
        out.append((value & 127) | 128)
        value >>= 7
    out.append(value)
    return bytes(out)


def fields(data):
    pos = 0
    while pos < len(data):
        start = pos
        tag, pos = varint(data, pos)
        number, wire = tag >> 3, tag & 7
        if not number:
            raise ValueError('Invalid protobuf field')
        if wire == 0:
            payload_start = pos
            _, pos = varint(data, pos)
            payload_end = pos
        elif wire == 1:
            payload_start, pos = pos, pos + 8
            payload_end = pos
        elif wire == 2:
            size, pos = varint(data, pos)
            payload_start, pos = pos, pos + size
            payload_end = pos
        elif wire == 5:
            payload_start, pos = pos, pos + 4
            payload_end = pos
        else:
            raise ValueError(f'Unsupported protobuf wire type {wire}')
        if pos > len(data):
            raise ValueError('Truncated protobuf field')
        yield number, wire, start, pos, payload_start, payload_end


def packed_varints(data):
    values, pos = [], 0
    while pos < len(data):
        value, pos = varint(data, pos)
        values.append(value)
    return values


def numeric_value(data):
    values = list(fields(data))
    if len(values) != 1:
        raise ValueError('Ambiguous MVT value')
    number, wire, _, _, start, end = values[0]
    if wire != 0 or number not in (4, 5, 6):
        raise ValueError('Minimum zoom must be an integer MVT value')
    value, _ = varint(data, start)
    if number == 6:
        value = (value >> 1) ^ -(value & 1)
    elif number == 4 and value >= 1 << 63:
        value -= 1 << 64
    if not 4 <= value <= 15:
        raise ValueError('Unexpected minimum zoom')
    return value


def delimited(number, payload):
    return encode_varint((number << 3) | 2) + encode_varint(len(payload)) + payload


def filter_layer(data, zoom):
    data = memoryview(data)
    layer_fields = list(fields(data))
    names = [bytes(data[s:e]).decode() for n, w, _, _, s, e in layer_fields if n == 1 and w == 2]
    if names != ['roads']:
        raise ValueError(f'Unexpected vector layer: {names}')
    keys = [bytes(data[s:e]).decode() for n, w, _, _, s, e in layer_fields if n == 3 and w == 2]
    values = [data[s:e] for n, w, _, _, s, e in layer_fields if n == 4 and w == 2]
    if keys.count('tippecanoe:minimumzoom') != 1:
        raise ValueError('Expected one minimum zoom key')
    minzoom_key = keys.index('tippecanoe:minimumzoom')
    used_values, value_indexes = [], {}
    result = bytearray()
    stats = Counter()

    # Emit other layer fields and keys unchanged. Feature tag value indices are
    # remapped while rebuilding a dictionary containing only retained values.
    for number, _, start, end, _, _ in layer_fields:
        if number not in (2, 4):
            result.extend(data[start:end])
    for number, wire, _, _, start, end in layer_fields:
        if number != 2:
            continue
        if wire != 2:
            raise ValueError('Invalid MVT feature wire type')
        feature = data[start:end]
        feature_fields = list(fields(feature))
        tag_fields = [field for field in feature_fields if field[0] == 2]
        if len(tag_fields) != 1 or tag_fields[0][1] != 2:
            raise ValueError('Expected one packed feature tag field')
        _, _, _, _, ts, te = tag_fields[0]
        tags = packed_varints(feature[ts:te])
        if len(tags) % 2:
            raise ValueError('Odd number of feature tags')
        minimum = None
        for i in range(0, len(tags), 2):
            key, value = tags[i:i+2]
            if key >= len(keys) or value >= len(values):
                raise ValueError('MVT tag index out of range')
            if key == minzoom_key:
                if minimum is not None:
                    raise ValueError('Duplicate minimum zoom tag')
                minimum = numeric_value(values[value])
        if minimum is None:
            raise ValueError('Feature has no minimum zoom')
        stats['input'] += 1
        if minimum > zoom:
            stats['excluded'] += 1
            continue
        new_tags = bytearray()
        for i in range(0, len(tags), 2):
            key, value = tags[i:i+2]
            if value not in value_indexes:
                value_indexes[value] = len(used_values)
                used_values.append(value)
            new_tags.extend(encode_varint(key))
            new_tags.extend(encode_varint(value_indexes[value]))
        updated = bytearray()
        for field, _, fs, fe, _, _ in feature_fields:
            if field == 2:
                updated.extend(delimited(2, new_tags))
            else:
                updated.extend(feature[fs:fe])
        result.extend(delimited(2, updated))
        stats['retained'] += 1
    for index in used_values:
        result.extend(delimited(4, values[index]))
    return bytes(result), stats


def filter_tile(data, zoom):
    data = memoryview(data)
    result = bytearray()
    stats = Counter()
    layers = 0
    for number, wire, start, end, payload_start, payload_end in fields(data):
        if number == 3 and wire == 2:
            layer, layer_stats = filter_layer(data[payload_start:payload_end], zoom)
            result.extend(delimited(3, layer))
            stats.update(layer_stats)
            layers += 1
        else:
            result.extend(data[start:end])
    if layers != 1:
        raise ValueError(f'Expected one roads layer, found {layers}')
    return bytes(result), stats


def read_directory(data):
    pos = 0
    count, pos = varint(data, pos)
    entries, last_id = [], 0
    for _ in range(count):
        delta, pos = varint(data, pos)
        last_id += delta
        entries.append([last_id, 0, 0, 0])
    for column in (3, 2, 1):
        for i in range(count):
            value, pos = varint(data, pos)
            if column == 1:
                value = entries[i-1][1] + entries[i-1][2] if value == 0 and i else value - 1
            entries[i][column] = value
    return entries


def tile_coordinates(tile_id):
    zoom = (3 * tile_id + 1).bit_length() - 1
    zoom //= 2
    t = tile_id - ((1 << (2 * zoom)) - 1) // 3
    x = y = 0
    scale = 1
    while scale < 1 << zoom:
        rx = (t // 2) & 1
        ry = (t ^ rx) & 1
        if ry == 0:
            if rx:
                x, y = scale - 1 - x, scale - 1 - y
            x, y = y, x
        x += scale * rx
        y += scale * ry
        t //= 4
        scale *= 2
    return zoom, x, y


def build(original, output):
    output_exists = os.path.exists(output)
    with open(original, 'rb') as src:
        header = src.read(127)
        if header[:8] != b'PMTiles\x03' or header[97:100] != bytes((2, 2, 1)):
            raise ValueError('Expected PMTiles v3 with gzip-compressed MVT')
        root_offset, root_len, meta_offset, meta_len, leaf_offset, _, tile_offset = struct.unpack_from('<7Q', header, 8)
        def read(offset, size):
            src.seek(offset)
            data = src.read(size)
            if len(data) != size:
                raise ValueError('Truncated archive')
            return data
        metadata = json.loads(gzip.decompress(read(meta_offset, meta_len)))
        root = read_directory(gzip.decompress(read(root_offset, root_len)))
        limit = ((1 << 14) - 1) // 3  # first zoom-7 Hilbert ID
        entries = []
        for tile_id, offset, length, run in root:
            if tile_id >= limit:
                break
            if run:
                entries.append((tile_id, offset, length, run))
            else:
                entries.extend(read_directory(gzip.decompress(read(leaf_offset + offset, length))))

        db = sqlite3.connect(output)
        if output_exists:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'metadata', 'tiles'} <= tables:
                raise ValueError('Existing output is not a resumable MBTiles database')
            existing = set(db.execute('SELECT zoom_level, tile_column, tile_row FROM tiles'))
            if any(not 4 <= z <= 6 for z, _, _ in existing):
                raise ValueError('Existing MBTiles contains rows outside zooms 4–6')
            print(json.dumps({'resume': True, 'existingTiles': len(existing)}), flush=True)
        else:
            db.execute('CREATE TABLE metadata (name text, value text)')
            db.execute('CREATE TABLE tiles (zoom_level integer, tile_column integer, tile_row integer, tile_data blob)')
            db.execute('CREATE UNIQUE INDEX tile_index ON tiles (zoom_level, tile_column, tile_row)')
            rows = {'name': 'AEM Western Roads Overview Candidate', 'format': 'pbf', 'type': 'overlay',
                    'version': '1', 'minzoom': '4', 'maxzoom': '6', 'bounds': metadata.get('bounds', '-124.737042,31.239763,-101.696897,49.222996'),
                    'attribution': metadata.get('attribution', 'OpenStreetMap'),
                    'json': json.dumps({'vector_layers': metadata['vector_layers']}, separators=(',', ':'))}
            db.executemany('INSERT INTO metadata VALUES (?, ?)', rows.items())
            existing = set()
        count = len(existing)
        for tile_id, offset, length, run in entries:
            for current in range(tile_id, min(tile_id + run, limit)):
                z, x, y = tile_coordinates(current)
                if not 4 <= z <= 6:
                    continue
                db_row = (z, x, (1 << z) - 1 - y)
                if db_row in existing:
                    continue
                data = gzip.decompress(read(tile_offset + offset, length))
                filtered, stats = filter_tile(data, z)
                compressed = gzip.compress(filtered, compresslevel=6, mtime=0)
                if len(compressed) > 2000000:
                    raise ValueError(f'Tile {z}/{x}/{y} exceeds 2 MB: {len(compressed)} bytes')
                db.execute('INSERT INTO tiles VALUES (?,?,?,?)', (*db_row, compressed))
                db.commit()
                print(json.dumps({'tile': [z, x, y], 'beforeBytes': length, 'afterBytes': len(compressed), **stats}), flush=True)
                count += 1
                existing.add(db_row)
        if count != 40:
            raise ValueError(f'Expected 40 overview tiles, found {count}')
        db.close()


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('Usage: filter-road-overview-tiles.py ORIGINAL.pmtiles NEW-OVERVIEW.mbtiles')
    build(sys.argv[1], sys.argv[2])
