import unittest
from pathlib import Path

from petreid.export_features import parse_splits


class ExportFeatureTests(unittest.TestCase):
    def test_parse_splits(self):
        self.assertEqual(parse_splits("gallery, query"), ["gallery", "query"])

    def test_parse_splits_rejects_empty_and_invalid(self):
        with self.assertRaises(ValueError):
            parse_splits(" , ")
        with self.assertRaises(ValueError):
            parse_splits("gallery,unknown")


if __name__ == "__main__":
    unittest.main()
