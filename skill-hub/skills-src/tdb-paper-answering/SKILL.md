---
name: tdb-paper-answering
description: Use when answering questions about academic papers grounded in the TDB gateway at 10.124.48.91:8996, especially when paper text, citations, ontology statements, provenance, and retrieval scope must be checked instead of relying on memory.
---

# TDB Paper Answering

Answer academic-paper questions with TDB as an evidence system, not a general
chat memory. Use the live gateway to retrieve paper text, wiki pages, ontology
concepts, statements, and provenance; then compose an answer shaped by the
question and bounded by the evidence.

## Deployment

- gateway: `http://10.124.48.91:8996`, all v2 routes under `/v2`
- active retrieval domain: **`archeology`**
- corpus character: academic papers currently exposed through streams such as
  `archeology.academic_papers.actaanthropologicasinica.*`
- MCP: if using `tdb-memory-server`, point it at this gateway with
  `TDB_GATEWAY_BASE_URL=http://10.124.48.91:8996`; otherwise call HTTP directly
- answer language: reply in the user's language; default to Chinese when the
  retrieved paper evidence is Chinese
- validation note: on 2026-09-02, `/v2/search/domain-stream/list` on this
  gateway returned active `archeology` bindings for academic-paper streams.

### Domain Guard

The skill name is `tdb-paper-answering`, but the current gateway binding uses
`domain: "archeology"`. Do **not** pass `domain: "paper"` unless the live
domain-stream list shows that `paper` has been bound.

A wrong domain does not necessarily error. `search/query` can return
`resolved_stream_ids: []` while still returning hits from an unscoped corpus.

Rule:

- empty `resolved_stream_ids` with non-empty `hits` means the domain is wrong or
  unbound; stop and report a binding mismatch
- non-empty `resolved_stream_ids` with zero `hits` means the scope is correct but
  the query found nothing; rephrase or expand
- confirm bindings with `GET /v2/search/domain-stream/list` whenever scope is
  uncertain

## How To Call TDB

Call HTTP endpoints directly unless MCP tools for this gateway are already
available. For fuller endpoint details, read
`references/gateway_api_doc.md`.

Discovery and search:

- `POST /v2/search/query`
  `{ "query": "...", "domain": "archeology", "mode": "hybrid", "limit": 30 }`
  returns source-text hits and `resolved_stream_ids`
- use `mode: "lexical"` to verify exact names, terms, dates, DOI strings,
  reference numbers, quoted phrases, section headings, and enumerated claims
- `POST /v2/qa/evidence-pack`
  `{ "question": "...", "domain": "archeology", "wiki_limit": 5, "evidence_limit": 3 }`
  is a discovery aid, not an answer engine

Wiki:

- `GET /v2/wiki/search?domain=archeology&q=...`
- `GET /v2/wiki/page?domain=archeology&slug=...`
- `GET /v2/wiki/pages?domain=archeology`
- `GET /v2/wiki/page/evidence?domain=archeology&slug=<slug>&fact_limit=20&evidence_limit=5`

Ontology and statements:

- `GET /v2/ontology/fact/search?domain=archeology&q=<short-term>&limit=20`
- `GET /v2/ontology/concept/evidence?concept_id=<id>&fact_limit=20&evidence_limit=5`
- when a hit exposes `statement_id`, prefer
  `GET /v2/ontology/statement/get?statement_id=<id>` plus
  `GET /v2/ontology/statement/provenance?statement_id=<id>&include_locators=true&evidence_limit=5`
- legacy provenance remains available at
  `GET /v2/ontology/fact/provenance?fact_id=<id>&evidence_limit=5`; for
  statement-first hits with `fact_id: 0`, pass both `fact_id=0` and
  `statement_id=<id>` if needed

## Retrieval Workflow

Scale effort to the question.

Fast factual lookup:

1. Search the distinctive title, author, site, method, object, period, or term.
2. Run a short `ontology/fact/search` for the same anchor.
3. Follow any `statement_id` to statement and provenance.
4. Answer from the first solid evidence, with citations and limits.

