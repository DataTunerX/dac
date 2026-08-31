# Architecture

The `wwybsj` domain is a local ontology built from museum registry records. It
does not copy the remote archaeology corpus. It stores local facts and links to
remote identifiers so downstream work can resolve background knowledge on
demand.

## Layers

```text
L0 registry facts     observed     deterministic, no LLM, no remote research
L1 term alignment     inferred     controlled terms -> remote concept clusters
L2 research claims    attributed   remote-text-backed claims about artifacts
L3 exhibit prose      hypothesized generated prose stored as data
wiki projection       rendered     deterministic page from local statements
```

## Core Invariants

- Use prefixed identifiers. Bare names such as `is_a` and `related_to` are global
  semantic entities and can overwrite namespace ownership for other domains.
- Set `metadata_json.domain = "wwybsj"` on every local statement.
- Keep `created_by` stable and unique enough for orphan detection.
- Treat `statement_key` as the idempotency key. Changing its shape or extractor
  name creates orphan rows that will not be overwritten.
- When rewriting a statement, submit all qualifiers and references again. The
  gateway replaces them for that statement id.
- Store uncertainty as data: quality flags, evidence gaps, rejected alignments,
  truncated clusters, and coverage ratings must be queryable.

## Epistemic Modes

| Mode | Producer | Requirement |
|---|---|---|
| `observed` | registry only | registry field plus registry event reference |
| `inferred` | deterministic rule or reviewed alignment | rule and premise recorded |
| `attributed` | remote source text | `stream_id`, `event_id`, and `source_span` |
| `hypothesized` | explicit hypothesis or generated prose | excluded from normal inference unless requested |

Do not use workflow `status` to encode evidence type. Use qualifiers.

## L0 Notes

L0 preserves registry literals while producing typed values for reasoning.
Examples include `dated_to`, `has_mass`, `has_dimension`, and `has_quantity`.

`ww_chicun` is free text and is intentionally not parsed in L0. Many records omit
units or contain ambiguous/corrupt strings, so L0 stores it as
`has_dimension_note` and emits data-quality flags instead of guessing.

Period label normalization applies only to the anchorable `in_period` term. It
does not overwrite `dated_to.registry_literal` or parsed intervals. Rules live in
`period_normalization.json`.

## L1 Notes

L1 alignment is term-level, not artifact-level. A term such as
`wwybsj.term.category.陶器` can cover many artifacts and align once to the remote
concept cluster.

Use concept clusters rather than one arbitrary concept id because remote
`concept/search` contains unresolved same-name concepts with different fact sets.
`primary_concept_id` is a stable display handle, not a claim that one member is
the only correct concept.

Homographs and bad members are governed by `alignment_review.json`:

- `confirm_exact`: accept same-name alignment
- `reject_exact`: reject a same-name alignment on sense grounds
- `exclude_concept_ids`: remove individual bad members from an otherwise useful cluster
- `align` plus `relation`: SKOS-style broader, narrower, close, or exact mapping

## Predicate Contract

`predicate_contract.json` is the source of truth for predicate types, functional
constraints, evidence requirements, and validator expectations. Inspect it before
changing any layer semantics or adding a predicate.
