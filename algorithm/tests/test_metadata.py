import json
import tempfile
import unittest
from pathlib import Path

from petreid.metadata import (
    MetadataError,
    group_by_pet,
    group_by_species,
    read_metadata,
    resolve_image_path,
    select_rows,
)


def make_row(image_id="cat_001", pet_id="p_001", species="cat", split="train", **extra):
    row = {"image_id": image_id, "pet_id": pet_id, "species": species, "split": split}
    row.update(extra)
    return row


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "images").mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def write_rows(self, rows):
        path = self.root / "metadata.jsonl"
        with open(path, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return path

    def test_read_valid_and_normalize_case(self):
        path = self.write_rows([make_row(species="CAT", split="Train")])
        rows = read_metadata(path)
        self.assertEqual(rows[0]["species"], "cat")
        self.assertEqual(rows[0]["split"], "train")

    def test_duplicate_image_id_rejected(self):
        path = self.write_rows([make_row(), make_row()])
        with self.assertRaises(MetadataError):
            read_metadata(path)

    def test_invalid_species_rejected(self):
        path = self.write_rows([make_row(species="bird")])
        with self.assertRaises(MetadataError):
            read_metadata(path)

    def test_invalid_split_rejected(self):
        path = self.write_rows([make_row(split="unknown")])
        with self.assertRaises(MetadataError):
            read_metadata(path)

    def test_missing_required_field_rejected(self):
        path = self.write_rows([{"image_id": "x", "pet_id": "p", "species": "cat"}])
        with self.assertRaises(MetadataError):
            read_metadata(path)

    def test_empty_file_rejected(self):
        path = self.root / "metadata.jsonl"
        path.write_text("\n", encoding="utf-8")
        with self.assertRaises(MetadataError):
            read_metadata(path)

    def test_resolve_image_path_with_suffix_and_missing(self):
        (self.root / "images" / "cat_001.jpg").write_bytes(b"x")
        self.assertEqual(
            resolve_image_path(self.root, make_row()),
            self.root / "images" / "cat_001.jpg",
        )
        self.assertIsNone(resolve_image_path(self.root, make_row(image_id="missing")))

    def test_resolve_explicit_relative_path(self):
        (self.root / "images" / "custom.png").write_bytes(b"x")
        row = make_row(image_path="images/custom.png")
        self.assertEqual(
            resolve_image_path(self.root, row),
            self.root / "images" / "custom.png",
        )

    def test_select_rows_reports_missing_images(self):
        (self.root / "images" / "cat_001.jpg").write_bytes(b"x")
        rows = [make_row(), make_row(image_id="cat_002", split="val")]
        selected, missing = select_rows(rows, ["train"], self.root)
        self.assertEqual([row["image_id"] for row in selected], ["cat_001"])
        self.assertEqual(missing, [])

        selected, missing = select_rows(rows, ["val"], self.root)
        self.assertEqual(selected, [])
        self.assertEqual(missing, ["cat_002"])

    def test_grouping(self):
        rows = [
            make_row(image_id="a", pet_id="p1", species="cat"),
            make_row(image_id="b", pet_id="p1", species="cat"),
            make_row(image_id="c", pet_id="p2", species="dog"),
        ]
        self.assertEqual(len(group_by_pet(rows)["p1"]), 2)
        self.assertEqual(len(group_by_species(rows)["cat"]), 2)
        self.assertEqual(len(group_by_species(rows)["dog"]), 1)


if __name__ == "__main__":
    unittest.main()
