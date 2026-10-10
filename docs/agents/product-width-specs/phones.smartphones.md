# Smartphones — bounded model and manufactured configuration recipe

Status: domain accepted in shared DSL, 2026-10-01; isolated authoring preview only. Concept `phones.smartphones`, family
`phones`, electronics store theme. Unlocked handheld smartphones, not tablets,
feature phones, refurbished-condition offers or contracts. This is an additive
authoring recipe; task/oracle/production adoption remains proposed.

## Primary examples and reuse

Four manufacturer examples are recorded in
`.local/product-width/research/smartphones.md`: [Samsung A16 5G UK](https://www.samsung.com/uk/smartphones/galaxy-a/galaxy-a16-5g-blue-black-128gb-sm-a166bzkdeub/),
[Pixel 9a GB](https://store.google.com/gb/product/pixel_9a_specs?hl=en-GB),
[S25 Ultra UK technical table](https://news.samsung.com/uk/samsung-galaxy-s25-series-sets-the-standard-of-ai-phone-as-a-true-ai-companion)
and [iPhone 16 UK specifications](https://www.apple.com/uk/iphone-16/specs/).
They establish plausible joint assemblies and distinctions, not recipe weights,
current prices, every manufactured regional variant or observed customer quality.
Synthetic model names and brand fixtures do not claim these vendors manufacture
the generated phones. Example technical combinations are bounded inspirations.

Reuse independent positioning/execution and the accepted rating/topic/value policy.
Add a neutral phone base rather than change the frozen colour-only headphone base.
No headphone controls, battery-hour equivalence, ear fit, shoe or clothing fields
are inherited. All device configurations bind the same model hardware and region;
retailer carry/stock, subscriptions, accessories sold separately and offer prices
remain downstream states.

## Joint model assemblies

One UK regional fixture, with four authored assemblies and the positioning-conditioned weights documented below:

| Assembly | Platform and coherent physical display/body | Declared memory manufacture |
| --- | --- | --- |
| Android entry | Android; 164.4×77.9×7.9 mm H×W×D, 200 g; full-rectangle 6.7-inch AMOLED, maximum 90 Hz | 4 GB RAM; 128 GB storage only |
| Android mid | Android; 154.7×73.3×8.9 mm, 186 g; 160 mm display diagonal, pOLED, 60–120 Hz | 8 GB RAM; 128/256 GB storage |
| Android large | Android; 162.8×77.6×8.2 mm, 218 g; full-rectangle 6.9-inch AMOLED, 1–120 Hz | 12 GB RAM; 256 GB/512 GB/1 TB storage (decimal comparison value 1000 GB) |
| iOS compact | iOS; 147.6×71.6×7.8 mm, 170 g; standard-rectangle 6.12-inch OLED (nominal marketed label 6.1 inches); refresh rate unknown | RAM unknown; 128 GB storage only |

Mid display uses its supplied millimetre diagonal; other diagonals use inches.
Expose the measurement and unit separately, rather than secretly convert a rounded
160 mm source label to an exact 6.3-inch claim. Declared body measurements and
masses refer to the phone, not packaging, accessories, case or screen-only area.
Rounded corners and usable display area are unspecified. Processor labels are
authored assembly identifiers, not benchmark rankings. Market positioning softly steers cost-related hardware bundles, not private execution or objective performance. Conditional entry/mid/large/iOS weights are budget8:3:1:2, mainstream3:6:2:2 and premium1:3:6:2. All alternatives remain possible; these authored heuristic weights favor entry, mid and richer large hardware respectively, without declaring a bigger screen or iOS inherently superior. Execution stays independent. The old constant3:3:2:2 recipe and wave12 remain historical.

Model RAM is constant across the authored storage variants; no independently
selected RAM menu. iOS RAM is a genuine unknown, not zero and not inapplicable.
Nominal advertised storage is not usable free storage; the latter remains unknown. Retain the advertised storage label separately from its decimal-GB comparison value: 1 TB maps explicitly to 1000 GB, not 1024 GB. This nominal decimal mapping is not a filesystem/usable-space conversion.
Sample a nonempty subset of each assembly's supported storage menu, allowing a
singleton. Sample nonempty black/white/blue colour subsets independently, then
manufacture the Cartesian combinations in this *authored* recipe. That combination
rule is not attributed to the inspected vendors. Storage and colour selectors or
separate pages are retailer decisions; RAM and reference price remain canonical
facts rather than additional SKU axes.

## Capacity, charging, hardware and missing declarations

Android nominal charge capacity uses a separate typical/minimum-or-rated pair:
entry 5000/4860 mAh (rated lower figure), mid 5100/5000 mAh (minimum), large
5000/4855 mAh (minimum). iOS charge capacity is unknown. Nominal battery energy Wh,
cell voltage, usable energy and actual endurance remain unknown for all assemblies.
Do not derive Wh from mAh or hours, or infer charge time/runtime from capacity.
No source runtime/percentage claim is copied into actual customer evidence.

All phones recharge through USB-C. Device wired-input power ceilings remain unknown for every assembly. The entry example refers to a 25 W adapter, the large example to a 45 W adapter used for its charging claim, and iOS to a 20 W-or-higher wired adapter. Record those adapter contexts separately as supported recommendation/test bases; no adapter nameplate establishes a device-input limit. Mid adapter power remains unknown. All include a charging cable and exclude
the power adapter as an explicit authored box choice, including where a source's
box-list omission alone would not prove that negative. Compatible accessories
and actual achieved charging speed remain unspecified. Entry wireless charging
is unknown; the other assemblies support a compatible wireless route. Its maximum
is 25 W for iOS, unknown for the others; pad not included. Unknown wireless support
does not mean unsupported. No stand, magnetic case or included pad is invented.

USB data declaration is USB 2.0 for entry/iOS and USB 3.2 for mid; large stays
unknown because the inspected launch table does not establish it. Supplied cable
data capability is unknown except mid's USB 2.0 cable. Port and cable versions
are distinct and do not establish achieved bandwidth or charging power.

Regional 5G is supported without guaranteed carrier/network coverage. Entry's
second physical slot is hybrid nano-SIM-or-microSD, not simultaneous second SIM
and card. Mid uses nano-SIM plus eSIM; iOS nano-SIM/eSIM or dual eSIM; large SIM
configuration is unknown. No universal global compatibility, unrestricted eSIM
count, simultaneous profiles or third-party accessory compatibility follows.
Wi-Fi/Bluetooth declarations remain attached to their source-inspired assembly:
entry ac/5.3, mid 6E/5.3, large 7/5.4, iOS 7/5.3. Required compatible router and
regional infrastructure are not generated here.

Camera arrays are model constructions: entry 50 MP main, 5 MP ultrawide and
2 MP macro; mid 48 MP main plus 13 MP ultrawide; large 200 MP main,
50 MP ultrawide, 50 MP 5× telephoto and 10 MP 3× telephoto; iOS 48 MP main
plus 12 MP ultrawide. iOS main-sensor 2× mode is not another physical lens.
OIS declaration is false for entry and true for the other primary cameras as an
explicit bounded assembly choice; no MP/OIS/lens count implies good image quality.

IP disclosure is known/unknown 3:1 independently of other hardware, an authored
missing-disclosure dial, not empirical prevalence or proof that undisclosed devices
have no protection. Known entry declaration IP54 retains its supplied spray-test
context; large IP68 retains 1.5 m fresh water/30 minutes, iOS IP68 retains
6 m/30 minutes, mid IP68 has unknown numerical protocol details. Unknown label
also has unknown test protocol. Every language/filter branch guards unknowns;
no waterproof, immersion-use, durability, permanent resistance or health assurance.

Entry declares up to six OS generations and up to six security years; large declares seven OS generations and seven security years from global model launch. Mid declares a seven-year OS-update period and seven-year security period, while its OS-generation count is unknown. Years and generation counts are separate claims; entry retains the up-to qualifier. Mid’s launch-based time origin is an explicitly authored fixture choice because the inspected excerpt does not establish the origin. Launch calendar dates and remaining support at purchase are unknown, so do not report any of these as remaining years from today.
iOS fixed support counts/period are unknown; that is not zero support. Installed
OS version, exact end date, future-feature support and carrier update schedules
remain unspecified. Years and OS generations are separate typed quantities.

## Reference price and exact-SKU opinions

Reference bands share the positioning parent with assembly probabilities: budget SEK1500–4500, mainstream
3500–9000, premium 7000–18000, rounded10. These are tunable synthetic model bands,
not current market quotes or a guarantee that each platform appears at every price.
They apply to the minimum supported storage of the sampled assembly. Increasing
storage has authored factors 1/1.12/1.25 for successive capacities in the full assembly menu, not the sampled manufactured subset. A mid 256 GB SKU keeps factor1.12 even when 128 GB is not manufactured, and a large 512 GB SKU keeps factor1.12 when 256 GB is absent;
colour has no reference surcharge. Exact canonical SKU prices preserve those
factors. Global category value bounds are SEK1500–22500 for every selected SKU;
actual selected capacity cost therefore affects relative price instead of being
silently replaced by the model's cheapest configuration. These bounds must cover
all reference endpoints. Private positioning/execution are not public claims.

Retain concentration1.5 and75% silent ratings. Original first-hand topics:
daylight static-scene satisfaction using the main rear camera; handheld indoor
low-light moving-subject satisfaction using the main camera; whether the owner's
usual day of calls/messages/navigation leaves charge; ordinary app switching and
typing on the tested storage configuration; subjective one-handed grip using that
model body; operating actual USB-C cable attachment; and value. Both polarity
wordings retain the same operation/context and exact tested colour/storage SKU.
No invented recharge schedule, achieved throughput, clinical hand fit, battery
degradation, drop survival or manufacturer test result is implied. Battery opinions
are owner experiences rather than measured capacity-to-runtime predictions.

## Acceptance and limits

Retain all seeds0–19. Force all four assemblies, singleton/all storage menus,
colour subsets, three SKU price-factor endpoints, known/unknown IP and all guarded
unknown disclosures. Check each body/screen unit, lens count, primary OIS, separate
mAh/Wh/runtime semantics, hybrid slot, unknown RAM, port-versus-cable data and
launch-versus-remaining update claims. Force every opinion/polarity/formulation;
reject missing request inputs rather than inventing thresholds. Sparse, sold-out
and empty retailer projections preserve every canonical SKU fact.

Storage/OS/minimum nominal battery/IP request predicates are reusable exported
proposals, not registered task semantics. No generic camera-quality predicate is
derived from MP. Deep carrier/band matrices, software feature versions, measured
battery protocols, charging curves, processor benchmarks, repairability, foldables,
used condition, warranties and production phone renderer adoption are deferred.
This concept is executable only after independent current-source DSL acceptance.
