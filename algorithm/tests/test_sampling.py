import unittest

from petreid.sampling import PKBatchSampler


class PKBatchSamplerTests(unittest.TestCase):
    def setUp(self):
        self.labels = [0] * 4 + [1] * 4 + [2] * 4 + [3] * 4

    def test_batch_contains_p_identities_and_k_samples(self):
        sampler = PKBatchSampler(self.labels, p=3, k=2, seed=7)
        batches = list(sampler)
        self.assertGreaterEqual(len(batches), 1)
        for batch in batches:
            self.assertEqual(len(batch), 6)
            counts = {}
            for index in batch:
                label = self.labels[index]
                counts[label] = counts.get(label, 0) + 1
            self.assertEqual(len(counts), 3)
            self.assertTrue(all(count == 2 for count in counts.values()))

    def test_same_seed_is_reproducible(self):
        first = list(PKBatchSampler(self.labels, p=2, k=2, seed=11))
        second = list(PKBatchSampler(self.labels, p=2, k=2, seed=11))
        self.assertEqual(first, second)

    def test_epoch_increments_and_changes_sampling(self):
        sampler = PKBatchSampler(self.labels, p=2, k=2, seed=3)
        first = list(sampler)
        second = list(sampler)
        self.assertEqual(sampler.epoch, 2)
        self.assertNotEqual(first, second)

    def test_p_is_clamped_to_available_identities(self):
        sampler = PKBatchSampler([0, 0, 1, 1], p=8, k=2)
        self.assertEqual(sampler.p, 2)
        self.assertEqual(sampler.batch_size, 4)

    def test_rare_identity_is_repeated_to_fill_k(self):
        labels = [0, 0, 1, 1, 1]
        sampler = PKBatchSampler(labels, p=2, k=4, seed=1)
        batch = next(iter(sampler))
        self.assertEqual(len(batch), 8)
        self.assertEqual(sum(1 for index in batch if labels[index] == 0), 4)

    def test_invalid_arguments(self):
        with self.assertRaises(ValueError):
            PKBatchSampler([0, 1], p=0, k=2)
        with self.assertRaises(ValueError):
            PKBatchSampler([0, 0, 0], p=1, k=1)


if __name__ == "__main__":
    unittest.main()
