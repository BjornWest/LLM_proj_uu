# Page-variation expectations for procedural storefronts

Proposed authoring/review rubric, 2026-09-22. This is a design standard, not a validated metric of agent difficulty or an implemented generator. It applies to [the procedural storefront plan](procedural-commerce-design.md).

First local within-family implementation: [department-market matched AX
comparison](agents/procedural-commerce-within-design.md), 2026-09-23. This supplies
one baseline/contrast pair with real browser captures, not full rubric coverage.

## Revision: agent-visible AX is the acceptance surface

**2026-09-22 user correction:** the first MVP retailers are variants of one legacy catalog family, not three accepted base designs. Their HTML histogram differences and class names were insufficient evidence. Preserve that implementation as a tunable family; do not use its earlier classification as precedent.

The browser derives an accessibility tree from HTML, accessible names and rendered state. It is not a copy of every DOM node: neutral wrappers can disappear; decorative images can be absent; hidden disclosure content can be excluded. Our harness then formats/filters the tree again. Therefore **the tree and text actually available to the policy are the primary design-review artifacts**. See [MDN's accessibility-tree explanation](https://developer.mozilla.org/en-US/docs/Glossary/Accessibility_tree).

Different classes, padding, colors or anonymous wrappers earn **zero diversity credit**. Visual sidebar placement alone also earns no credit if it leaves the same AX ordering and grouping. A sidebar should change the accessible navigation organization, nesting, relation to results and/or discovery actions. Functional CSS still matters for visibility and interactions.

A new base design must identify at least three independently explainable AX/interaction differences from its nearest existing family, across landing, results and product pages. At least one must change discovery or interaction; renaming headings alone is insufficient. Examples:

- utility navbar plus a nested category navigation region versus one short navbar versus sidebar-only navigation;
- result table with associated headers/cells versus a list of separately named product articles;
- short canonical title versus a longer title composed from actual product attributes;
- one or two nondecorative images with useful, factual alt descriptions, with gallery grouping and surrounding information in different reading orders;
- description inline below other sections versus behind a closed disclosure versus reachable on a separate details route;
- purchase options in a named complementary region versus within a product article/fieldset;
- shipping/returns facts in footer content versus beside purchase controls, with the same facts still reachable.

These are not arbitrary obstacles. Every advertised control must work, and equivalent commercial actions must retain their meaning. A description requiring navigation is an explicit discoverability variation; record it independently of changing or withholding the underlying fact. Never hide the oracle answer in alt text or ARIA labels. Product images in the current synthetic prototype are schematic illustrations, not evidence of realistic visual grounding.

For acceptance, fix world, product, retailer identity and task, then vary only design/configuration. Save actual BrowserGym AX, the harness observation text and a before/after state when information requires an interaction. Compare roles, accessible names, nesting, ordering, expanded/checked states and reachable controls. Ignore volatile BIDs and origins when matching, but retain raw originals. HTML-only distances may be supplementary; a differing hash is not proof of useful diversity. Report similarities and unsupported variation axes explicitly.

## Equal variation ambition, unequal numbers of base designs

Common retailer types may receive more base designs. Within a base design, aim for comparable **meaningful structural variation per page role**, including boutique stores. Do not multiply common-store representation again by giving each common design a disproportionately richer variation system or sampling it more often merely because it has more combinations.

Sample retailer type, base architecture and site configuration in separate stages. Adding a new configuration option should not automatically increase that base architecture's probability. Practical limitations are legitimate but should be recorded; simplicity is not an instruction to manufacture complex navigation in a boutique.

The goal is a recognizable design family whose generated instances require the agent to locate and operate controls using current page content, rather than memorized positions or hierarchy. Purely cosmetic identity changes and arbitrary DOM noise do not establish that.

## Four dimensions for comparing two instances

Compare the same page role with the same world facts and behavior/disclosure contract. Vary only presentation parameters. Score the observed rendered DOM/accessibility and supported interaction, not the amount of source code changed.

| Dimension | 0: unchanged/irrelevant | 1: local meaningful change | 2: substantial change within the base design |
| --- | --- | --- | --- |
| **Semantic grouping and hierarchy** | New IDs/classes, neutral wrappers, colour changes | One useful region or information group reorganized | Major information/control groups have a different semantic organization or nesting |
| **Information order and association** | Same reading order; only product names differ | One meaningful section changes order or grouping | Several major sections reorganized, or equivalent facts represented as a grouped table versus a structured detail list |
| **Navigation and discovery** | Same links and entry points in the same arrangement | Different prominence/grouping of valid destinations | Flat versus expandable category groups, or a materially different in-page route to the same available region, within the design's supported vocabulary |
| **Control/interaction structure** | Same controls; only text/IDs change | One control grouping or optional expansion changes | Dropdown versus grouped option buttons, explicit filter Apply versus supported immediate application, or another distinct control/state arrangement preserving the same commercial operation |

These are ordinal reviewer judgments, not physical distances. An observed change may affect several dimensions, but do not meet a diversity target by describing one trivial modification several ways. Record independent variation choices and concrete evidence of their effects.

“Grid versus list” earns no structural credit if it is only CSS and exposes the same DOM/AX structure and controls. Different public labels can still be useful for robustness, but wording variation alone is insufficient. Random meaningless nesting, broken label associations, missing controls and gratuitous duplicate buttons are defects, not diversity.

## Initial acceptance target

For each supported page role:

- Provide at least **two independently configurable meaningful structural choices**. More options are welcome when cheap and coherent; raw combination count is not the target.
- Show a baseline and two deliberately different representative configurations. Each alternative should differ from the baseline on at least **two dimensions**, including one substantial (2) difference: approximately **3/8 or more** on the rubric. The two alternatives must not simply be the same example with different values.
- Keep the site's architectural identity and navigation conventions coherent. Maximum difference is not the objective, and not every random pair must pass this contrast threshold; near-neighbor instances and recognizable shared engines are useful too.
- If a minimal page has only one sensible structural axis, document the limitation and its supported meaningful variation. Do not pad the DOM or invent a convoluted flow to achieve a numeric score. Do not compensate by polishing CSS.

This is an initial review convention to make expectations discussable. Adjust it once actual generated pages and agent behavior show where it is too weak or unnecessarily expensive. It is not a reward, a training difficulty score or evidence of real-web coverage.

Sampling should exercise the supported structural choices at useful frequencies, independently of whether an offer wins. Three handpicked showcase variants do not prove that ordinary seeds vary. Later, cheap descriptor counts can detect unused knobs or a distribution dominated by one configuration; occasional rendered comparisons check that the knobs have real effects. No exhaustive Cartesian browser sweep is required.

## Examples by required page role

| Page role | First meaningful choice | Second meaningful choice | What stays invariant |
| --- | --- | --- | --- |
| Landing | Flat category navigation versus nested/expandable groups | Search/category/promotional regions ordered and grouped differently | Valid destinations, coherent store identity, available navigation/search capabilities |
| Search results | Compact results with grouped details versus richer independently grouped result summaries | Supported filter control/apply arrangement or sorting placement/grouping | Same query semantics, result facts, selected filters and reachable result population |
| Product detail | Specification table versus labeled information sections | Variant dropdown versus button/radio group; reorganized price/configuration/detail regions | Canonical selection, price/stock rules, required facts and allowed actions |
| Cart/checkout, where supported | Quantity/extras grouped per line versus a coherent separate configuration area | Alternative supported review/control arrangement | Quantities, quotes, required confirmations, authorization-relevant effects and receipt correctness |

A boutique can vary a simple flat versus grouped category menu and how its small set of main sections is arranged; it does not need a department-store mega-menu. A product page with no meaningful variants must use other genuine variation points rather than inventing a size selector.

Not every example fits every base architecture. Design owners select compatible choices and can propose equivalent alternatives. The shared contract does not impose these exact DOM implementations.

## Boundaries with behavior and hindrance generation

Presentation variation may alter where controls are found or how equivalent interactions are performed. It must not silently alter the underlying commercial state, eligibility rules, facts, consent choices or required disclosure preconditions.

For example, after a valid destination is supplied, a shipping quote may appear in an expanded region or dialog. Changing the rule from “destination required” to “all destinations' charges sent immediately” is a behavior/disclosure change and must be separately configured. A visual relocation does not authorize leaking previously private values into page payloads.

Cookie/consent mechanisms deserve multiple renderer-owned realizations under their declared semantic contracts. A banner becoming a blocking modal changes interruption behavior as well as markup; record that as a mechanism-realization choice, not evidence that a pure layout comparison held everything else fixed. Test equivalent resulting consent state for actions with the same meaning.

Functional CSS for visibility, overlays, scrolling and hit targets remains necessary; decorative styling is low priority. A change that affects what the policy can observe or operate must be measured in its actual rendered state.

## Bounded review packet, reusable checks

A design author supplies:

1. A short list of variation knobs and valid combinations, including limitations.
2. Per page role, baseline plus two representative contrast configurations under a fixed world/behavior fixture; save their settings and compact DOM/AX evidence.
3. A short rubric assessment naming concrete changed groups/controls, not just a score.
4. Shared contract-check results establishing retained facts, accessible operations and state transitions. Reuse engine/renderer-family cases rather than writing a new task grader per configuration.

Freeze site-wide choices for the lifetime of a generated site. Landing, results and product views should share coherent conventions; revisiting a page must not resample it. Page-local variants may differ while obeying that shared site configuration.

Validate one representative consumer path and mechanism boundaries relevant to changed controls, with wider coverage only for new shared components or observed defects. Do not run paid model episodes merely to approve cosmetic or structural authoring changes. Later held-out-base and within-base evaluations establish whether this variation actually improves generalization.
