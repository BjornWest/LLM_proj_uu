"""Read-once defaults retain native world bytes, reload boundaries and callers."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from experiments.accepted_catalog_commerce import model as commerce, package_export
from experiments.world_sampling_defaults import model as population


def stand_in(seed, concept_id, brand, product_id, *, earlier, review_count):
    return {'public': {'product_id': product_id, 'concept_id': concept_id,
                       'family_id': concept_id.split('.')[0], 'name': 'Product ' + product_id,
                       'reference_price_sek': 400 + seed % 600,
                       'skus': [{'sku_id': f'{product_id}-{size}', 'product_id': product_id,
                                 'size_eu': size} for size in range(38, 42)]},
            'private': {'profiles': {'positioning': brand['positioning']}},
            'variant_fields': {'size_eu': {'retail_presentation': {'allowed': ['selector']}}},
            'descriptions': [], 'reviews': []}


class DefaultsSnapshotTests(unittest.TestCase):
    def generate(self, seed, world_size):
        with patch.object(package_export, 'sample', stand_in):
            return commerce.generate(seed, concept_ids=['footwear.walking_shoes'],
                                     tasks=['footwear.walking_shoes'],
                                     controls={'world_size': world_size}, review_count=0)

    def test_complete_world_bytes_match_repeated_defaults_reads(self):
        original_load, original_sample, original_listing = population.load, population.sample, population.list_skus
        original_home = commerce.native.choose_home

        def old_sample(*args, **kwargs):
            # Reproduce the old population boundary: load its own defaults.
            kwargs.pop('_loaded_defaults')
            return original_sample(*args, **kwargs)

        def old_listing(*args, **kwargs):
            # Reproduce the old per-retailer/product defaults reads.
            kwargs.pop('config')
            return original_listing(*args, **kwargs)

        def old_home(*args, **kwargs):
            kwargs.pop('population_config')
            return original_home(*args, **kwargs)

        for seed, size in ((5, 1), (73, 4), (18, 0)):
            with self.subTest(seed=seed, world_size=size):
                with patch.object(population, 'load', wraps=original_load) as reads:
                    current = self.generate(seed, size)
                self.assertEqual(reads.call_count, 1)
                with patch.object(population, 'sample', old_sample), \
                     patch.object(population, 'list_skus', old_listing), \
                     patch.object(commerce.native, 'choose_home', old_home), \
                     patch.object(population, 'load', wraps=original_load) as repeated:
                    old = self.generate(seed, size)
                self.assertGreater(repeated.call_count, 1)
                self.assertEqual(json.dumps(current, sort_keys=True), json.dumps(old, sort_keys=True))

    def test_new_world_reads_new_defaults_including_provenance(self):
        first = population.load()
        second = (deepcopy(first[0]), first[1])
        second[0]['sku_listing']['size_coverage_mode_probabilities'] = {'all_manufactured_sizes': 1, 'every_other_size': 0}
        # Use a valid changed default without a process-global cache.
        population.validate(second[0], second[1])
        before = deepcopy(first[0]), deepcopy(second[0])
        with patch.object(population, 'load', side_effect=[first, second]) as reads:
            worlds = [self.generate(5, 1), self.generate(5, 1)]
        self.assertEqual(reads.call_count, 2)
        self.assertEqual(first[0], before[0])
        self.assertEqual(second[0], before[1])
        self.assertEqual(worlds[1]['provenance']['population_defaults_sha256'], commerce.native.digest(second[0]))
        self.assertNotEqual(worlds[0]['world_id'], worlds[1]['world_id'])

    def test_metadata_only_default_call_still_loads_and_matches_explicit_snapshot(self):
        loaded = population.load()
        with patch.object(population, 'load', return_value=loaded) as reads:
            ordinary = population.sample(5, controls={'world_size': 0})
        reads.assert_called_once_with()
        with patch.object(population, 'load', side_effect=AssertionError('Unexpected reload')):
            reused = population.sample(5, controls={'world_size': 0}, _loaded_defaults=loaded)
        self.assertEqual(ordinary, reused)

    def test_legacy_foreign_placement_call_and_explicit_config_agree(self):
        config, _ = population.load()
        for method in ('delivery', 'pickup', 'inspection'):
            for international in (False, True):
                with self.subTest(method=method, international=international):
                    with patch.object(population, 'load', return_value=(config, None)) as reads:
                        ordinary = population.foreign_placement_multiplier('uppsala', 'helsinki', method, international)
                    reads.assert_called_once_with()
                    with patch.object(population, 'load', side_effect=AssertionError('Unexpected reload')):
                        reused = population.foreign_placement_multiplier('uppsala', 'helsinki', method, international, config=config)
                    self.assertEqual(ordinary, reused)


if __name__ == '__main__':
    unittest.main()
