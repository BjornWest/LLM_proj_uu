# Slim portable keyboards — compact layouts and distinct power routes

Status: domain accepted in shared DSL, 2026-10-01; isolated authoring preview only. Concept
`keyboards.slim_portable_keyboards`, family `keyboards`, registered electronics/office
stores. One freestanding, unsplit compact keyboard with low-profile keys, an on/off
slider and no integrated number pad. This bounded recipe is rigid and does not
fold. It is not a tablet cover, keyboard case, split assembly, trackpad, display,
mouse, wrist rest or powered USB hub. Those are explicit fixture exclusions, not
universal claims about portable keyboards. Slimness/portability does not establish
health benefits, universal bag fit or shock/water protection.

## Sources and frozen foundation

[Primary notes](../../../.local/product-width/research/slim_portable_keyboards.md)
record [Pebble Keys2](https://www.logitech.com/en-gb/shop/p/pebble-keys-2),
[MX Keys Mini](https://www.logitech.com/en-gb/shop/p/mx-keys-mini), and
[B1 Pro](https://www.keychron.com/products/keychron-b1-pro-ultra-slim-wireless-keyboard).
They support replaceable-cell, illuminated rechargeable and multi-mode examples.
The notes preserve power/box/unit gaps rather than fill them from marketing.
These are separately named synthetic fixtures, not real vendor SKUs. Every
quantity, regional count, complete box list and restricted interface below is
explicitly authored unless labeled unknown. Source claims of runtime, range,
acoustics, precision, ergonomics or protective-skin performance are not imported
as facts or sampled customer evidence. The ambiguous source3.7V label is not a
battery/input measurement in this package.

Extend frozen `_keyboards_base.json` for identity, independent profiles and
language/colour presentation declarations only, under the neutral contract in
`_keyboards-base.md`. Replace child SKU schema and bounds, supply independent
manufacture and price producers. Do not carry desktop hardware, masses,
dimensions,1000Hz polling, mechanical mechanisms, tilt feet, red lighting, USB
lead, battery-free status or QMK/VIA defaults into this child. Existing
base/desktop/compiler/indices/pilot sources remain read-only.

## Finite joint assemblies

| Assembly | Authored power and interfaces | Included hardware | Key/light construction |
| --- | --- | --- | --- |
| cell_compact | two replaceable AAA alkaline cells; Bluetooth only | cells preinstalled; no USB lead, receiver or charging socket | scissor keys, ABS body/keycaps; no backlight |
| rechargeable_lit | integrated Li-polymer battery; Bluetooth keyboard input; USB-C charging only, explicitly no USB keyboard data mode | one detachable nominal1m USB-A-to-USB-C charge lead; no receiver | scissor keys, ABS body/keycaps; declared white key backlight |
| rechargeable_trimode | integrated Li-polymer battery; Bluetooth, matched2.4GHz receiver and USB keyboard data modes; USB-C charging/data socket | one detachable nominal1.2m USB-A-to-USB-C data/charge lead and one matched USB-A receiver | scissor keys, ABS body/keycaps; no backlight |

All have function row/arrow keys but no separate full navigation cluster,
number pad, user-adjustable tilt feet, hot-swap sockets or declared mechanical
switch plate. Mechanical-plate quantities and tilt-adjustment heights/angles
are not applicable; scissor mechanism does not imply a mechanical switch type.
Keycap-removal declaration, switch supplier, force/travel, rollover, polling,
latency, acoustic levels, wear cycles and spill/impact ratings remain unknown.
No protective skin, cover, carrying pouch or stand is included. No folded size,
folding joints or split adjustment exists for these authored rigid fixtures.

Model assembly defines the joint installed power/interface/mechanism, not a
retailer-selectable battery option. Baseline cell:lit:trimode4:3:3, budget8:2:2,
mainstream4:4:4,premium2:6:6. These tunable positioning associations leave every
assembly possible; they are not vendor prices or empirical prevalence. Private
execution remains independently uniform0.05–0.95 and cannot change or establish
hardware or compatibility.

## Counted regional layouts and bodily quantities

| Model format | Printed language and geometry | Installed key count | Enter geometry |
| --- | --- | --- | --- |
| cell_compact or rechargeable_lit: compact function-row layout | US English ANSI |79|horizontal single-row|
| same two assemblies | UK English ISO |80|tall two-row|
| rechargeable_trimode: compact75% label | US English ANSI |77|horizontal single-row|
| same trimode assembly | UK English ISO |78|tall two-row|

These are explicit authored joint counts/physical layouts, not derived by
multiplying a format percentage or inferred from a locale URL. Count installed
physical keys including Fn/modifiers; layers and software functions add no
physical keys. The source77-key example does not establish this authored UK78
or either79/80 tuple. Exact row spacing, complete legend inventory and scan
matrix remain unknown. Other regional/JIS/Nordic layouts are deferred.

Printed legends and physical Enter/modifier positions do not set the computer's
input map. A punctuation task/review must identify the selected printed US/UK
layout and the corresponding active computer input map; choosing a software
language does not reshape this canonical keyboard.

Authored nominal body width/depth/maximum height(mm) is280/125/17 for cell,
300/132/21 for lit,296/130/15 for trimode. The basis is assembled keyboard with
installed keycaps and its operating batteries, resting normally, external leads,
receiver and packaging excluded. It is neither front-edge height nor supplied-set
measurement. Nominal body mass(g) on that same installed-battery basis is420,
510,430 respectively. Cable/receiver/cell-only/packaging/complete-box masses remain
unknown; do not subtract invented component masses. Both regional layouts share
these dimensions/masses by authoring choice. None is a copied desktop quantity or
an unqualified reconstruction of the source front/rear heights or accessory mass.
There are no adjustable-foot or folded-dimension quantities; those are NA.

## Battery capacity, energy and declaration status

All models have a battery, so unknown energy is present-but-unknown, not0Wh or
battery-free. Cell has two supplied user-replaceable AAA alkaline cells and an
authored tool-free rear compartment; cell voltage, charge capacity, electrical
arrangement and aggregate Wh are unknown. On-device recharging/USB input/socket
and charge time are NA for this explicitly nonrechargeable fixture. No replacement
cells are supplied beyond the installed two; safe replacement procedure beyond
this compartment/hardware declaration remains unspecified.

Lit has one integrated1500mAh Li-polymer pack by authored declaration. Its nominal
cell voltage and Wh remain unknown: mAh alone does not establish energy. Trimode
has a finite authored joint nominal pack tuple800mAh,3.7V,2.96Wh, one integrated
Li-polymer pack. This tuple is an authored cell-energy basis, not a corrected
manufacturer measurement and not a USB input rating. It is internally coherent
(0.8Ah×3.7V=2.96Wh); emit joint typed constants rather than let unrelated draws
invent invalid combinations. These two integrated packs are not user-replaceable
in this recipe. Integrated-pack count is not AAA count; those other quantities
are NA in the respective branch.

Rechargeable device-input V/A/W ceilings, cable electrical ratings and charging
protocol/charge time are unknown. USB-C does not turn3.7V cell voltage into input
voltage or imply USB Power Delivery. Lit lead data capability is unknown even
though the keyboard data mode is explicitly absent; trimode supplied lead has
declared keyboard data capability, with data-speed/electrical ceiling unknown.
All runtime/endurance/range declarations and exact protocols/conditions are
unknown here. Do not convert manufacturer calendar claims into operating hours,
Wh or sampled user outcomes. Numeric runtime topics are deferred.

## Connections, remembered devices and software

Every assembly has three authored remembered Bluetooth host slots and dedicated
selection controls. This permits choosing between already paired hosts; it does
not declare simultaneous keyboard input to three hosts. Bluetooth version,
radio range/RSSI, signal security, reconnect latency and exact host/version
compatibility matrices are unknown. Basic input is declared for compatible
Windows/macOS/iPadOS/Android/Linux hosts as an authored capability, not production
interoperability validation. Bluetooth on a host is an explicit precondition;
manufacturer platform lists do not prove login-screen/virtual-machine/app behavior.

Cell and lit have no receiver mode in these bounded fixtures, despite optional
receiver support in a real source example. Receiver protocol/connector/mass/radio
band is NA there. Trimode's included receiver is matched to this exact keyboard
model, with a USB-A host plug and declared2.4GHz band; it is not universal, not a
Bluetooth adapter and not compatible merely by using a same-looking connector.
Receiver software/firmware/hardware interchangeability and actual radio results
remain unknown. No USB-C host adapter, hub or extension is included. USB-A lead
ends and receiver require matching compatible host/source hardware. A USB-C
keyboard socket never establishes a USB-C host plug.

For trimode the supplied lead supports USB keyboard input/charging; selecting
that mode is an explicit use context. For lit the lead charges while typing stays
on Bluetooth. Cell has no socket/lead or USB keyboard data route. Socket/lead
related quantities are NA when absent. Charger inclusion is explicitly false for
all authored boxes, closing rather than concealing the unresolved source flag.

Cell remapping support is unknown, not a known empty support set. Lit declares a
synthetic `shortcut_utility` for function-row assignments on a compatible
Windows/macOS host; general arbitrary-key remapping is unknown. Trimode declares
synthetic `keymap_utility` for physical-key assignments on a compatible host
while connected by its supplied USB data lead. These are named authoring utility
fixtures with explicit scopes, not promises to work with a real vendor app or
production firmware. No utility, subscription, browser setup or installed keymap
is supplied. A review about one assignment requires the matching compatible
utility already installed/configured and the stated connection; declarations do
not establish automatic discovery or successful software setup. Actual utility
versions/OS releases/firmware/keymap export interoperability are deferred.

Lit white backlight presence/colour is authored; brightness, modes, spectrum,
controls and sensors are unknown. Those light quantities are NA for the two
explicitly unlit assemblies. Absence of lighting does not mean known black LEDs.
Body/keycap care, permissible cleaner and water exposure are unknown for all
three; a real source's washable silicone accessory does not make this keyboard
washable. There is no owner-cleaning topic or disposal/repair/health assurance.

## Canonical manufacture, box and price

Draw nonempty subsets of black/white and US English ANSI/UK English ISO; each menu
uses equal item weights, one/two cardinality weights3:2. Manufacture every chosen
Cartesian row. These palettes/layout combinations are authored choices, not
extrapolated source catalogues. Only colour and language layout are retail axes.
Canonical rows retain owner/product ID, unique SKU ID, installed count/physical
layout/Enter, assembly identity, nominal body quantities/basis, battery/interface
and supplied-hardware declarations, assembly factor and exact reference price.
Derived descriptive facts are not extra selectors. Stock/carried subsets follow
manufacture and may be sparse/empty/sold-out; grouping cannot overwrite any
canonical fact or invent a receiver/lead/layout not manufactured.

Every box includes one complete assembled keyboard with its declared battery and,
only when applicable, its stated lead/receiver. No mouse, wall charger, host
adapter, extension, number-pad accessory, wrist rest, extra battery, cover/pouch,
skin, puller, spare keycaps/switches or stand is included. These exclusions are
explicitly authored. Documentation is not an extra hardware component. Optional
real bundles or image-only source box contents are not silently promoted to these
synthetic boxes.

Synthetic anchor bandsSEK180–450/400–1100/900–2000 by positioning, rounded5.
Assembly factors cell1,lit1.2,trimode1.35 apply before subset manufacture; language
and colour add no surcharge. Selected canonical reference uses that assembly
factor, not a per-retailer quote. Global price bounds are180–2700SEK, anchored
to the complete authored menu even for singleton manufacture. Do not rebase to
whatever variants happened to be made or scale by unknown energy/runtime.

## Natural owner meanings and proposed bindings

Standalone review binds an existing exact canonical SKU without regenerating
product. Stars retain shared concentration1.5, topic-count weights0:24,1:4,2:3,3:1
(75% silence), variable order and protected value-frequency policy. Silence still
contributes its star draw. At fixed satisfaction value favourability remains a
clipped normal with mean(stars−1)/4−0.2*(relative_price−0.5),sd0.22,round1e−6,
positive>=0.5; relative price is(selected price−180)/2520. Other topic sentiments
are soft satisfaction-dependent draws, not factual proof.

Meaning retains operation, source provenance, exact selected SKU, setup and both
polarities. Common owner topics:

- key feel while typing a short text passage at a small shared table using an
  already paired laptop on Bluetooth;
- perceived key sound during that passage in one's quiet room;
- finding printed punctuation with the stated US/UK matching laptop input map;
- packing the individual keyboard in one's usual work bag, not measuring universal
  bag fit or the complete box mass;
- selecting between one's already paired laptop and tablet, then typing a message
  on the selected device;
- moving the actual on/off slider before packing the keyboard;
- subjective value at the selected canonical reference price.

Branch-specific meanings are selected only for actual known hardware:

- cell: opening/closing its tool-free rear compartment while replacing both AAA
  cells with matching replacements, not recharging it or claiming safe procedure;
- rechargeable: connecting/removing the actual supplied USB-A-to-USB-C lead at the
  keyboard socket and a compatible USB-A power source for charging, not USB typing
  for lit or an achieved wattage/time/endurance result;
- lit: seeing white-lit legends while typing a passage in one's dim room;
- trimode: inserting/removing its matched supplied USB-A receiver at a compatible
  laptop port while using the receiver input mode;
- trimode: connecting the supplied data lead and typing on the matching computer
  in USB keyboard mode;
- lit/trimode: assigning one function-row shortcut/one physical key using the
  respective compatible utility already configured, retaining Bluetooth(lit) or
  supplied USB data connection(trimode) in both polarities.

Public phrases are natural, e.g. “The keys felt comfortable while I typed a short
passage at a small shared table”/“...felt uncomfortable...”; “Packing this keyboard
in my usual work bag was easy”/“...was awkward”. Hardware labels/typed nominal
bases belong in meaning and factual catalog descriptions; owner prose still
retains the actual tested connection, input map, loaded utility and operation
where necessary. Neither polarity gains health, precision, speed, battery-life,
radio-range, chemical-care or universal compatibility guarantees. Source customer
reviews/marketing are not copied or converted to synthetic evidence.

Proposed exports, not automatic consumers: exact language/colour; physical key
minimum and numpad absence; scissor mechanism; nominal body footprint/mass bounds
with an exact required installed-battery basis; declared requested input route
(Bluetooth/receiver/USB data); supplied compatible receiver; rechargeable versus
replaceable-cell hardware; known batteryWh minimum; declared backlight; and known
utility support with a requested assignment scope. Guard missing request/candidate
evidence, applicability and known values before numeric comparison or set
membership. Unknown cell/lit Wh cannot satisfy an energy threshold; charging-only
USB cannot satisfy USB keyboard-input requirements; utility label alone cannot
prove general-key scope. User bag/comfort/reliability requirements need attributed
experience in the actual requested context, not private execution or mass alone.

## Gate, checks and deferred decisions

Stop at this prose gate before child/input/test authoring. After root acceptance,
retain seeds0–19 without retries and verify all12 assembly/layout/colour
singletons, joint79/80/77/78 counts, three independent body/battery/cable bases,
unknown/NA states, all catalog/owner forms/polarities and route/scope gates.
Check72 positioning-band endpoint combinations, nonzero profiles/independent
execution, exact selected-SKU price normalization and real sparse grouping with
all canonical conflicts. Reuse the frozen declaration-driven generic checker
with its known explicit exact-SKU catalog adapter; do not introduce a package
layout default to hide missing SKU context.

Deferred: other regional layouts, folding/covers/split hardware, complete matrices,
care instructions, real app/firmware/OS/receiver/cable matching, measured
switch/acoustic/latency/rollover/wear/radio/runtime/charging claims, cell electrical
arrangement and unknown energy, utility setup and production renderer/filter/task
adoption. These are explicit limits rather than assumptions inherited from desktop
or more research dependencies. No shared compiler/base edit is needed.
