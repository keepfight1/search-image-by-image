import tempfile
import unittest
from pathlib import Path

import numpy as np

from petreid.features import (
    FeatureFormatError,
    l2_normalize,
    load_features,
    normalize_and_cast,
    save_features,
    save_per_image,
    validate_feature,
)


class FeatureTests(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(42)

    def test_l2_normalize_rows(self):
        array = self.rng.normal(size=(3, 512)).astype(np.float32)
        normalized = l2_normalize(array)
        norms = np.linalg.norm(normalized, axis=1)
        np.testing.assert_allclose(norms, np.ones(3), atol=1e-6)

    def test_normalize_and_cast_dtype_and_shape(self):
        array = self.rng.normal(size=(4, 512)).astype(np.float32) * 10
        result = normalize_and_cast(array)
        self.assertEqual(result.shape, (4, 512))
        self.assertEqual(result.dtype, np.float16)
        norms = np.linalg.norm(result.astype(np.float32), axis=1)
        np.testing.assert_allclose(norms, np.ones(4), atol=2e-3)

    def test_normalize_and_cast_rejects_wrong_shape(self):
        with self.assertRaises(FeatureFormatError):
            normalize_and_cast(np.zeros((2, 256), dtype=np.float32))

    def test_validate_feature_accepts_contract_format(self):
        feature = normalize_and_cast(self.rng.normal(size=(1, 512)))[0]
        validate_feature(feature)

    def test_validate_feature_rejects_bad_dtype_shape_nan_and_norm(self):
        feature = normalize_and_cast(self.rng.normal(size=(1, 512)))[0]
        with self.assertRaises(FeatureFormatError):
            validate_feature(feature.astype(np.float32))
        with self.assertRaises(FeatureFormatError):
            validate_feature(np.zeros(511, dtype=np.float16))
        broken = feature.copy()
        broken[0] = np.nan
        with self.assertRaises(FeatureFormatError):
            validate_feature(broken)
        with self.assertRaises(FeatureFormatError):
            validate_feature(np.full(512, 0.1, dtype=np.float16))

    def test_save_load_roundtrip(self):
        features = self.rng.normal(size=(5, 512)).astype(np.float32)
        image_ids = ["img_%d" % index for index in range(5)]
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "features"
            feature_path, ids_path = save_features(
                features, image_ids, output, meta={"split": "gallery"}
            )
            self.assertTrue(feature_path.is_file())
            self.assertTrue(ids_path.is_file())
            self.assertTrue((output / "features_meta.json").is_file())
            loaded, loaded_ids = load_features(output)
            self.assertEqual(loaded_ids, image_ids)
            self.assertEqual(loaded.dtype, np.float16)
            self.assertEqual(loaded.shape, (5, 512))

    def test_save_features_rejects_duplicate_ids(self):
        features = self.rng.normal(size=(2, 512)).astype(np.float32)
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(FeatureFormatError):
                save_features(features, ["same", "same"], Path(temp))

    def test_save_features_rejects_count_mismatch(self):
        features = self.rng.normal(size=(2, 512)).astype(np.float32)
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(FeatureFormatError):
                save_features(features, ["only_one"], Path(temp))

    def test_save_per_image(self):
        features = self.rng.normal(size=(3, 512)).astype(np.float32)
        with tempfile.TemporaryDirectory() as temp:
            paths = save_per_image(features, ["a", "b", "c"], Path(temp))
            self.assertEqual(len(paths), 3)
            for path in paths:
                vector = np.load(path)
                self.assertEqual(vector.shape, (512,))
                self.assertEqual(vector.dtype, np.float16)


if __name__ == "__main__":
    unittest.main()
