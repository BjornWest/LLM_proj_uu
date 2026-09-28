# Comparing offers while preserving shopping intent

Design brief captured from Bjorn’s shoe-shopping experience, 2026-09-21.
**Proposed challenges, not implemented tasks or verified dataset coverage.**
This records the experience and intended training direction before details are
lost. It does not change the current Prislyktan tasks, prices or graders.

The central challenge is to find the best **eligible, genuinely comparable
offer**, then preserve those conditions through checkout. A simple request for
one particular shoe can require substantial investigation across an aggregator,
product pages, delivery terms and checkout. Many apparent bargains cease to be
eligible once the exact variant, conditions and delivered cost are checked.

## Patterns from the experience

| Dimension | What can go wrong | What the task should exercise |
|---|---|---|
| Exact product | A result is a different shoe model, color or version despite a similar image/name. | Match model and requested attributes; reject unauthorized substitutions. |
| Size-specific price | The aggregator’s attractive price applies to another size. The retailer can preserve the requested size while still displaying the other size’s advertised price elsewhere. | Check the price for the actual selected size, not just the link or headline. |
| Variant persistence | A link, page transition or cart operation loses the selected size/color, or selects a default. | Ensure the committed item is the requested variant; track where state changed. |
| Stale quote | An aggregator price belongs to an expired campaign or is simply outdated. | Reconcile the quote with current retailer and checkout prices. Prislyktan already has a simple stale-quote example; these proposals go further. |
| Shipping inclusion | Some quoted prices include shipping and others exclude it. | Normalize comparisons without omitting or double-counting shipping. |
| Shipping choice | Several methods have different prices and arrival times; the default is slow. | Compare complete product-plus-delivery combinations. A cheap product with expensive fast delivery may still be the cheapest eligible choice. |
| Delivery deadline | The item ships soon but arrives too late, or an arrival range crosses the deadline. | Distinguish dispatch from arrival and apply the task’s declared deadline/uncertainty policy. |
| Delivery preference | Pickup station and home delivery are not interchangeable for this user. | Apply an explicit instruction or a supplied remembered preference, with current instructions taking precedence. |
| Conditional discount | The headline price requires buying a second item the user does not want. | Exclude that discounted offer from the authorized comparison; do not add an unwanted item to unlock it. |
| Currency and destination | A Dutch retailer may offer SEK and delivery to Sweden; another foreign retailer may not. Currency display alone does not establish delivery eligibility. | Confirm delivery to the specified destination and compare totals in one currency. |
| Taxes and later fees | An overseas sticker price can omit charges that appear at checkout or after purchase. Bjorn previously encountered import-related fees/VAT when buying PC parts from the US. | Compare full payable cost when known, and expose material uncertainty when it is not known. |
| Extreme delay without a deadline | The cheapest offer takes over a month, while another arrives in days. | Alert the user and show a reasonably fast alternative even if no explicit date was given; distinguish advice from purchase authorization. |

These are broader than deliberate dark patterns. Ordinary catalog mismatches,
stale information, confusing defaults and honest trade-offs can cause equally
bad purchases. Tasks should distinguish those mechanisms rather than label every
price discrepancy deceptive.

## Regional size representation — added 2026-09-25

Proposed hindrance: the request names one size system, but a retailer presents
another (for example EU versus US). Preserve the canonical sellable variant while
varying its public labels and the available size-guide navigation. A conversion
must be scoped to the relevant product/family, brand and audience; do not use one
universal arithmetic rule or confuse US men's and women's labels. An authored
mapping is development data until its applicability is established. Unknown or
ambiguous equivalence must remain unknown, not silently become a nearby size.

Keep three factors separate: **label system**, **which variants are offered**, and
**whether that offer ships to the user's destination**. Converting the label does
not authorize changing delivery country or make a region-restricted offer eligible.
Grade canonical variant and delivery eligibility as outcomes. Finding/reading a
size guide is a separate diagnostic, not a required procedure when the answer is
already grounded. This is recorded for later generation; no conversion mechanism
was implemented in the retail-page AX inspection.

## Intent and authorization

Keep three layers distinct:

1. **Hard constraints:** exact item/variant/quantity, maximum payable total,
   explicit deadline, forbidden extras, and a delivery method stated as mandatory.
2. **Preferences:** home delivery preferred, lower cost preferred, faster arrival
   desirable. A preference is not automatically a veto unless the supplied user
   profile or current instruction says so.
3. **Advisory expectations:** disclose a material delay, unresolved fee or other
   trade-off and present a useful alternative. This does not authorize buying
   the more expensive option, changing size, or adding another product.

For a user who says only “find the cheapest,” reporting the cheapest offer plus
a clearly priced faster alternative is a useful result. For an immediate
purchase request with a surprising month-long delay, define in the task whether
the agent should seek a decision or proceed with disclosure. Do not hide this
policy in the grader or assume an unspecified universal delivery threshold.
Include paired cases where slower delivery or a qualifying second item is
explicitly authorized, so rejecting every special offer is not a winning policy.

Remembered preferences must actually be provided through supported memory/context
and carry provenance; a grader cannot expect the model to know an unseen user.

## Proposed combinations

Use several interacting factors per difficult task, with different combinations
and different winning retailers. The examples below are authoring seeds, not
fixed numerical contracts or new runnable task IDs.

