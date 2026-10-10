# Split ergonomic keyboards — physical adjustment and scoped use

Status: domain accepted in shared DSL, 2026-10-01; isolated authoring preview only. Current concept
`keyboards.split_ergonomic_keyboards`, registered electronics/office stores.
“Ergonomic” is the registry label; no medical suitability, pain relief, injury
prevention, posture correction or typing-performance guarantee follows from it.
One complete keyboard may have one fixed split frame or two separate keying
modules. Splitting key groups, spreading modules, lateral tenting, front-edge
tilt and logical software layers are different facts.

## Sources and unchanged foundation

[Primary notes](../../../.local/product-width/research/split_ergonomic_keyboards.md)
record [ERGO K860](https://www.logitech.com/en-gb/shop/p/k860-split-ergonomic),
[Freestyle2](https://kinesis-ergo.com/shop/freestyle2-for-pc-us/) and
[Voyager](https://www.zsa.io/voyager). They establish plausible fixed/separate,
membrane/mechanical, connection and accessory distinctions. Complete construction,
regional counts, adjustment bounds, support kits and box choices below are
explicit synthetic fixtures, not named real vendor SKUs or reconstructed tests.
Source medical/comfort claims and testimonials are not imported as evidence;
source widths, cable lengths and illustrations do not establish a different
clear-gap/angle/footprint basis.

Extend frozen `_keyboards_base.json` for neutral identity, independent profiles
and retail language/colour conventions only. Override the child language enum,
manufacture and canonical schema for columnar language tuples; a UK legend set
does not force ISO geometry. Old base/desktop/slim/compiler/indices remain
read-only; no inherited dimensions, polling, force, lighting, battery status,
software or lead configuration. Public metadata follows
`product-public-assertions.md`; producer validation/export/adoption is pending.

## Three finite assemblies

| Assembly | Physical construction | Power/input and actual supplied hardware | Adjustment/support |
| --- | --- | --- | --- |
| fixed_curve | one rigid curved split frame, row-staggered full size, low-profile scissor; integrated number pad | two installed replaceable AAA alkaline cells; Bluetooth plus included matched USB-A receiver; no USB lead/socket/data input | fixed separation/splay/transverse curve; integrated nonremovable fabric/foam palm rest; front-edge pitch positions0/−4/−7° |
| separated_membrane | two row-staggered modules, rubber-dome membrane; no number pad | battery-free host USB; one fixed nominal2m USB-A host lead and fixed nominal0.5m intermodule bridge | independent desk placement; two removable foam/ABS palm supports and supplied two-support tent kit; nominal inward-roll positions0/10° |
| separated_columnar | two columnar modules,52-key compact format, low-profile linear mechanical; no number pad | battery-free host USB; detachable supplied nominal1.5m USB-A-to-USB-C data lead and matched nominal1m3.5mm four-contact intermodule bridge | independent desk placement; two supplied magnetic tent supports, nominal inward-roll positions0/5°; palm rests explicitly absent |

All have ABS bodies/keycaps by authoring choice. Columnar has steel lower base
plates and declared hot-swap sockets for its authored low-profile switch family;
replacement compatibility beyond that declaration is unknown, with no spare
switches/puller supplied. Columnar RGB key backlight is declared; brightness,
modes, controls and spectrum unknown. Fixed/membrane lighting is absent and
related light quantities NA. Keycap removal is unknown for fixed/membrane;
columnar removable keycaps declared. No other mechanical plate/socket quantities
apply to scissor/membrane configurations. Switch supplier, force/travel curves,
rollover, polling, latency, noise measurements, wear tests and certifications
remain unknown; red/brown colour names never determine behavior here.

Separation is a declared maximum clear gap200mm(membrane) or300mm(columnar)
between inner module edges, when aligned parallel and flat on the desk with the
supplied bridge routed without tension. This is an authored usable placement
bound, not bridge length, F/J-key distance or total keyboard width. In-plane splay
placement is permitted by the fixture; numeric splay limits are unknown. The
bridge restricts placement; do not promise arbitrary separation or transplant a
source9/20inch option. Fixed separation is unadjustable; adjustable-gap/splay
quantities are NA, not0mm or a declared maximum measured gap.

Inward-roll tenting raises the inside edge of each separate module using its
supplied kit. It is not front-edge pitch or clinical wrist rotation. Front-edge
pitch adjustment is present only in fixed_curve; inward-roll adjustable tenting
is absent there, while fixed transverse curve angle is unknown. Positive/negative
angle signs retain their declared axis. Tenting angles are nominal authored
positions, not tolerance, continuous ranges or raised-height measurements. The
fixed-frame front-edge foot mechanism is an authored installed fixture.

Whole configured footprint, per-module/whole-body masses, installed-battery or
supplied-set masses, raised heights and component dimensions remain unknown in
this release. A separated keyboard's envelope depends on actual gap, splay and
tent configuration; do not publish a single configuration-free width. Any later
quantity needs an explicit configuration/component/installed-parts basis. The
source accessory/shipping/body figures are not copied into another basis.

## Joint counted layouts and canonical manufacture

| Assembly | Selected language/geometry | Installed count | Enter |
| --- | --- | --- | --- |
| fixed_curve | US English ANSI / UK English ISO |104 /105|horizontal single-row / tall two-row|
| separated_membrane | US English ANSI / UK English ISO |94 /95|horizontal single-row / tall two-row|
| separated_columnar | US English columnar / UK English columnar |52 /52|one-unit rectangular key in either case|

Counts/geometry are explicit authored tuples including physical Fn/modifiers,
not percentages, keymap functions or extra keycaps. Columnar has26 physical keys
per module:24 finger positions and two thumb positions;52 includes the four
thumb keys. Columnar UK printing does not add an ISO Enter or a53rd key. The two
columnar layouts keep identical physical geometry but different declared
printed-language legends; complete legend inventory and default firmware maps
are unknown. A matching active computer input map is a separate setup requirement.
Changing layers never changes installed count or body placement.

Draw black/white and one/two layouts from the chosen assembly's applicable
US/UK pair; equal item weights, one/two cardinality weights3:2. Manufacture each
chosen Cartesian row. Four total language labels form a child enum, with no
cross-geometry manufacture. Only colour and language layout are retail axes.
Canonical row facts include owning IDs, assembly identity, count/Enter/geometry,
number-pad declaration, supplied host/bridge/receiver/kit/support declarations,
adjustment capabilities/explicit scope and exact price. Descriptive derived
facts are not extra selectors. Sparse retailer stock/carried sets follow
manufacture and cannot invent a wired receiver, UK ISO columnar model, supplied
palm rest or alternate adjustment kit.

## Power, connection, software and absence

Fixed_curve includes two installed user-replaceable AAA alkaline cells in an
authored rear compartment, an on/off control, three remembered Bluetooth host
slots/selection controls and one matched USB-A receiver. Aggregate Wh, voltage,
charge capacity, arrangement, runtime, radio version/range and receiver protocol
interchangeability are unknown. It is nonrechargeable here: device charging
socket/lead/time/input ratings are NA. The receiver is not a Bluetooth adapter
or a universal device selected by plug shape. A compatible host/source port and
actual selected Bluetooth or receiver input mode are distinct contexts.

The two separated models are wired, host-powered, battery/radio/receiver-free;
battery Wh/runtime/charge and receiver/Bluetooth quantities are NA, not0Wh or
known false capacity. Membrane host/bridge leads are fixed, with detachable
socket/plug quantities NA. Columnar host socket is USB-C; supplied host end is
USB-A. Its intermodule3.5mm four-contact connection is matched keyboard hardware,
not an audio or host USB socket. Include exactly those two leads and no adapter;
USB-C socket identity does not imply a USB-C host plug, PD or electrical rating.
Input V/A/W and cable electrical/data-speed ratings are unknown.

Basic compatible Windows/macOS/Linux input is an authored declaration, not
production interoperability. Platform/hotkey behavior, login states and firmware
versions remain unknown. Fixed/membrane remapping declaration is unknown rather
than an empty supported-system set. Columnar declares synthetic
`split_keymap_utility` for physical-key assignments and logical layers on a
compatible USB-connected host; actual max layers/default map/setup result is
unknown. No app/keymap/firmware service is supplied. A review about mapping or a
number layer requires an already configured compatible utility or matching
loaded keymap, stated connection and active computer input map. No automatic
recognition, flashing success, simpler learning or medical benefit is promised.

Every box has one complete keyboard(one body or two linked modules), its stated
batteries/leads/receiver and stated palm/tent hardware. Columnar has no palm
rests; fixed has an installed nonremovable one; membrane has two removable ones.
No mouse, wall charger, host adapter, extension, separate number pad, extra
battery, carrying case, spare keys/switches, puller, tripod/mount, trackpad/display,
knob or powered hub is included. These exclusions close source accessory/bundle
gaps explicitly. No source complete box/care inference is imported. Keyboard,
palm-pad and tent-support cleaning/water permissions remain unknown separately;
a material label or detachable pad is not permission to wash it.

## Soft profiles and selected-price review policy

Baseline fixed:membrane:columnar4:3:3; budget6:3:1,mainstream4:4:4,premium2:3:6.
Every assembly stays possible. Execution independently uniform0.05–0.95 affects
satisfaction tendency, not hardware/health/actual comfort evidence. Synthetic
anchor bandsSEK300–650/600–1500/1400–3000 by positioning, rounded5, with assembly
factors1/1.15/1.7 before manufacture. Colour/language have no surcharge and sparse
subsets do not rebase full-menu factors/bounds. Global selected-SKU bounds300–5100
SEK are not a retailer quote or a medical-quality proxy.

Standalone review selects an existing exact canonical row without regenerating
facts. Shared rating concentration1.5,75% silent weights0:24,1:4,2:3,3:1,variable
order/protected value frequency remain. At fixed rating, value favourability is
clipped normal mean(stars−1)/4−0.2*(relative_price−0.5),sd0.22,round1e−6,
positive>=0.5; relative price=(selected price−300)/4800. Other sentiments softly
follow satisfaction. Silent comments still contribute stars.

## Original owner contexts

Common feel/sound passages use one's usual desk, a matching active US/UK input
map and an explicit actual setup: fixed frame at neutral0° front pitch on an
already paired Bluetooth laptop; or linked separate halves flat/parallel with
100mm clear gap using the supplied USB host lead at a matching laptop port.
Both polarities preserve setup/connection; no inference that adjustability
improves comfort or that discomfort indicates a medical defect. Perceived sound
uses the same passage in one's quiet room, with no dB claim. Printed punctuation
is evaluated with the selected printed language and matching active computer
input map; a physical52-key layout does not establish an unmentioned number
layer. Value retains exact selected reference price.

Applicable additional topics: fixed number-pad spreadsheet entry; fixed
front-lift operation from0 to−4° on one's desk; actual palm-rest contact during
pauses(only supplied fixed/membrane supports); two-module spacing100→200mm
parallel/flat with supplied bridge untensioned; supplied tent-kit operation from
flat to its declared raised position(10°membrane/5°columnar); actual wired host
lead handling; columnar matched intermodule connection with host USB unplugged;
columnar one-key assignment with compatible utility configured on the USB host;
and use of one's configured number layer with matching keymap loaded, declared
computer input map and supplied USB connection. Host disconnect is an operation
context, not a safety or repair assurance. No hot-swap replacement, battery
endurance, spill/chemical-care, medical recovery or speed/accuracy topic.

Natural text examples and both polarity wordings are source-pinned in the
annotation language plan. Their assertion audit follows below; no boilerplate
claim of first-hand experience is required in every sentence. Structured meaning
retains first-hand provenance, selected SKU, actual configuration and operation.

## Public assertion audit and draft companion

Owned drafts in `.local/product-width/annotations/keyboards.split_ergonomic_keyboards/`
contain `language-plan-v3.json`, `public-content-draft-v3.json` and
`assertion-audit-v3.md`. These pin the prose, exact prospective wording order,
neutral base and contract fixture. No executable child exists yet: planned field
paths/pools require later binding to the actual child plus recursive source
hashes and Product's validator. This is neither a validated capability nor browser
JSON, publication ledger, discovered evidence, implementation test or readiness
promotion. The production companion path is reserved for after the DSL gate.

Audit actual communicated meanings rather than a union of fact-paths. Product
construction/adjustment declarations remain product-scoped; selected printed
layout/count/colour are exact-SKU facts. Component care/materials refer to the
actual palm supports/lower baseplates/lead, not every part. Gap requires the
inner-edge, flat/parallel, untensioned-bridge basis; angles preserve roll versus
pitch, nominal position and supplied support. Runtime/energy/care unavailable
states are communicated only by explicit unknown/NA wording; never interpolate
sentinels. Private positioning/execution, weights, price normalization and
applicability prerequisites are not public assertions merely by being referenced.

The fixed-shape pair intentionally demonstrates a useful incidental extra:
formulation0 says the split key groups share one rigid body; formulation1 also
explicitly says they cannot be separated. Common claims are split key groups
and one body; only formulation1 credits unadjustable separation. No registered
inference from “rigid” is assumed. Other pairs are normalized to state the same
listed claims; no unmentioned numerical angle, material or installed kit is
credited from a guard. Review entries credit the full attributed
aspect/polarity/context at the tested SKU, without becoming objective performance
or manufacturer/medical authority. Review/reviewer provenance resolution remains
an exporter dependency, not an invented existing field. The executable companion must
bind the actual tested `review.subject.sku_id` and copy the exact DSL meaning
object for the selected occurrence, including its resolved configuration; no
ambient `sku` alias, default setup or union of alternative assemblies may stand
in for that attribution. The cell-powered catalog forms explicitly state that
on-device charging and charge time are inapplicable.

## Proposals, gate and deferred decisions

Proposed filters: selected language/geometry/count/number pad, known mechanism,
separate-module versus fixed split, declared clear-gap support on its exact
basis, requested nominal tent/pitch position on its own axis, included/removable
palm supports, actual input route/supplied receiver, declared backlight/hot-swap
and known utility scope. Missing request/candidate or unavailable evidence
rejects; known/applicable guards precede membership/comparison. Body-size/mass,
quantitative battery energy, runtime and clinical suitability predicates are
explicitly deferred here. Customer comfort/learning/operation requirements need
attributed evidence in the requested exact context, not execution or capability
labels. Bindings remain proposals, not adopted task/oracle/filter consumers.

Stop for root prose/audit gate. After acceptance retain seeds0–19,all12
assembly/layout/colour singletons and72 price endpoint combinations, both
polarities/all wording, fixed versus separate adjustment axes and every
battery/interface/unknown/NA branch. Verify columnar UK remains52/columnar,
gap is not cable length, slot/guard references do not overcredit assertions,
formulation-specific extra stays chosen-only, exact-SKU grouping/canonical
conflicts/value normalization and source pins. No shared validator/compiler
implementation, old-source annotation migration or automatic website adoption
is authorized by this document.

Deferred: complete key matrices/default maps, other language/blank/cap options,
real software/firmware/receiver interoperability, measured care/geometry/mass/
force/acoustics/latency/range/runtime/health outcomes, alternative accessory kits,
continuous splay/tent ranges, medical tasks and producer/export/publication-ledger
acceptance. No additional research or compiler workaround is needed for this
bounded authoring design.
