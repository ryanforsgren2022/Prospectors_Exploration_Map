"""Filter MVT claim features read-only, preserving retained feature/attribute bytes.
Unknown classifications are counted separately and omitted from the classified
non-closed layer. No Active-only filter, source rebuild, or data writes.
"""
from collections import Counter
import gzip
import struct


def varint(data, position=0):
    value = 0
    for shift in range(0, 70, 7):
        if position >= len(data):
            raise ValueError('Truncated protobuf varint')
        byte = data[position]
        position += 1
        value |= (byte & 127) << shift
        if not byte & 128:
            return value, position
    raise ValueError('Invalid protobuf varint')


def encode_varint(value):
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def fields(data):
    position = 0
    while position < len(data):
        start = position
        key, position = varint(data, position)
        number, wire = key >> 3, key & 7
        if number == 0:
            raise ValueError('Invalid protobuf field number')
        if wire == 0:
            value, position = varint(data, position)
        elif wire in (1, 5):
            length = 8 if wire == 1 else 4
            value = data[position:position + length]
            position += length
        elif wire == 2:
            length, position = varint(data, position)
            value = data[position:position + length]
            position += length
        else:
            raise ValueError('Unsupported protobuf wire type')
        if position > len(data):
            raise ValueError('Truncated protobuf field')
        yield number, wire, value, data[start:position]


def packed(data):
    position = 0
    while position < len(data):
        value, position = varint(data, position)
        yield value


def value_of(data):
    for number, wire, value, _ in fields(data):
        if number == 1 and wire == 2:
            return value.decode('utf-8')
        if number == 2 and wire == 5:
            return struct.unpack('<f', value)[0]
        if number == 3 and wire == 1:
            return struct.unpack('<d', value)[0]
        if number in (4, 5, 6, 7) and wire == 0:
            return value
    return None


def normalize(value, present=True):
    if not present:
        return None, 'missing'
    if value is None:
        return None, 'null'
    if not isinstance(value, str):
        return None, 'invalid'
    result = ' '.join(value.split()).casefold()
    return (result, None) if result else (None, 'blank')


def filter_claim_records(records, classification_field='CSE_DISP', id_field='OBJECTID'):
    """Return original record objects whose named classification is not Closed.

    Missing, null, blank and non-string values are reported separately and are
    not silently promoted to active/non-closed claims.
    """
    counts, unknown = Counter(), Counter()
    report = {
        'before': 0, 'after': 0, 'closed': 0, 'unknown': 0,
        'byClassification': {}, 'afterByClassification': {},
        'unknownReasons': {}, 'unknownFeatureIds': []
    }
    retained = []
    wanted = classification_field.strip().casefold()
    for record in records:
        report['before'] += 1
        attributes = record.get('attributes') or {}
        matches = [value for key, value in attributes.items()
                   if str(key).strip().casefold() == wanted]
        if len(matches) > 1 and any(value != matches[0] for value in matches[1:]):
            raise ValueError('Conflicting duplicate classification attribute keys')
        classification, reason = normalize(matches[0] if matches else None, bool(matches))
        if reason:
            report['unknown'] += 1
            unknown[reason] += 1
            if len(report['unknownFeatureIds']) < 20:
                report['unknownFeatureIds'].append({
                    'id': attributes.get(id_field), 'reason': reason
                })
        else:
            counts[classification] += 1
            if classification == 'closed':
                report['closed'] += 1
            else:
                report['after'] += 1
                retained.append(record)
    report['byClassification'] = dict(sorted(counts.items()))
    report['afterByClassification'] = {
        key: count for key, count in sorted(counts.items()) if key != 'closed'
    }
    report['unknownReasons'] = dict(sorted(unknown.items()))
    assert report['before'] == report['after'] + report['closed'] + report['unknown']
    return retained, report


def filter_claim_tile(payload, source_layer, classification_field='CSE_DISP'):
    compressed = payload[:2] == b'\x1f\x8b'
    tile = gzip.decompress(payload) if compressed else payload
    counts, unknown = Counter(), Counter()
    report = {'before': 0, 'after': 0, 'closed': 0, 'unknown': 0,
              'byClassification': {}, 'afterByClassification': {}, 'unknownReasons': {}, 'unknownFeatureIds': [],
              'sourceLayerFound': False}
    output = []
    for number, wire, layer_data, raw_layer in fields(tile):
        if number != 3 or wire != 2:
            output.append(raw_layer)
            continue
        parts = list(fields(layer_data))
        name = next((value.decode('utf-8') for n, w, value, _ in parts if n == 1 and w == 2), None)
        if name != source_layer:
            output.append(raw_layer)
            continue
        report['sourceLayerFound'] = True
        keys = [value.decode('utf-8') for n, w, value, _ in parts if n == 3 and w == 2]
        values = [value_of(value) for n, w, value, _ in parts if n == 4 and w == 2]
        retained = []
        for n, w, feature, raw in parts:
            if n != 2 or w != 2:
                retained.append(raw)
                continue
            report['before'] += 1
            attributes, feature_id, tags = {}, None, []
            for fn, fw, fv, _ in fields(feature):
                if fn == 1 and fw == 0:
                    feature_id = fv
                elif fn == 2 and fw == 2:
                    tags.extend(packed(fv))
                elif fn == 2 and fw == 0:
                    tags.append(fv)
            if len(tags) % 2:
                raise ValueError('Odd MVT feature tag count')
            for index in range(0, len(tags), 2):
                key_index, value_index = tags[index:index + 2]
                if key_index >= len(keys) or value_index >= len(values):
                    raise ValueError('MVT tag references missing attribute')
                name = keys[key_index].strip().casefold()
                if name != classification_field.strip().casefold():
                    continue
                if name in attributes and attributes[name] != values[value_index]:
                    raise ValueError('Conflicting duplicate classification attribute keys')
                attributes[name] = values[value_index]
            key = classification_field.strip().casefold()
            classification, reason = normalize(attributes.get(key), key in attributes)
            if reason:
                report['unknown'] += 1
                unknown[reason] += 1
                if len(report['unknownFeatureIds']) < 20:
                    report['unknownFeatureIds'].append({'id': feature_id, 'reason': reason})
            else:
                counts[classification] += 1
                if classification == 'closed':
                    report['closed'] += 1
                else:
                    report['after'] += 1
                    retained.append(raw)  # Original feature tags, values, geometry and ID bytes.
        content = b''.join(retained)
        output.append(encode_varint(26) + encode_varint(len(content)) + content)
    report['byClassification'] = dict(sorted(counts.items()))
    report['afterByClassification'] = {key: count for key, count in sorted(counts.items()) if key != 'closed'}
    report['unknownReasons'] = dict(sorted(unknown.items()))
    assert report['before'] == report['after'] + report['closed'] + report['unknown']
    if report['closed'] == 0 and report['unknown'] == 0:
        return payload, report
    content = b''.join(output)
    return (gzip.compress(content, mtime=0) if compressed else content), report
