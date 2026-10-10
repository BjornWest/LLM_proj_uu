# Plug-in USB wall chargers — named ports, power policy and exact bundles

Status: domain accepted in shared DSL, 2026-10-01; isolated authoring preview only. Concept `chargers.plug_in_wall_chargers`,
family `chargers`, electronics/office stores. One mains adapter; no desktop power
cord/hub, battery, wireless pad or Wh/runtime claim. Proposed consumer integration only.

## Sources and reuse

Research `.local/product-width/research/wall_chargers.md` records
[Samsung UK45W no-cable adapter](https://www.samsung.com/uk/mobile-accessories/45w-power-adapter-black-without-cable-ep-t4511nbeggb/),
[Belkin UK65W two-port offer](https://www.belkin.com/uk/p/dual-usb-c-gan-wall-charger-with-pps-65w/WCH013myBK.html)
and [Belkin family output/bundle support](https://www.belkin.com/support-article/?articleNum=333637).
Sources distinguish protocol/profile requirements, ports used together and selected
bundle contents. Shared footnotes do not override the explicit Samsung no-cable
SKU. Belkin's ambiguous65W/45W single-use footnote and20W PPS range/current
arithmetic remain source limitations, not silent corrections or achieved output.

Use a new neutral `_chargers_base.json`, concept-specific wall input, and model
identity with independent positioning/execution. Do not edit phones, cases, pilots,
compiler or lane-B bowl files. Only explicit nominal hardware/profile declarations
become facts; latency, thermal safety, device speed and private execution do not.

## Joint hardware and soft sampling

Two constructions, baseline3:2, budget5:2/mainstream3:4/premium2:5. These soft,
nonzero weights associate multiport capacity with positioning while keeping every
construction possible; no empirical market probabilities or quality ranking.

| Assembly | Hardware and fixed single-use profiles | Simultaneous policy |
| --- | --- | --- |
| Single45 | One USB-C port C1; PD3.0 PDO/PPS. Fixed5V3A,9V3A,15V3A,20V2.25A; maximum45W | C1 only, total45W; C2 absent, not a zero-power physical socket |
| Dual65 | Two labelled USB-C ports C1 upper/C2 lower; PD3.0 PDO/PPS. Either sole active port uses authored common5V3A,15V3A,20V3.25A profiles; maximum65W | With both connected, C1≤45W and C2≤20W, combined≤65W. Dual C1 fixed5V3A,9V3A,15V3A; dual C2 fixed5V3A,9V2.22A |

The dual common solo-port policy and stable upper/lower assignment are explicit
bounded authored resolutions of source gaps, not an exhaustive vendor negotiation
matrix. Reconnection interruptions, priority, simultaneous-output measurements and
input/output efficiency remain unknown. PDO tuples are separate fixed alternatives,
not an arbitrary voltage/current Cartesian space. W denotes power, not energy.

PPS constraints: Single45 V5–20,I≤2.25A,P≤45W. Dual65 solo V3.3–21,I≤3.25A,P≤65W;
dual C1 V3.3–16,I≤2.81A,P≤45W; dual C2 V3.3–11,I≤3A,P≤20W. **All three constraints
apply jointly**. The dual bottom11V×3A mathematical product does not establish33W,
and solo21V×3.25A does not establish68.25W. Values at the top of the interval need
current below its ceiling to respect the stated power cap. No promise every
interior voltage/current pair is supported or that a device negotiates maximum.
Fixed9V2.22A retains its supplied precision, not a silently rewritten2.222…A.

Single45 input voltage declaration100–240V is source-inspired. Dual input voltage,
all input current/frequency, body/plug dimensions and mass are unknown; do not mix
regional bodies, plug-inclusive sizes or bundled weights. No safety/certification
claim or mains-frequency compatibility is invented from sales country.

## Manufactured SKU choices and box facts

Manufacture nonempty subsets of exact plug labels **UK type G** and **EU type C**,
counts1/2weights3:2; black/white colours, counts1/2weights3:2; and adapter-only versus
USB-C cable bundle, counts1/2weights3:2. All selected Cartesian tuples are explicit
authored configurations. Physical plug standards and manufacture across these
regions are authoring choices, not inferred from UK vendor URLs. Do not infer
universal travel/socket fit or successful dual-input operation. Folding-pin hardware
and per-plug dimensions remain unknown. Exact plug/bundle/colour are real grouping
axes; no runtime electrical phone/cable interoperability is adopted.

One adapter per SKU. Adapter-only includes no cable; bundle includes exactly one
2m USB-C-to-USB-C cable as an authored choice. Cable current/power rating, data
capability and e-marker status remain unknown, even in the bundle. Known length and
connector do not establish a5A or65W cable. Phone, mains extension, travel adapter
and wireless pad are excluded by bound authored box facts. Case accessories or
source footnotes never establish extra contents.

Cable length is not applicable for adapter-only (not0m); cable capability is unknown
for a represented bundle and not applicable when absent. Canonical SKU rows preserve
plug, colour, bundle, inclusion/length status, anchored price factor and exact price.
Reference bands SEK150–350/300–650/550–1100, rounded5, share the positioning parent
with construction weights. Bundle multiplier1.25 versus adapter-only1, anchored
before subset sampling and never rebased. Colour/plug no surcharge. Exact selected
SKU price and global150–1375 bounds inform value; keep concentration1.5,75%silent
and accepted0.2relative-price adjustment/0.22 reviewer spread. Synthetic reference
prices are not current quotes; retailer carry/stock and device matches remain separate.

## Public wording, opinions and filter proposals

Disclose actual named ports, solo versus simultaneous ceilings, fixed PDO tuples,
PPS ranges plus their joint W caps, bundle and regional plug; unknown/inapplicable
fields need guarded/static paths. C2 fields/profiles apply only to the dual model.
No45W+65W advertised arithmetic or connector-only fast-charge conclusion. Matching
device, protocol and cable capabilities are necessary; achieved output/time unknown.

Original owner topics retain exact tested plug/bundle/colour SKU: inserting/removing
the adapter at the owner's matching wall socket; attaching/removing the owner's
USB-C cable specifically at C1; reaching C1 at the owner's usual desk; handling
adapter body beside their usual adjacent socket; packing/unpacking it in their bag;
value. Dual-only handling connects/removes two owned compatible devices using actual
USB-C cables at C1 and C2, without claiming their charging watts or uninterrupted
negotiation. Bundle-only cable handling places the included2m cable between matching
USB-C ports at the owner's usual desk; do not assert an included cable otherwise.
Both polarities retain same socket/port/cable/device/use context. No safety, efficiency,
measured temperature, speed, capacity, universal adjacent-socket fit or output performance
is inferred. Do not invent folding-pin opinions while that hardware is unknown.

Proposed predicates: exact candidate SKU plug type, known named C1 solo minimum W,
combined declared maximum, dual simultaneous C1/C2 requested minima only when C2
exists and both ceilings suffice, and explicit included-cable requirement. Required
fields absent reject. Unknown cable capability cannot satisfy current/power requests;
no such request is silently implemented. Predicate is capability ceiling, not a
promise of achieved charging. Profiles/voltage negotiation and production task/oracle
integration remain unregistered.

## Acceptance and limits

Retain0–19. Force both models, all plug/bundle/colour singletons, solo/dual scope,
known/unknown input and cable unknown/not-applicable branches; actual grouping must
preserve sparse sold-out/empty offerings and reject changed canonical box/plug/price.
Check all fixed V/A products against declared nominal W caps with supplied rounding,
all PPS ranges/limits and the20W/33W distinction independently. Use typed V/A/W
fields; finite tables can avoid unsupported cross-unit arithmetic inside the DSL,
never strip units. Verify nonzero profile weights, price endpoints and every applicable
opinion/description form/context. No source-exhaustive firmware policy, device/cable
join, charging measurement, power efficiency, regulatory assurance, body measurement
or desktop hub manufactured by this revision.
