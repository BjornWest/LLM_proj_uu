"""Capacity parsing prevents skipping a cheaper matching product."""
import unittest
from data.curation.expansion.webarena.batch05_driver import switch_capacities
class CapacityTests(unittest.TestCase):
    def test_actual_ten_card_case(self):
        self.assertEqual(switch_capacities('our case can hold Nintendo Switch original charger AC adapter and 10 game cards.'),[10])
    def test_actual_units_wording(self):
        self.assertEqual(switch_capacities('Capacity: 40 units Nintendo Switch games, SD/ SDHC/ SDXC memory cards or Sony PS Vita games'),[40])
    def test_actual_mixed_game_sd_capacity(self):
        self.assertEqual(switch_capacities('This compact storage case holds up to 24 game cards and 24 micro SD cards for nintendo switch game card.'),[24])
    def test_sd_count_must_not_satisfy_game_constraint(self):
        self.assertEqual(switch_capacities('10 game cards and 64 micro SD cards'),[10])
        self.assertEqual(switch_capacities('holds 64 SD cards'),[])
    def test_unknown_format_stays_unknown(self):
        self.assertEqual(switch_capacities('lots of cartridges'),[])
if __name__=='__main__':unittest.main()
