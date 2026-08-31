# Research Heuristics

This file documents retrieval and alignment policies that are intentionally
heuristic. Change them only with a before/after validation run.

## Source Corpus

Remote `archeology` contains Chinese archaeology, museology, cultural relic,
ceramic technology, metal technology, archaeometry, architecture, and cultural
history material. `domain-stream/list` is not a complete search-scope inventory;
inspect `resolved_stream_ids` from `/search/query` for a specific retrieval.

## Concept Search

`concept/search` is substring search. Use the server cap, currently `limit=200`,
before concluding that an exact concept is absent. Lower limits can miss exact
matches buried under partial matches.

Do not cache negative concept-resolution results. A timeout, backend empty
response, or overly narrow search is indistinguishable from a real miss at this
layer. Positive cache entries are safe because statement idempotency does not
depend on the xref cache.

## Same Name Does Not Mean Same Sense

Remote concepts are not fully disambiguated. Same-name concept clusters can mix
valid and invalid senses. Govern these cases through `alignment_review.json`,
not one-off branches in code.

Known homograph pattern: short labels such as `金`, `石`, `唐`, `宋`, and `元`
can refer to dynasties, places, units, or other meanings rather than materials or
periods. Prefer reviewed longer labels when available.

## Wiki And RAG Noise

`wiki/search` is substring search, not semantic search. Single-character probes
create noise and should be filtered before retrieval.

RAG can rank PDF table-of-contents chunks highly. A chunk filtered by
`wwybsj_research.is_noise()` must not be cited as evidence. A surviving hit is
only a candidate; L2/L3 gates still need to confirm that the text supports the
claim.

## Coverage Ratings

Coverage ratings are evidence-quality signals, not truth labels:

- `strong`: enough relevant evidence to support research claims
- `partial`: use weaker, carefully scoped claims
- `thin`: avoid research claims; report limited coverage
- `none`: write only registry facts and evidence gaps

Never report "retrieved" as "confirmed". Provenance exists only when the cited
text supports the statement.

## Traditional/Simplified Matching

Some remote architecture text uses traditional characters while the registry is
simplified. The shared code folds traditional to simplified before topicality
matching using `scripts/t2s_chars.json`.

The conversion is one-way only. Do not convert simplified to traditional; that
direction is ambiguous.

Character folding does not solve domain synonymy. Terms such as `绿釉` and
`綠琉璃`, or `柱础护圈` and `覆盆柱础`, require curated probes or reviewed
synonym resources.

## Timeouts

Remote search and fact endpoints can return HTTP 200 with an empty result after
a backend deadline. Treat slow empty responses flagged as suspect timeouts as
unknown, not as evidence absence. Rerun before writing coverage conclusions.

Useful knobs:

| Env | Default | Purpose |
|---|---|---|
| `WWYBSJ_DEBUG` | off | print every HTTP call timing |
| `WWYBSJ_SLOW_SECS` | `3` | slow-call threshold |
| `WWYBSJ_HTTP_TIMEOUT` | `25` | HTTP timeout; increase for remote search |

Progress and timing logs go to stderr; normal data output goes to stdout.
