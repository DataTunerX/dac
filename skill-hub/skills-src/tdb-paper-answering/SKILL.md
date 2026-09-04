---
name: tdb-paper-answering
description: Use when answering questions about academic papers grounded in the TDB gateway at 10.124.48.91:8996, especially when paper text, citations, ontology statements, provenance, and retrieval scope must be checked instead of relying on memory.
  Probe the wiki and ontology layers before concluding anything is missing.
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

## Runtime Constraints

- **One `plan_cmd` per turn.** Extra calls in the same turn are blocked and
  wasted. Batch the whole retrieval chain into a single script.
- Budget: `LOCAL_SKILL_MAX_STEPS=30`, two turn loops, 300s per command. A
  well-batched probe answers most questions in three or four steps.
- Print digests, not raw JSON. Truncate long strings and drop fields you are
  not reading. A hit buried in a 15KB dump is a hit you will miss.
- Memory may be unavailable and a run can start cold. Re-derive from the probe
  instead of assuming earlier context survived.

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
- `wiki/page` returns the page under `page`; read `response["page"]["content"]`,
  not a top-level `content` field. An empty-looking page after `wiki/page`
  often means the client parsed the response shape incorrectly.

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
- `GET /v2/ontology/concept/search?q=<short-term>&limit=50` returns
  `{ concepts }` when a label exists but no wiki page was built
- `GET /v2/ontology/relation-candidate/list` returns `{ relation_candidates }`;
  filter on `subject_label` / `object_label` to reach raw extractions carrying
  `tdb_evidence_id` before any fact was promoted

## Wiki Probe

This is the **first retrieval move** for every question that names a typed,
coded, or labelled entity: type/subtype codes (`Bb型`, `Aa型`), artifact or
material names (`酱釉罐`, `青白釉瓶`), sites, kilns, periods, and methods.

The runtime allows **one `plan_cmd` per turn**. Do not emit one call per
anchor. Run the whole probe chain inside a single script, and print a compact
digest instead of raw JSON.

```python
import json, urllib.parse, urllib.request

B, DOMAIN = 'http://10.124.48.91:8996/v2', 'archeology'
ANCHORS = ['<anchor1>', '<anchor2>', '<anchor3>']   # short, 2-6 chars each

def g(path, **kw):
    url = B + path + '?' + urllib.parse.urlencode(kw)
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.loads(r.read())
    except Exception as e:
        return {'_err': str(e)[:120]}

seen = set()
for a in ANCHORS:
    hits = (g('/wiki/search', domain=DOMAIN, q=a, limit=8) or {}).get('results') or []
    print(f'\n### ANCHOR {a}  hits={len(hits)}')
    for h in hits:
        slug = h.get('slug')
        if not slug or slug in seen:
            continue
        seen.add(slug)
        print(f'  SLUG {slug} | {h.get("page_type")} | conf={h.get("confidence"):.2f}'
              f' | {h.get("authority_kind")}')
        ev = g('/wiki/page/evidence', domain=DOMAIN, slug=slug,
               fact_limit=60, evidence_limit=3)
        for it in (ev.get('facts') or []):
            f = it.get('fact') or {}
            src = (it.get('evidence') or [{}])[0]
            print(f'    FACT {f.get("src_concept_label")} -{f.get("predicate")}->'
                  f' {f.get("dst_concept_label")} | conf={f.get("confidence")}'
                  f' | {f.get("status")} | ev={it.get("evidence_count")}'
                  f' | stream={str(src.get("stream_id"))[-28:]}')
```

Read the digest before deciding anything. A `SLUG` line that exactly matches
the queried term is a **hit**, and its `FACT` lines are the answer material.
When `FACT` lines are sparse, still open the matching slug with `wiki/page` and
read the page body. Many compiled pages preserve useful type hierarchies,
aliases, and explanatory bullets that have not been promoted to accepted facts.

Escalate only when the probe is empty:

1. `GET /v2/ontology/concept/search?q=<short-term>&limit=50`, then
   `GET /v2/ontology/concept/evidence?concept_id=<id>&fact_limit=60`
2. `GET /v2/ontology/relation-candidate/list` filtered on `subject_label` /
   `object_label`; these carry `tdb_evidence_id` for raw extractions
3. only then conclude `Not established`

Anchor rules:

- Probe **short** anchors. `酱釉` and `罐` resolve; `闽江流域出土宋元酱釉瓷器`
  does not.
- Probe the bare code and the compound: `Bb型`, `Bb型酱釉罐`.
- When a Chinese term misses, probe the English form the OCR may hold
  (`brown glazed jar`), and the reverse.
