import unittest
from data.curation.expansion.webarena.batch06_driver import review_matches,BATCH,HELD,NAVIGATE
class Rules(unittest.TestCase):
 def test_source_partition(self):
  self.assertEqual(len(BATCH),len(set(BATCH)));self.assertEqual(len(BATCH),40);self.assertEqual(len(HELD),7)
 def test_positive_appearance_with_other_complaint(self):
  self.assertTrue(review_matches(385,{'title':'Cute, but not magnetic','body':'Otherwise, the case is cute.'}))
 def test_durability_failure(self):
  self.assertTrue(review_matches(384,{'title':'Read','body':'The gold is already peeling out.'}))
 def test_absence_does_not_invent_underwater(self):
  self.assertFalse(review_matches(22,{'title':'Nice camera','body':'Good pictures.'}))
 def test_driver_update_support_is_not_customer_service(self):
  self.assertFalse(review_matches(26,{'title':'Never again','body':'They do not support driver updates any longer.'}))
 def test_speaker_excludes_compatible_charger(self):
  from data.curation.expansion.webarena.batch06_driver import echo_third_generation_speaker
  self.assertTrue(echo_third_generation_speaker('Echo Dot (3rd Gen) - Smart Speaker with Alexa'))
  self.assertFalse(echo_third_generation_speaker('Juyoon Charger for Amazon Echo Dot (3rd Gen)'))
 def test_standalone_ssd_rejects_computer_capacity(self):
  from data.curation.expansion.webarena.batch06_driver import standalone_ssd_candidate
  self.assertFalse(standalone_ssd_candidate('Dell XPS Tower Desktop PC 512GB SSD 1TB HDD'))
  self.assertFalse(standalone_ssd_candidate('Microsoft Surface Go 128GB SSD'))
  self.assertFalse(standalone_ssd_candidate('USB Hub for HDD SSD'))
  self.assertTrue(standalone_ssd_candidate('Saichi mSATA SSD 256GB Internal SATA III SSD'))
  self.assertTrue(standalone_ssd_candidate('Portable SSD 2TB External Hard Drive for PC Laptop'))
 def test_no_hidden_source_answers(self):
  from pathlib import Path
  text=Path('data/curation/expansion/webarena/batch06_driver.py').read_text()
  self.assertNotIn("['expected']",text);self.assertNotIn('dataset.json',text)
if __name__=='__main__':unittest.main()
