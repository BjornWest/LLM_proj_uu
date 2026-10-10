# Neutral charger module

`_chargers_base.json` provides brand/model identity, independent positioning and
execution, reference anchors and canonical plug/colour/bundle grouping. Children
declare named ports and electrical profiles; no battery/runtime, retailer stock,
actual device output or safety assurance is inherited. Both positioning-related
construction alternatives remain possible; execution is a separate draw.

Wall adapters use SEK150–350/300–650/550–1100 anchors rounded5. Cable bundles cost
1.25 times that anchor before retailer manufacture. Selected canonical-SKU prices
use global SEK150–1375 review bounds; accepted75% silence/concentration1.5 and
rating-conditioned value with cheap-product adjustment remain unchanged.

Canonical rows retain inclusion, `declared` versus `not applicable` length status,
a `2 m`/`not applicable` label and `unknown`/`not applicable` capability status.
The represented model cable has a typed2m fact only when a cable-bundle SKU exists.
A consumer binds the selected row to `sku` and binds typed length/current/power/data
aliases with the matching applicable/unknown states; it must not treat another
bundle's cable as included. This finite length recipe has no numeric per-SKU length
variant or production cable/device join. No0m cable or absent physical C2 is invented.

Public fixed PDO alternatives and PPS voltage/current/power ceilings are typed;
finite tables avoid unsupported dimensional multiplication in the shared DSL.
Independent arithmetic checks enforce the declared power cap. The20W port's PPS
range/current product33W does not increase its limit; output at a device is unknown.
