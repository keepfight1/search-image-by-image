import inspect
import json
import unittest
from pathlib import Path

from petreid import EMBEDDING_DIM, EMBEDDING_DTYPE, MODEL_VERSION, extract
from petreid.contract import INPUT_SIZE, MEAN, PREPROCESS_SPEC, STD
from petreid.version import MODEL_VERSION as VERSION_FILE_VALUE


class ContractTests(unittest.TestCase):
    def test_fixed_embedding_contract(self):
        self.assertEqual(EMBEDDING_DIM, 512)
        self.assertEqual(EMBEDDING_DTYPE, "float16")
        self.assertEqual(MODEL_VERSION, VERSION_FILE_VALUE)

    def test_extract_signature(self):
        parameters = list(inspect.signature(extract).parameters.values())
        self.assertEqual(len(parameters), 1)
        self.assertEqual(parameters[0].name, "image_path_or_bytes")

    def test_preprocess_json_matches_code(self):
        path = Path(__file__).resolve().parents[1] / "preprocess.json"
        spec = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(spec["embedding_dim"], EMBEDDING_DIM)
        self.assertEqual(spec["embedding_dtype"], EMBEDDING_DTYPE)
        self.assertEqual(spec["model_version"], MODEL_VERSION)
        self.assertEqual(spec["input"]["resize"], [INPUT_SIZE, INPUT_SIZE])
        self.assertEqual(spec["input"]["mean"], list(MEAN))
        self.assertEqual(spec["input"]["std"], list(STD))
        self.assertEqual(spec["input"]["resize_mode"], "direct_resize")
        self.assertFalse(spec["input"].get("center_crop", False))

    def test_preprocess_spec_is_consistent(self):
        self.assertEqual(PREPROCESS_SPEC["embedding_dim"], 512)
        self.assertTrue(PREPROCESS_SPEC["l2_normalized"])
        self.assertEqual(PREPROCESS_SPEC["input"]["resize"], [224, 224])


if __name__ == "__main__":
    unittest.main()
