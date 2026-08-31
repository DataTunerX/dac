# Known Failures

This is a compact failure ledger. Keep entries when they prevent repeat data
corruption or false conclusions; avoid adding ordinary debugging notes.

## Wrong Domain

Remote research must use domain `archeology`. Other similarly named domains have
been empty, local-only, or unrelated to Chinese museum registry records.

Symptom: empty bindings, empty wiki, or high-scoring directory pages.

Check: compare `/search/query` `resolved_stream_ids` and actual hit text.

## Gateway/Database Split

The old pattern wrote through the gateway and read through direct Postgres. When
the gateway was repointed, scripts read one database and wrote another, making
the domain appear partially empty.

Current rule: no SQL and no `psql` in this skill. Add gateway reads to
`wwybsj_common.py` instead.

Check after gateway or database movement:

```bash
python3 wwybsj_verify.py --check q0
```

## Predicate Namespace Theft

Bare semantic entity ids such as `is_a` are global. Upserting them from this
domain can change the namespace metadata for predicates used by other domains.

Current rule: all local predicates use `wwybsj.predicate.*`.

## Silent Reference Loss On Rewrite

The gateway replaces qualifiers and references for a statement id. Rewriting a
statement without its full references removes its evidence chain.

Current rule: rewrite operations must submit the complete qualifier/reference
set, and validations must check provenance, not just statement existence.

## Search Limit False Negatives

`concept/search` is substring search. Exact concepts can be buried below low
limits, making real concepts appear absent.

Current rule: L1 uses the server cap before declaring absence and does not cache
negative results.

## Homographs

Same surface form can name unrelated things. Alignments for ambiguous surfaces
must be reviewed in `alignment_review.json`.

Current rule: use `reject_exact` or longer reviewed labels rather than trusting
same-name matches.

## Dimension Unit Guessing

The registry has structured length, width, and height columns but no unit source.
Free-text dimensions often omit units or contain corrupted values.

Current rule: L0 does not infer dimension units or parse `ww_chicun`. It stores
free text and emits data-quality flags.

## Orphan Rows After Extractor Or Key Changes

Changing `statement_key` shape or extractor names stops overwriting old rows.

Current rule: run Q7 and predicate validation after such changes. The gateway can
mark orphan statements deprecated by id, but physical deletion is outside this
skill.