- Probe the abstract's own category words; they name the material classes the
  paper actually uses.

## Retrieval Workflow

TDB holds three layers. A miss in one says nothing about the others:

| layer | endpoint | holds |
| --- | --- | --- |
| structured | `wiki/*`, `ontology/*` | concepts, typed facts, provenance |
| source text | `search/query` | chunked paper text and OCR output |
| candidates | `ontology/relation-candidate/list` | raw extractions with `tdb_evidence_id` |

Typed or coded entities - type and subtype codes, artifact classes, kilns,
sites, periods - live in the **structured** layer. Prose, argument, and
narrative live in the **source text** layer. Start where the answer lives.

Typology-heavy or table-heavy papers can be asymmetric: type labels and
classification notes may be well represented in compiled wiki page bodies while
source-text search returns only an abstract, bibliography, image placeholders,
or a small OCR fragment. Do not equate "few accepted facts" with "the paper did
not establish the typology." For these questions, use page bodies as evidence
after opening the relevant slugs, then label which details are page-body
evidence versus accepted fact/provenance.

Fast factual lookup:

1. Run the Wiki Probe on 2-4 short anchors.
2. If it returns facts, answer from them with provenance.
3. Use `search/query` only to quote or corroborate.

Full paper interpretation:

1. Split the question into concepts and falsifiable claims: paper identity,
   authors, venue, problem, method, material, argument, evidence, conclusion,
   limitations, and cited comparanda.
2. Run the Wiki Probe first. Harvest every matching slug and its facts.
3. Open the paper's `source_summary_*` page. It enumerates the classes and
   types the paper actually establishes, including sibling types you did not
   think to ask about.
4. For taxonomic / typological / table questions, also enumerate
   `wiki/pages` and filter page titles/slugs for the target material plus
   type-code terms (`型`, `亚型`, `式`, `Aa`, `Bb`, `Ⅰ式`, etc.). Open those
   pages with `wiki/page`; their bodies often contain the sibling hierarchy.
5. Then run `search/query` for prose, and `mode: "lexical"` for exact strings.
   If scoped search returns only an abstract or image placeholders, say so and
   rely on wiki page bodies plus accepted facts rather than declaring absence.
6. Expand for up to two rounds, using retrieved labels as new anchors.
7. Reconcile structured facts against source text. Label anything plausible
   but unsupported as `Not established`.

## Evidence Discipline

- A miss in one layer is not absence. `search/query` returning nothing means
  the phrase is absent from the chunked text - often because those pages are
  OCR image output - not that the knowledge is missing. Never write
  `Not established` until the Wiki Probe and the concept / relation-candidate
  escalation have both come back empty.
- For table or figure-driven source material, `search/query` may return only
  image placeholders such as `assets/page_*_image_*.jpeg`. Treat those as a
  retrieval limitation, not as negative evidence. Check compiled wiki pages and
  accepted facts before answering.
- A `wiki/search` hit list is a navigation result, not evidence. Open the slug
  with `wiki/page/evidence` before judging it.
- A `wiki/page` body can be evidence for compiled hierarchy/description when
  it directly contains the relevant bullets, but its evidence grade is weaker
  than statement provenance. Cite it as page-body evidence and avoid presenting
  it as statement-provenanced fact unless `wiki/page/evidence` returns a fact.
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

- Concluding `Not established` from `search/query` alone while the concept page
  exists with accepted facts.
- Concluding `Not established` from sparse accepted facts while the `wiki/page`
  body contains the type hierarchy or morphology.
- Reading `wiki/page` as if `content` were top-level; the content is nested
  under `page.content`.
- For typology questions, failing to enumerate `wiki/pages` for sibling type
  pages after finding one type such as `Bb型酱釉罐`.
- Stopping at a `wiki/search` hit list without opening the slug.
- Emitting several `plan_cmd` calls in one turn; only the first runs.
- Dumping raw JSON so large that the real hit is buried.
- Probing long descriptive phrases instead of short anchors.
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
3. Run the Wiki Probe on 2-4 short anchors from the question.
4. Open every matching slug with `wiki/page/evidence` and read its facts.
5. Also read `wiki/page` bodies for matching slugs; use `response.page.content`.
6. For type/table questions, enumerate `wiki/pages` to find sibling type pages.
7. Escalate to `concept/search` and `relation-candidate/list` before writing
   `Not established`.
8. Use `search/query` for prose and lexical mode for exact strings.
9. Answer with numeric citations and explicit limits.
