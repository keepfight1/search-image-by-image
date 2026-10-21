import unittest

import numpy as np

from petreid.retrieval import cosine_similarity_matrix, rank_metrics, threshold_metrics


def unit(vector):
    vector = np.asarray(vector, dtype=np.float32)
    return vector / np.linalg.norm(vector)


class RetrievalTests(unittest.TestCase):
    def test_cosine_similarity_identity(self):
        features = np.eye(3, dtype=np.float32)
        similarities = cosine_similarity_matrix(features, features)
        np.testing.assert_allclose(similarities, np.eye(3), atol=1e-6)

    def test_cosine_similarity_dimension_mismatch(self):
        with self.assertRaises(ValueError):
            cosine_similarity_matrix(np.zeros((1, 4)), np.zeros((1, 5)))

    def test_rank_metrics_perfect_retrieval(self):
        gallery = np.stack([unit([1, 0, 0]), unit([0, 1, 0]), unit([0, 0, 1])])
        metrics = rank_metrics(
            query_features=gallery[:2],
            query_pet_ids=["p1", "p2"],
            query_image_ids=["q1", "q2"],
            gallery_features=gallery,
            gallery_pet_ids=["p1", "p2", "p3"],
            gallery_image_ids=["g1", "g2", "g3"],
        )
        self.assertEqual(metrics["top1"], 1.0)
        self.assertEqual(metrics["top5"], 1.0)
        self.assertEqual(metrics["mAP"], 1.0)
        self.assertEqual(metrics["num_queries"], 2)
        self.assertEqual(metrics["num_negative_queries"], 0)

    def test_rank_metrics_excludes_same_image(self):
        gallery = np.stack([unit([1, 0, 0]), unit([0.8, 0.2, 0]), unit([0, 0, 1])])
        metrics = rank_metrics(
            query_features=gallery[:1],
            query_pet_ids=["p1"],
            query_image_ids=["g1"],
            gallery_features=gallery,
            gallery_pet_ids=["p1", "p1", "p2"],
            gallery_image_ids=["g1", "g2", "g3"],
        )
        self.assertEqual(metrics["top1"], 1.0)
        self.assertEqual(metrics["num_queries"], 1)

    def test_rank_metrics_counts_negative_query(self):
        gallery = np.stack([unit([1, 0, 0]), unit([0, 1, 0])])
        metrics = rank_metrics(
            query_features=np.stack([unit([0, 0, 1])]),
            query_pet_ids=["unknown"],
            query_image_ids=["q1"],
            gallery_features=gallery,
            gallery_pet_ids=["p1", "p2"],
            gallery_image_ids=["g1", "g2"],
        )
        self.assertEqual(metrics["top1"], 0.0)
        self.assertEqual(metrics["num_queries"], 0)
        self.assertEqual(metrics["num_negative_queries"], 1)

    def test_threshold_metrics_tar_and_far(self):
        gallery = np.stack([unit([1, 0, 0]), unit([0, 1, 0])])
        query = np.stack([unit([1, 0.1, 0]), unit([0, 0, 1])])
        metrics = threshold_metrics(
            query_features=query,
            query_pet_ids=["p1", "unknown"],
            gallery_features=gallery,
            gallery_pet_ids=["p1", "p2"],
            threshold=0.9,
        )
        self.assertEqual(metrics["tar"], 1.0)
        self.assertEqual(metrics["far"], 0.0)
        self.assertEqual(metrics["positives"], 1)
        self.assertEqual(metrics["negatives"], 1)

    def test_threshold_metrics_excludes_same_image(self):
        gallery = np.stack([unit([1, 0, 0]), unit([0, 1, 0])])
        metrics = threshold_metrics(
            query_features=gallery[:1],
            query_pet_ids=["p1"],
            gallery_features=gallery,
            gallery_pet_ids=["p1", "p2"],
            threshold=0.99,
            query_image_ids=["g1"],
            gallery_image_ids=["g1", "g2"],
        )
        self.assertEqual(metrics["tar"], 0.0)


if __name__ == "__main__":
    unittest.main()