Full paper interpretation:

1. Split the question into concepts and falsifiable claims: paper identity,
   authors, publication venue, research problem, method, dataset/material,
   argument, evidence, conclusion, limitations, and cited comparanda.
2. Search the full question and each distinctive anchor independently.
3. Use `qa/evidence-pack` for quick recall, then drive promising hits to
   statement/provenance where possible.
4. Verify exact claims with lexical search: DOI, dates, names, quoted terms,
   table entries, numbered references, sample counts, and section headings.
5. Expand from retrieved evidence for up to two rounds. Use paper title,
   author names, cited works, methods, archaeological sites, artifact types,
   period names, and argument phrases as follow-up anchors.
6. Reconcile structured statements and source text. Label anything plausible
   but unsupported as `Not established`.

## Evidence Discipline

- Search hits are not evidence unless the returned text actually supports the
  claim.
- Relation evidence must be graded:
  - `usable`: directly states the answer-bearing relation
  - `weak fallback`: helps navigation but cannot carry the main claim
  - `mismatched`: wrong sense, wrong entity, or contradicted by source text
- Preserve qualifiers such as time, period, place, culture, sample, method,
  uncertainty, and scope.
- Do not read local corpus files unless the user explicitly authorizes leaving
  the gateway boundary.
- Skip chunks whose metadata or content indicates footnotes, citations,
  bibliography-only sections, table of contents, or page markers unless the
  question is specifically about references or document structure.
- Ranking is weak. Corroborate names, numbers, dates, and enumerated claims with
  a second pass, preferably lexical.

## Answer Rules

- Answer like a careful paper reviewer: distinguish the paper's claim, its
  evidence, the author's interpretation, your synthesis, and current TDB limits.
- For research-paper questions, surface method, data/material, argument,
  conclusion, and limitation when the evidence supports them.
- For comparative questions, attribute each claim to its paper or stream and
  state whether evidence converges or conflicts.
- For citation-network questions, separate bibliography mentions from claims in
  the body text.
- Do not infer beyond TDB evidence. When the corpus is thin, say what was
  retrieved and what remains unsupported.

## Citation Discipline

Use scientific-literature style numeric citations in user-facing answers.

- Cite answer-bearing claims inline as `[1]`, `[2]`, etc.
- Reuse a citation number for repeated use of the same evidence object.
- Prefer citations backed by statement provenance; source-text search hits are
  acceptable when they clearly state the claim.
- End with `References`: each entry should include a readable source note plus
  minimal trace IDs such as `stream_id`, `statement_id`, `event_id`, or
  `tdb_evidence_id` when returned.
- Do not invent citation metadata. If an endpoint returns text but no stable ID,
  say `id not returned`.

## Output Shape

Fast path:

1. Direct answer with inline citations.
2. Brief evidence note if needed.
3. `References`.

Full path:

1. Direct answer.
2. Systematic explanation.
3. Evidence chain: source hit / wiki / statement / provenance and evidence grade.
4. Debug block for broad, comparative, causal, or debugging questions:
   planned concepts, planned statements, wiki hits, ontology hits, search hits,
   resolved streams, answer basis, and `Not established` gaps.
5. Short summary.
6. `References`.

## Common Failure Modes

- Passing `domain: "paper"` before the gateway actually binds that domain.
- Trusting unscoped hits when `resolved_stream_ids` is empty.
- Treating a bibliography hit as evidence for an argument in the paper body.
- Answering from the first semantic hit without checking provenance.
- Flattening qualifiers or uncertainty into a universal claim.
- Treating search rank as confidence.
- Looping indefinitely instead of answering with labeled gaps after two
  expansion rounds.

## Quick Start

1. Check `GET http://10.124.48.91:8996/v2/search/domain-stream/list`.
2. Use `domain: "archeology"` unless the live binding list says otherwise.
3. Run `search/query` and confirm `resolved_stream_ids` is non-empty.
4. Search distinctive paper anchors, then follow `statement_id` to
   statement/provenance.
5. Verify exact claims with lexical search and answer with numeric citations.
