import unittest

if __package__:
    from .model import VERSION, price_domain, resolve
else:
    from model import VERSION, price_domain, resolve


class RequirementTests(unittest.TestCase):
    def setUp(self):
        self.requirement = {"schema": VERSION, "kind": "two_designated_available_cheapest_ties",
                            "concept_id": "footwear.walking_shoes", "offer_ids": ["a", "b"]}

    def test_declared_distinct_target_ids(self):
        resolved = resolve(self.requirement)
        resolved["offer_ids"].append("c")
        self.assertEqual(self.requirement["offer_ids"], ["a", "b"])

    def test_malformed_requirements(self):
        for ids in (["a", "a"], ["a"], ["a", 2], [True, "b"], "ab"):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                resolve({**self.requirement, "offer_ids": ids})
        with self.assertRaises(ValueError):
            resolve({**self.requirement, "allow_price_overflow": True})

    def test_bounds_match_clamped_native_rounding(self):
        def rounding(raw, reference, config):
            return max(1000, reference + round((raw - reference) / 1000) * 1000)
        cfg = {"offset_min": -.3, "offset_max": .3, "rounding_bands_sek": [[None, 10]]}
        support = price_domain({"price_trace": {"reference_minor": 51000}}, cfg, rounding)
        self.assertEqual(support, set(range(36000, 66001, 1000)))
        self.assertNotIn(35999, support)
        self.assertNotIn(47001, support)
        # Every hundredth raw offset maps inside the finite output support.
        for hundredth in range(-30, 31):
            self.assertIn(rounding(51000 * (1 + hundredth / 100), 51000, cfg), support)

    def test_clamped_endpoint_is_not_a_new_rounding_grid(self):
        def rounding(raw, reference, config):
            return max(100, reference + round((raw - reference) / 100) * 100)
        cfg = {"offset_min": -.9, "offset_max": 2, "rounding_bands_sek": [[None, 1]]}
        support = price_domain({"price_trace": {"reference_minor": 190}}, cfg, rounding)
        self.assertEqual(support, {100, 190, 290, 390, 490, 590})
        self.assertNotIn(200, support)

    def test_existing_float_endpoint_keeps_its_half_step(self):
        def rounding(raw, reference, config):
            return max(100, reference + round((raw - reference) / 100) * 100)
        cfg = {"offset_min": -.3, "offset_max": .3, "rounding_bands_sek": [[None, 1]]}
        # float(5500*(1-.3)) falls just below3850; native round gives3800.
        support = price_domain({"price_trace": {"reference_minor": 5500}}, cfg, rounding)
        self.assertEqual(min(support), rounding(5500 * (1 + cfg["offset_min"]), 5500, cfg))
        self.assertEqual(min(support), 3800)

    def test_reference_match_draw_exists_outside_offset_interval(self):
        def rounding(raw, reference, config):
            return max(1000, reference + round((raw - reference) / 1000) * 1000)
        cfg = {"offset_min": .05, "offset_max": .3,
               "reference_match_probability": .4, "rounding_bands_sek": [[None, 10]]}
        offer = {"price_trace": {"reference_minor": 51000}}
        self.assertIn(51000, price_domain(offer, cfg, rounding))
        self.assertNotIn(51000, price_domain(offer, {**cfg, "reference_match_probability": 0}, rounding))


if __name__ == "__main__":
    unittest.main()
