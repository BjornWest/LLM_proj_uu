"""Saved-AX corrected removal label; original pair driver and traces remain immutable."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4];sys.path.insert(0,str(ROOT))
from data.curation.expansion.webarena_wishlist import run_v2
base=run_v2.base
class ControlDriver(base.WishlistDriver):
 def steps(self):
  if self.variant!='remove-after-add':
   yield from super().steps();return
  assert self.contract['source_task_id']==516,'Bounded current-page control only'
  yield from self.add()
  row=self.page.locator('.products-grid.wishlist li.product-item').first
  # Exact current AX name is lowercase item; title attribute uses uppercase Item.
  yield self.act(row.get_by_role('link',name='Remove item',exact=True))
  yield self.finish()
base.WishlistDriver=ControlDriver
if __name__=='__main__':base.main()
