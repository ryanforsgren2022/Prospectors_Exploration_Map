import importlib.util
from pathlib import Path


spec = importlib.util.spec_from_file_location('road_filter', Path(__file__).parents[1] / 'scripts' / 'filter-road-overview-tiles.py')
road = importlib.util.module_from_spec(spec)
spec.loader.exec_module(road)


def number(field, value):
    return road.encode_varint(field << 3) + road.encode_varint(value)


def feature(minimum_index, name_index, geometry):
    tags = b''.join(road.encode_varint(x) for x in (0, minimum_index, 1, name_index))
    return number(1, 42) + road.delimited(2, tags) + number(3, 2) + road.delimited(4, geometry)


def tile():
    features = [feature(0, 2, b'\x09\x02\x02'), feature(1, 3, b'\x09\x04\x04')]
    values = [number(5, 4), number(5, 9), road.delimited(1, b'Keep'), road.delimited(1, b'Remove')]
    layer = (road.delimited(1, b'roads') + b''.join(road.delimited(2, f) for f in features)
             + road.delimited(3, b'tippecanoe:minimumzoom') + road.delimited(3, b'name')
             + b''.join(road.delimited(4, v) for v in values) + number(5, 4096) + number(15, 2))
    return road.delimited(3, layer), features[0]


def test_filter_retains_original_geometry_and_id_and_compacts_values():
    data, expected = tile()
    output, counts = road.filter_tile(data, 4)
    assert counts == {'input': 2, 'retained': 1, 'excluded': 1}
    layer = next(output[s:e] for n, _, _, _, s, e in road.fields(output) if n == 3)
    features = [layer[s:e] for n, _, _, _, s, e in road.fields(layer) if n == 2]
    assert len(features) == 1
    def without_tags(raw):
        return b''.join(raw[start:end] for number, _, start, end, _, _ in road.fields(raw) if number != 2)
    assert without_tags(features[0]) == without_tags(expected)
    values = [layer[s:e] for n, _, _, _, s, e in road.fields(layer) if n == 4]
    assert len(values) == 2
    assert b'Keep' in values[1]
    assert b'Remove' not in output


def test_filter_rejects_missing_zoom():
    import pytest
    data, _ = tile()
    with pytest.raises(ValueError, match='minimum zoom'):
        road.filter_tile(data.replace(b'tippecanoe:minimumzoom', b'tippecanoe:maximumzoom'), 4)


def test_hilbert_coordinates_match_known_archive_tiles():
    # Known tile IDs obtained independently using the PMTiles library.
    assert road.tile_coordinates(33) == (3, 1, 3)
    assert road.tile_coordinates(135) == (4, 2, 6)
