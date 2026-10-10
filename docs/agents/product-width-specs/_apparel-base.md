# Neutral adult apparel authoring module

Status: proposed additive base for the jacket wave; not a counted concept or a
production schema. `_apparel_base.json` shares canonical identity, positioning,
execution, nominal size labels and sparse colour/size manufacture. It includes no
footwear EU size, width, sole, heel, comfort or weather assumptions.

Adult alpha labels are an explicit bounded convention: XS–XL, S–XXL, or XS–XXXL
ordered ranges, weights3:3:1. They are manufacturer labels, not measured body or
garment dimensions, and do not establish gender/cut equivalence between brands.
Colour selection reuses the reviewed general palette and weighted subset recipe.
Each colour manufactures a full/subrange/alternating subset of the ordered nominal
size range at weights75:20:5. These are tunable authoring choices, not estimates.
No retailer stock, availability, offer prices or destination eligibility enter
manufacture; sparse/no-match combinations are retained.

Canonical SKU = product identity plus colour and nominal size label. Retailer
grouping may show colour as selector/separate page; size is a selector. A future
product requiring length, body measurements or cut variants needs an explicit
extension rather than encoding those properties into a label. Reviews bind the
actual canonical tested SKU, including its size/colour, not an arbitrary model ID.
The shared review factory accepts this module's SKU properties explicitly.

Positioning/execution and colour distributions reuse existing machinery; new random
namespace keeps the module additive. Size grids, care, fit/cut, fabrics, closures,
weather declarations and mass basis belong to each concept. There is no automatic
generalization from a rain shell to insulation, fleece or every jacket.
