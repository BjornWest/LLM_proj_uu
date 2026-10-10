# Desktop keyboards — physical layouts, wired leads and scoped owner use

Status: domain accepted in shared DSL, 2026-10-01; isolated authoring preview only. Concept `keyboards.desktop_keyboards`,
family `keyboards`, registered electronics/office stores. One freestanding,
unsplit desktop keyboard. Current bounded recipe is host-powered and wired only;
no wireless receiver/Bluetooth/radio, battery, rechargeable runtime, split halves,
trackpad, display, knob, wrist rest or powered USB hub. Those exclusions are
explicit authored facts for these fixtures, not claims about all desktop keyboards.

## Source status and foundation

Primary observations are in `.local/product-width/research/desktop_keyboards.md`:
[Logitech K120](https://www.logitech.com/en-gb/shop/p/k120-usb-standard-computer)
supports the full-size number-pad, corded office and tilt-leg example;
[Keychron C3 Pro](https://www.keychron.com/products/keychron-c3-pro-qmk-via-wired-mechanical-keyboard)
supports mechanical TKL, USB-C/Type-A-to-Type-C lead, red-light and QMK/VIA examples.
The inspected texts do not supply exact regional key counts, complete manufacture
menus or complete box lists. Office membrane chemistry/fixed lead, regional tuples,
our physical quantities, switch behavior, soldered switches and box exclusions below
are explicit authored choices. These synthetic models are not named vendor SKUs.
Vendor comfort, acoustic, spill, durability, latency or gaming marketing becomes
neither objective fact nor sampled customer evidence.

Proposed new `_keyboards_base.json` has the neutral contract in `_keyboards-base.md`.
Reuse identity and independent positioning/execution only. Replace manufacture
and price/SKU schema for this child; frozen electronics and charger sources are
read-only. Keyboard capabilities never come from the existing colour foundation.

## Model assemblies and soft associations

Three finite, unsplit constructions. Model-level mechanism means the installed
keys use the selected factory mechanism; changing switch type defines a different
model assembly here, not a retail switch selector or promised user replacement.

| Assembly | Format and mechanism | Construction | USB lead and socket | Lighting and remapping |
| --- | --- | --- | --- | --- |
| office_full | full-size with integrated number pad; authored rubber-dome membrane | ABS body and keycaps; mechanical-switch plate not applicable | one fixed nominal1.5m lead with USB-A host plug; no user-removable keyboard socket | lighting explicitly absent; remapping declaration unknown |
| mechanical_linear | TKL80% with number pad explicitly absent; authored linear mechanical switches | ABS body/keycaps and steel switch plate; factory soldered, no hot-swap sockets | one included detachable nominal2m USB-A-to-USB-C data lead; keyboard USB-C socket | declared red key backlight; QMK/VIA support with matching configuration |
| mechanical_tactile | same TKL80% format; authored tactile mechanical switches | same bounded body/plate/keycap construction and soldered restriction | same detachable lead/socket declaration | same red-light and remapping declaration |

Linear/tactile behavior is authored directly, not inferred from red/brown switch
names. Individual force/travel curves, exact switch supplier/model, rated cycles,
stabilizer behavior, acoustic levels and keycap wear tests remain unknown. All
three have fold-out tilt feet; two positions(folded/raised) are an authored fixture.
Raised heights, angles, foot material/grip and ergonomic effectiveness are unknown.
Mechanical red-light presence is known; exact brightness, modes, spectrum, controls
and software-version behavior are unknown. Office light colour/brightness/modes
are inapplicable, not known black/off LEDs. Mechanical keycaps are removable;
office keycap-removal declaration is unknown. No keycap-removal topic is required.

Baseline office:linear:tactile4:3:3; positioning budget8:2:2,
mainstream5:4:4,premium3:6:6. Every assembly remains possible. Execution is independently
sampled uniform0.05–0.95; it cannot supply material, input ratings, switches or
hardware. These are tunable soft associations, not prices/market measurements.

## Joint physical layout and counted-key tuples

Manufactured language layouts are exact authored combinations of printed legends
and physical geometry, not just a software language preference:

| Format | Selected language/physical layout | Physical key count | Enter key geometry |
| --- | --- | --- | --- |
| office_full | US English ANSI |104|horizontal single-row Enter|
| office_full | UK English ISO |105|tall two-row Enter|
| either mechanical TKL | US English ANSI |87|horizontal single-row Enter|
| either mechanical TKL | UK English ISO |88|tall two-row Enter|

Counts describe installed physical key positions, including physical modifiers or
Fn where present; firmware layers and spare keycaps do not add keys. Regional
printed legend set and modifier positions are authored to match the chosen tuple.
Full-size retains navigation/arrow/function keys and a number pad; TKL retains
navigation/arrow/function keys but excludes the number pad.80% is a format label,
not an arithmetic percentage of104. No Nordic/JIS/other ISO map, split geometry,
complete scan matrix or exact row spacing is supplied in this release.

These four count/geometry tuples are declared fixtures, not vendor measurements
or a universal rule that every ANSI/ISO keyboard has these counts. Host OS input
layout and optional firmware remapping remain separate. Printed UK legends do
not force the computer to use a UK input map; US physical geometry does not change
by choosing a UK software map. A task about a symbol needs an explicit matching
physical legend/input-map context, not a colour or format substring.

Authored nominal outer width/depth/maximum height is450/155/28mm for office and
370/135/42mm for either mechanical construction. This includes installed keycaps
with tilt feet folded, excludes the routed USB lead, and is not a raised-foot size
or a measured source housing. Authored complete supplied-set mass is550g office,
950g mechanical: assembled keyboard plus its one supplied USB lead, excluding
packaging/accessories. Body-only, cable-only and packaging masses are unknown;
do not subtract an invented cable mass. Both language layouts share those nominal
quantities by explicit authoring choice. Source C3 front/back heights and912±10g
with unspecified cable/angle basis are not copied into this different basis.

## Host connection, statuses and box facts

All three are declared USB keyboard devices for basic input on compatible
Windows/macOS/Linux hosts, an authored compatibility declaration rather than
production interoperability validation. Included host connector is USB-A; a
USB-C-only host would require separately supplied matching hardware, not a silently
included adapter. Office has a fixed lead and no exposed detachable keyboard-side
socket, so detachable socket/end quantities are inapplicable. Mechanical keyboard
socket and detachable lead's keyboard plug are USB-C; this is not a USB-C host plug,
a power-delivery rating or a wireless receiver. Lead length is nominal, not tolerance
or universal desk reach. Input voltage/current/power, cable electrical/data-speed
ratings, enumeration timing, host adapters and actual latency remain unknown.
Battery capacity in Wh and charge/runtime quantities are not applicable to this
explicit battery-free fixture; do not invent0Wh or derive capacity from hours.

Mechanical polling frequency is declared1000Hz; office polling declaration is
unknown. Polling is not measured input latency or improved typing speed. QMK/VIA
support is declared for mechanical models; source recognition/manual-keymap caveat
stays explicit. It does not promise every browser/OS, automatic identification,
firmware flashing success or current software version. Office remapping support
is unknown, not an empty known support set or evidence of impossibility. If a
proposed predicate needs a remapping system, guard known support before membership.
No installed key map, specific software download or browser service is supplied.

Every row includes one assembled keyboard with its represented one USB lead.
Mechanical lead is a separate detachable included item; office lead is attached.
No mouse, receiver, wall charger, host adapter, extension, detachable number pad,
wrist rest, spare switches/keycaps, puller or stand is included. These explicit
box exclusions are authored, not deductions from empty source box sections.
Hardware that is absent has not-applicable related quantities; unspecified
capability of present hardware remains unknown. Material/printed-symbol/rating
information does not establish spill protection, certification or clinical comfort.

## Canonical manufacture and exact prices

Draw nonempty subsets of black/white cosmetic colours and US English ANSI/UK English
ISO layouts. Both menus have equal item weights and one/two cardinality weights3:2.
Every chosen Cartesian row is manufactured. These colours/regional combinations
are authored rather than inferred from UK URLs or vendor palette omissions.
Only colour and language layout are retail selector/separate-page axes. Key count,
physical layout/Enter geometry, connector/lead inclusion/length/detachability,
assembly factor and exact reference price stay canonical row facts; changing one
in a listing must reject. Retailer may carry a sparse subset or none, with sold-out
variants retained. No stock draw is manufacturer truth.

Reference anchor bands are synthetic SEK120–350/250–800/600–1500 by positioning,
rounded5. Assembly factors office1,linear1.25,tactile1.3 apply before manufacture,
with no language/colour surcharge or rebasing for sparse subsets. A canonical row
uses the selected assembly factor and exact price; bounds for selected-SKU value
are global120–1950SEK. Neither a real seller quote nor latent electrical/ergonomic
quality is represented by that price. Reference quantities/basis are declared,
not simulated lab measurements.

## Review meanings and useful proposed tasks

A reviewer selects an existing exact canonical row without regenerating product
facts. Stars use shared concentration1.5. Topic-count weights0:24,1:4,2:3,3:1 preserve
75% silence; a silent review still contributes stars. Variable topic/order and
protected pilot value frequency remain. At fixed rating, clipped normal value
favourability has mean(stars−1)/4−0.2*(relative_price−0.5),sd0.22,round1e−6,
with positive sentiment at>=0.5. Relative price is(selected price−120)/1830.
Other sentiments depend softly on sampled satisfaction, not factual performance.

Original owner meanings retain operation, exact SKU, provenance and both polarities:

- typing feel while writing an ordinary text passage at one's usual desk;
- perceived key sound while typing that text in one's quiet room, with no dB claim;
- locating printed punctuation while using the stated matching OS input layout;
- inserting/removing the supplied USB-A host plug at one's matching computer port
  and routing its actual lead on the usual desk;
- adjusting the actual tilt feet between folded/raised positions at that desk;
- spreadsheet number entry on the integrated number pad, only office models;
- seeing red-lit legends while typing in one's dim room, only mechanical lighting;
- connecting/removing the supplied detachable lead at the keyboard's actual USB-C
  socket, only known detachable hardware;
- optional one-key remapping only declared mechanical support, with a compatible
  computer and the matching configuration loaded, explicitly retaining that setup;
- subjective value at the exact selected synthetic reference price.

Owner text is natural: e.g. “The keys felt comfortable while I typed a text passage
at my usual desk” versus “The keys felt uncomfortable…”; neither becomes a universal
comfort, wrist-health, speed or accuracy result. Both polarity forms keep the same
text/desk, quiet-room, matching-map, lead/port or loaded-config condition. Do not
invent lighting/removable socket/numpad/remapping opinions for ineligible hardware.
No source marketing or customer review is copied as evidence.

Proposed bindings(not automatic consumers): exact selected language/colour,
minimum physical key count, number-pad presence, model mechanism, declared wired
connection/host plug, nominal footprint bounds with this feet/keycap basis,
known detachable keyboard lead, known backlight presence and known requested
remapping-system support. Missing request/candidate evidence rejects. A current
layout/count must be bound from that canonical row, never a default largest/US
layout. Unknown office remapping/polling cannot satisfy those capability requests;
firmware maps and USB interfaces do not establish physical printed-language fit.
Customer requirements about feel/sound retain their exact use context and evidence
source rather than treating private execution or fact labels as proof.

## Gate and deferred questions

This is prose only, awaiting root independent acceptance before JSON/base/test
implementation. Later closure will retain0–19 without retries, all three assemblies,
four physical format/layout tuples, both colours, all12 assembly/layout/colour
singletons and72 positioning-band endpoint combinations. Verify typed units,
unknown/NA branches, all natural public forms/polarities, gated hardware topics,
exact selected-SKU pricing, sparse/grouping/conflict behavior and independent
execution/nonzero profiles. Old foundations/indices/pilot worlds remain untouched.

Deferred uncertainties are explicit: full key matrix/legend inventory, Nordic/JIS,
wireless/battery variants, hot-swap models, force/travel/noise/latency/wear/spill
measurements, raised-foot dimensions and comfort effects, host/cable negotiation,
firmware/software version interoperability, automatic remapping and production
renderer/filter/task/oracle adoption. No systemic compiler change is assumed.
