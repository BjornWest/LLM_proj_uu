# Versioned website component ordering

Fresh native-footwear or unified-catalog recipes can explicitly select:

```json
{"realism": {"component_ordering": "canonical-v2"}}
```

This emits `website-component-priors-v2`. Factor/outcome names and module unit
domains are canonically ordered before normalization and seeded accumulation.
Reordering JSON object keys or unit-domain lists preserves both the composition
and its priors hash, including finite conditions and module-dependent variations.
The existing architecture weights, scoped random streams, upstream policies and
commerce semantics are retained. Both world compilers forward the mode and pin
its effective priors into presentation. A v2 component plan explicitly records
`component_priors_schema`; its existing transport schema is unchanged.

Omission or explicit `"legacy-v1"` preserves historical v1 draws. V1 domain order
is significant: retain its declared weight/domain order when replaying a saved
world. No existing recipe or pin is migrated. Canonical mode is an explicit
fresh recipe choice, not a whole-world SAT change or an evaluation promotion.

The direct sampler API also supports `load_priors(version=2)` followed by
`sample_components(..., priors=priors)`. `load_priors()` remains v1. V2 sampling
normalizes a private copy, preserving caller-owned priors. Conditions keep their
existing allowed-value semantics; v2 introduces no cross-role constraints.
