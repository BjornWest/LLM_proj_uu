# Pricing and accounting

The bundled `prices-2026-09-21.json` is a pinned USD-per-million Standard API
price snapshot verified against https://developers.openai.com/api/docs/pricing
and the individual Astra/Sol/Terra/Luna model pages on 2026-09-21. It includes exact
Astra, Sol, Terra and Luna model IDs. No model suffixes or aliases are guessed.
Reports identify the catalog and its fingerprint. A snapshot's date does not
claim the rates were historically applicable to every recorded request.

For each request:

```
ordinary_input = input_tokens - cached_input_tokens - cache_write_input_tokens
base_cost = (ordinary_input * input_rate
           + cached_input_tokens * cached_rate
           + cache_write_input_tokens * write_rate
           + output_tokens * output_rate) / 1_000_000
```

This schema treats cache reads and writes as disjoint subsets of total input.
Do not subtract writes twice or charge them again as ordinary input. Reasoning
is a subset of output. Missing counters are unknown, not implicit zero. Invalid
or contradictory counters make the request unpriceable. Decimal arithmetic
avoids repeated floating-point rounding during aggregation.

Long-context multipliers apply to the whole request when total input is strictly
above the catalog's threshold. Input multipliers apply to ordinary, cached and
cache-write input. The output multiplier applies to all output. The tier
multiplier then applies to the complete request. The current snapshot uses
272,000 tokens, 2x input and 1.5x output; Standard 1x, Fast 2x, Batch/Flex 0.5x.
Tier selection is an estimate scenario; it is not inferred from a CLI speed label.
No tool fees, regional surcharges or subscription discounts are included.

## Add or update a saved price

Use official OpenAI documentation to verify rates when a model is missing or the
user requests current prices. Read the OpenAI Docs skill when available. Do not
use a similar model's price as an automatic fallback. Preserve the old snapshot;
create a new dated catalog and select it using `--prices PATH`. Include source
URL, date, exact model names, input/cache-read/cache-write/output rates, explicit
long-context threshold/multipliers and supported tier multipliers. Numeric rates
are nonnegative decimal strings. The parser must reject malformed catalogs.

Unknown model/price or missing token splits produce an incomplete result with a
known priced subtotal and a null complete dollar total. That is useful evidence;
it is not a reason to invent prices. A fully supported thread with no activity
inside the selected window may have a zero total; a cumulative-only legacy log
cannot establish zero cost from lack of per-request records.

For attribution, report response-completion timestamps as the accounting
boundary. A request spanning the boundary belongs to the interval containing its
usage-record timestamp, not proportionally to each interval. Local-only logs
cannot prove absence of activity on another machine.