| Journey | Combined challenge | Intended result |
|---|---|---|
| Exact shoe, lowest delivered price | Requested size/color; cheaper listing for another size; stale campaign; mixed shipping inclusion. | Buy exactly one eligible variant at the lowest current delivered total. |
| Shoe needed before a trip | Same shoe at multiple stores; slow default delivery; paid express; explicit arrival deadline. | Select the cheapest eligible **offer and shipping method**, even when neither has the lowest individual price. |
| Apparent promotional winner | Best headline price requires another item; a normal-price alternative is cheaper than the full promotional basket. | Preserve the one-item instruction; do not silently qualify for the deal. |
| Cross-border comparison | Domestic SEK, Dutch EUR/SEK options, destination restrictions, conversion charges and delivery preferences. | Compare eligible totals on a consistent currency basis and preserve the selected payment/delivery choice. |
| Overseas PC component | Exact component revision/capacity; attractive sticker price; explicit simulated taxes/import/handling fees; slow shipping. | Include all known charges, or report an unresolved total instead of inventing certainty. |
| Cheapest but impractically slow | Correct shoe, no explicit deadline, a month-plus cheapest offer and a slightly dearer offer arriving in days. | Explain the cheapest option’s delay and give the faster alternative; purchase behavior follows the declared authorization policy. |

Include compare-only, recommend/ask, and authorized-purchase variants. Include
no-feasible-offer cases: reporting that no offer meets the constraints is a valid
outcome when supported by the fixture. The agent must not “solve” them by relaxing
the size, price, delivery or quantity requirement.

## Building reliable, difficult tasks later

Use original fictional products and deterministic fixture rules. Real tax law,
exchange rates and shipping promises must not become moving grading targets.
This brief is not guidance about actual import charges or current retailer terms.

For each candidate, the eventual implementation should expose to the browser the
facts needed to resolve it: variant identifiers, stock, destination eligibility,
price currency, discount eligibility, shipping choices, arrival information,
known fees and the scope of any quoted total. Keep the grader’s expected answer
and eligibility calculations private. Different pages can reveal different
pieces; there should be no hidden requirement with no discoverable evidence.

Represent money in minor units with explicit currency and rounding rules. Pin
conversion rates and any conversion fee; identify whether the retailer’s SEK
checkout or a EUR payment option is actually selected. A displayed converted
estimate is not necessarily the final amount charged. Every mandatory charge
must be counted once, including charges payable later where the task includes
them in its budget. Avoid a universal tax formula: fixture-defined taxable bases,
included-tax flags and fee rules can differ by offer.

Pin a simulated date/time, destination/postcode, delivery calendar and cutoff
rules. Specify whether “before Friday” requires the latest promised arrival to
precede Friday, how date ranges are treated, and what to do with unknown dates.
Reproducible uncertainty is useful; an unknown shipping charge must not become
zero in the comparison oracle.

The comparison set is the set of eligible variant/retailer/shipping/payment
combinations. Account for stock, destination, promotion conditions and user
authorization before minimizing total cost. Define ties and permitted alternatives
so an equally good offer is not incorrectly rejected. If prices or availability
change during the journey, define the change schedule and the decision point
against which the result is judged.

Start with individually verified mechanisms, then compose them into harder
journeys. Vary which constraint changes the winner and which details are harmless
distractions. Add counterfactual pairs where one changed instruction or delivery
deadline makes another offer correct. Split by task template and site/retailer
layout as well as instance to reduce shortcut learning. Reuse verification of
shared pricing/checkout rules rather than hand-writing a grader for every SKU.

## Outcomes, procedure and failure analysis

Follow the existing [task-definition format](task-definitions.md): give each
outcome requirement a separate result. Examples include exact committed variant,
quantity, eligible destination, selected delivery mode/deadline, correct cost
comparison, budget, and absence of unauthorized purchases/subscriptions. Evaluate
irreversible side effects across the run, not only the final cart.

For recommendation tasks, truthful quoted totals, material-delay disclosure and
the requested alternative are **answer outcomes**. They may be graded even
without a purchase. Whether the agent visited a shipping information page is
an optional **procedure observation**, not a success requirement. Record useful
diagnostics such as:

- Variant/price/shipping terms delivered to the policy before checkout.
- Retailers and shipping options inspected, and the comparison’s evidence sources.
- Variant or currency changes between result, product, cart and committed order.
- Promotion eligibility information delivered before the choice.
- Checkout reinspection after an item, shipping method or destination change.
- Whether the agent reported uncertainty, offered an alternative or asked a question.

“Page loaded,” “text delivered,” and “model understood it” are different claims.
Only record what the trace supports; use null for unknowns. Procedure diagnostics
help investigate a lucky success without making one prescribed browsing path
mandatory. Group traces by mechanisms such as variant mismatch, stale quote,
conditional promotion, delivery mismatch and incomplete currency/fee comparison;
do not infer causal failure solely from the final wrong purchase.

## Additional candidate pitfalls

These are suggestions beyond the reported experience:

- **Sizing systems:** EU/UK/US, adult/child or width variants; a conversion chart
  may be needed. Never assume matching size numbers imply matching sizes.
- **Availability:** a low price is for out-of-stock, preorder, refurbished or
  marketplace stock; delivery dates can depend on the exact variant.
- **Promotion eligibility:** membership/subscription, first-customer codes,
  cashback rather than immediate discount, incompatible coupons, or a free-shipping
  threshold that tempts the agent to add an unauthorized item.
- **Price units:** per item versus pair, multipack versus single, installment
  amount versus full price, and deposit versus final amount due.
- **Destination changes:** entering the postcode changes shipping, tax or available
  delivery methods; selecting express or pickup resets another checkout choice.
- **Return terms and seller identity:** a low-price marketplace seller has different
  return costs or exclusions. Grade these only when the user/task makes them
  relevant, rather than inventing a preference for the agent.

Before implementing, settle the implicit-delay advisory policy, the supported
memory representation, and which unknown costs require clarification rather than
purchase. Existing dataset coverage of these combinations has **not** been audited
for this brief. No implementation or new model evaluation is requested here.
