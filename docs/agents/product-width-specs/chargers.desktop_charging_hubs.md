# Desktop charging hubs — output scope and two different cable roles

Status: domain accepted in shared DSL, 2026-10-01; isolated authoring preview only. Concept
`chargers.desktop_charging_hubs`, electronics/office stores. One mains-powered
freestanding charging body with a mains lead and multiple device outputs. This
recipe has no battery, wireless pad, display, controls, USB host/data uplink,
Ethernet, video or removable stand; these are explicit authored boundaries.
It does not imply other charging hubs lack them. Existing wall adapters stay frozen.

## Primary sources and reuse

[Belkin UK108W mixed-port charger](https://www.belkin.com/uk/p/4-port-gan-charger-108w/WCH010myWH.html)
and [Belkin UK200W USB-C charger](https://www.belkin.com/uk/p/200w-4-port-usb-c-gan-charger/WCH015myWH.html)
are recorded in `.local/product-width/research/desktop_charging_hubs.md`.
They distinguish mains leads from separately purchased device cables, total from
single-port maxima, and listed sizes from unspecified measurement bases. Vendor
fast-charge test timings, recycling proportions and missing output allocations are
not transferred into synthetic product facts or owner outcomes.

Reuse frozen `_chargers_base.json` identity, independently sampled positioning and
execution, and plug/colour/bundle manufacture interfaces. Replace the child SKU
schema, price bands and bundle vocabulary explicitly. A selected plug belongs to
the included mains lead, not a wall-adapter body. Wall PDO/PPS tables, device-cable
lengths and hardware are not inherited as desktop facts.

## Joint constructions and soft profiles

Two source-inspired constructions, mixed108:C4_200 baseline3:2, budget5:2,
mainstream3:4,premium2:5. Every alternative remains possible; execution is independent
uniform0.05–0.95. These are authored nonzero associations, not measured market rates.

| Construction | Outputs and protocol declarations | Power scope | Included mains lead |
| --- | --- | --- | --- |
| mixed108 | C1/C2 USB-C plus A1/A2 USB-A; USB-C PD3.0, USB-A protocol unknown | combined108W; every named port's solo maximum and all simultaneous allocations unknown | nominal2m; detachability/inlet unknown |
| C4_200 | C1/C2/C3/C4 USB-C; model-level PD3.1 EPR/PD3.0 support | combined200W; at least one output has a single-port140W declaration, specific output unidentified; named maxima and simultaneous allocations unknown | detachable nominal1.5m; inlet type unknown |

C1/C2/A1/A2 or C1–C4 are authored stable port identifiers, without asserting a
physical ordering or a vendor's140W port assignment. PD3.1 at model level does not
prove every port supports EPR. The140W existential single-output ceiling is not
four140W outputs,140W on C1, or two140W simultaneous outputs. No allocation table is
invented to fill the source gap; simultaneous use remains subject to the combined
cap but its distribution is unknown. Fixed V/A alternatives, PPS support/ranges,
per-port protocol allocation, priority, reconnect interruptions and achieved watts
or time remain unknown. Unknown profiles are neither zero-power nor unsupported.

Input voltage/current/frequency, body/cord/package masses, inlet standard and all
plug dimensions are unknown. mixed108 body dimensions are unknown. C4_200 retains
listed nominal4.7×3.6×1.4in L×W×H; a derived approximate119×91×36mm representation
rounds the25.4mm/in conversion to whole mm and expressly remains a rounded label,
not a measured or more precise body size. Whether the vendor's listed dimensions
include cord/plug is unknown; it is not package size. The source5ft/1.5m lead keeps
its nominal metric1.5m label, not an exact1.524m measurement. Private execution never
supplies mass, efficiency, safety, electrical compatibility or observed speed.

## Exact manufacture, two cables and prices

Draw nonempty subsets of UK typeG and EU typeC mains plugs, black/white cosmetic
colours, and `mains_only`/`mains_plus_usb_c` bundles; each two-option subset has equal
eligible item weights and one/two cardinality weights3:2. All selected Cartesian
rows are authored manufacture, not inferred regional availability from UK URLs.
Plug is an included-lead choice, not evidence of universal input compatibility.

Every row includes one charging body and one mains lead of its construction's
nominal length. `mains_only` excludes a device cable; `mains_plus_usb_c` adds one
nominal2m USB-C-to-USB-C device cable. That optional cable's current/power/data and
e-marker capabilities are unknown; length/capability are inapplicable if absent.
It is not rated140W just because a represented output has that maximum. The USB-C
cable is for a matching USB-C output, not the mixed model's USB-A outputs. Phones,
laptops, mains extension, travel adapter and wireless pad are explicitly excluded.
Source mains-lead length never supplies device-cable length or inclusion.

Canonical rows preserve plug/colour/bundle, mains lead inclusion/length/detachability,
device-cable inclusion/length/capability statuses, anchored bundle factor and price.
Only plug/colour/bundle are grouping axes. A changed canonical lead length or bundle
fact must reject even if it is not a selector. Manufacturer SKUs do not force stock.

Reference anchors SEK300–600/500–1000/850–1600 by positioning, rounded5. The USB-C
bundle multiplies anchor by1.15 versus1 for mains-only, before subset manufacture;
no rebasing when only a bundled row exists and no plug/colour surcharge. Selected
canonical SKU price uses global300–1840SEK value bounds. Keep concentration1.5,
75% silent comments and the accepted0.2 price-position adjustment/0.22 spread;
reference prices are synthetic, not current offers or an electrical quality score.

## Catalog, first-hand wording and proposed predicates

Descriptions disclose exact output identities/connectors, model protocol scope,
combined versus unidentified single-port maximum, unknown named maxima/allocations,
the two cable roles, correct nominal dimension/length basis, component inclusion
and guarded unknowns. A SKU-scoped statement requires that actual row, never a
silent first bundle. No per-port count multiplication or invented charging matrix.

Original owner topics: placing/repositioning the body on the owner's usual desk;
reaching actual C1 at that desk; attaching/removing the owner's own compatible USB-C
cable at C1; routing the represented mains lead from the body to the owner's matching
socket; arranging two owned compatible USB-C device cables at C1 and C2 on the desk;
packing/unpacking the body and mains lead in the owner's bag; subjective value.
Detach/refit mains-lead handling is eligible only for known detachable hardware,
with the lead unplugged from the wall first. Included-device-cable handling is
eligible only for a tested USB-C bundle, between matching USB-C ports at the usual
desk. Both polarities preserve the same operation/lead/port/context, in natural
owner language. These experiences do not establish output, negotiated speed,
continuous charging, safety, thermal measurements or universal desk/socket reach.
No screen/stand/rubber-foot opinions are invented while those parts are absent or
unspecified. The provided2m mains lead must not appear as an included2m USB cable.

Proposed filters require explicit evidence: exact selected mains plug, minimum
combined W ceiling, minimum USB-C/USB-A counts, minimum selected mains-lead length,
known detachable lead, and explicit USB device-cable inclusion. An unidentified
140W output may answer a clearly existential maximum-output question, but cannot
satisfy a named-C1 or simultaneous device request. Missing requested thresholds or
selected-row facts reject. Unknown per-port/device-cable capacities cannot silently
match a power requirement. All declarations are ceilings/labels, not device joins
or achieved performance. Production task/filter/oracle adoption stays deferred.

## Acceptance and limits

Retain0–19, both constructions, all plug/colour/bundle singleton combinations and
anchor endpoints. Check declared positive totals, four actual outputs and the
unknown named/parallel policy;140W is a qualified existential fact only. Preserve
source nominal in/mm representation and unspecified dimension inclusion, including
unknown/inapplicable branches for unplugged/refitted mains hardware and absent USB
cables. Check every applicable public formulation and both owner polarities,
canonical sparse/sold-out/empty grouping and conflicts, exact tested price and
nonzero positioning weights independent of execution. No shared base/wall change.

Deferred: complete allocation/negotiation table, protocol compatibility, device/cable
join, actual watts/time, USB data, regulatory/thermal/efficiency tests, measured
body/lead/plug dimensions, safe regional mains compatibility and production adoption.
