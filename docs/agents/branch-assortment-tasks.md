# Widest physical-store assortment

`query='widest_assortment'` adds a footwear task asking which individual branch has
the widest selection meeting the user's requirements, for an in-person try-on visit.
The task is sampled before stock/prices; existing branch-stock disclosures and
travel pages supply evidence. No renderer changes or model runs are required.

```python
from environments.product_world.scenario import generate_scenario
scenario = generate_scenario(
    task_options={
        'seed': 0, 'family': 'footwear', 'query': 'widest_assortment',
        'destination_city': 'malmo', 'price_range_sek': [1000, 2000],
        'requirements': 3, 'memory': 'mixed', 'hidden': 'none',
    },
    world_options={'seed': 42, 'footwear_depth': {}},
    location_options={},
)
```

The explicit query currently supports footwear categories. Named-model targets,
other families, and `budget_sek` are rejected; use the two-ended `price_range_sek`
(default1000–2000). With a geographic destination, footwear/random-family random
query sampling can also choose this task. Existing task priors are not outcome quotas.

## Counting and price contract

Count distinct model IDs separately at each physical branch. A model counts when
at least one SKU matches all product requirements, has positive saleable stock at
that branch and is available for inspection there. Extra colours, widths, sizes,
stock units and duplicate offers do not increase the model count. Branches of the
same retailer are not combined. The user's size remains a fit requirement.

Warehouse inventory, future transfers and display-only units do not count. A branch
can qualify even if it does not offer online pickup: the visit uses inspection and
actual local stock, not the click-and-collect capability. Existing inspection tasks
still allow display-only units; this task deliberately asks for stocked assortment.

Price bounds are inclusive and apply to the listed item price per pair. The current
world does not model separate till prices; this convention is disclosed in task
context. Online coupons, shipping, collection fees and travel costs do not change
this task's price eligibility. It is a branch-selection task, not an instruction to
buy the entire assortment or choose one cheapest pair.

Purpose (activity or an implying shoe type), size and other attributes can be in
the request or existing hybrid memories. A missing purpose is sampled coherently
from the intent vocabulary, without reading the world. Travel limits/mode and
retailer exclusions use their existing contracts. Size may be withheld using the
existing personal-fit clarification contract; never withhold ordinary optional
preferences as mandatory questions. Frozen manual examples keep size visible.

## Reference and manual review

`outcomes.evaluate(scenario)` and `Episode.reference()` supply a private reference:
per-branch matching model IDs, qualifying exact-SKU candidate IDs, lower/upper
model-count bounds and all branches tied for the largest positive count. All-zero
populations return `no_match`. Unknown eligibility stays uncertain unless it is
only an alternative SKU of a model already known to qualify at that branch; such
an alternative cannot change the count. Incomplete population coverage stays unknown.

`Episode.policy_input()` requests the branch name/location, matching count and
useful retailer/product links, without requiring every SKU or a summed basket price.
References and source/stock internals never enter public task cards. Response grading
is intentionally deferred: `grade_answer` raises `NotImplementedError` for this query,
so existing cheapest-offer grading cannot accidentally accept or reject these answers.
Human reviewers use the reference and the actual response, including link usefulness.

Three fixed task draws (seeds0,1,2) are bound to the unchanged account-world v11 at
`.local/coordination/branch-assortment/examples-v1/`; all returned no-match and were
retained without seed search. The existing world lacks some requested colours and
combinations. These examples demonstrate valid shortages, not a successful broad
assortment. Positive model counts, tied branches, price endpoints, duplicate variants,
wrong size, local stock and uncertainty have independent controlled tests in
`environments/product_world/test_assortment.py`. No browser-agent result is claimed.

Public cards are under that example directory's `public/`; private task/reference
files are outside it. Preserve that serving boundary. No previous card or world was
replaced. Ownership and reproduction scripts are in `.local/coordination/branch-assortment/`.
