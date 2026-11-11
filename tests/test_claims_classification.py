from collections import Counter
import gzip
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'vm-review'))
from aem_claims_classification import (
    encode_varint, fields, filter_claim_records, filter_claim_tile, normalize
)


def field(number, data):
    return encode_varint(number << 3 | 2) + encode_varint(len(data)) + data


def fixture(values, key='CSE_DISP', layer_name='claims'):
    features = []
    encoded_values = []
    for index, value in enumerate(values):
        if value is not MISSING:
            if value is None:
                encoded = b''
            elif isinstance(value, str):
                encoded = field(1, value.encode())
            else:
                encoded = b'\x28' + encode_varint(value)
            tags = field(2, encode_varint(0) + encode_varint(len(encoded_values)))
            encoded_values.append(field(4, encoded))
        else:
            tags = b''
        # Native ID, all tags and geometry must remain byte-identical when kept.
        feature = b'\x08' + encode_varint(index + 1) + tags + b'\x18\x01' + field(4, b'\x09\x02\x02')
        features.append(field(2, feature))
    layer = field(1, layer_name.encode()) + b''.join(features) + field(3, key.encode()) + b''.join(encoded_values) + b'\x28\x80\x20\x78\x02'
    return field(3, layer), features


MISSING = object()


class ClassificationTests(unittest.TestCase):
    def test_all_states_include_every_nonclosed_status_with_original_attributes(self):
        values = ['Active', 'Filed', 'Submitted', 'Under Review', 'On Appeal',
                  'Appeal - Stay Granted', 'Draft', 'Interim', ' CLOSED ', 'closed', 'ClOsEd\t',
                  MISSING, None, '', ' \n\t', 5]
        tile, features = fixture(values, ' cSe_DiSp ')
        expected_ids = list(range(1, 9))
        for state in 'az ca co id mt nm nv or ut wa wy'.split():
            with self.subTest(state=state):
                filtered, counts = filter_claim_tile(gzip.compress(tile), 'claims')
                self.assertEqual(counts['before'], 16)
                self.assertEqual(counts['after'], 8)
                self.assertEqual(counts['closed'], 3)
                self.assertEqual(counts['unknown'], 5)
                self.assertEqual(counts['unknownReasons'], {'missing': 1, 'null': 1, 'blank': 2, 'invalid': 1})
                self.assertEqual(counts['byClassification']['filed'], 1)
                self.assertEqual(counts['byClassification']['closed'], 3)
                self.assertNotIn('closed', counts['afterByClassification'])
                self.assertEqual(sum(counts['afterByClassification'].values()), 8)
                decoded = gzip.decompress(filtered)
                layer = next(value for number, wire, value, _ in fields(decoded) if number == 3)
                kept = [raw for number, wire, value, raw in fields(layer) if number == 2]
                self.assertEqual(kept, features[:8])
                ids = [next(value for number, wire, value, _ in fields(feature)
                            if number == 1) for number, wire, feature, _ in fields(layer) if number == 2]
                self.assertEqual(ids, expected_ids)

    def test_normalization_is_explicit_and_missing_is_not_active(self):
        for value in ['Closed', ' CLOSED ', '\nClOsEd\t', '\u00a0Closed\u2003']:
            self.assertEqual(normalize(value), ('closed', None))
        self.assertEqual(normalize('Under   Review'), ('under review', None))
        self.assertEqual(normalize(None), (None, 'null'))
        self.assertEqual(normalize(None, present=False), (None, 'missing'))
        self.assertEqual(normalize(''), (None, 'blank'))

    def test_uncompressed_and_no_removal_preserve_original_bytes(self):
        tile, _ = fixture(['Filed', 'Submitted', 'Under Review'])
        for payload in [tile, gzip.compress(tile)]:
            filtered, counts = filter_claim_tile(payload, 'claims')
            self.assertEqual(filtered, payload)
            self.assertEqual(counts['after'], 3)

    def test_malformed_tiles_cannot_bypass_validation(self):
        for payload in [b'\x1a\x80', b'\x1a\x05abc', b'\x00']:
            with self.assertRaises(ValueError):
                filter_claim_tile(payload, 'claims')

    def test_live_records_use_the_same_nonclosed_and_unknown_policy(self):
        records = [
            {'attributes': {'OBJECTID': 1, 'CSE_DISP': 'Active'}},
            {'attributes': {'OBJECTID': 2, 'CSE_DISP': ' Filed '}},
            {'attributes': {'OBJECTID': 3, ' cse_disp ': '\tCLOSED\n'}},
            {'attributes': {'OBJECTID': 4, 'CSE_DISP': None}},
            {'attributes': {'OBJECTID': 5}},
        ]
        filtered, counts = filter_claim_records(records)
        self.assertEqual(filtered, records[:2])
        self.assertEqual((counts['before'], counts['after'], counts['closed'], counts['unknown']),
                         (5, 2, 1, 2))
        self.assertEqual(counts['afterByClassification'], {'active': 1, 'filed': 1})
        self.assertEqual(counts['unknownReasons'], {'missing': 1, 'null': 1})


if __name__ == '__main__':
    unittest.main()
