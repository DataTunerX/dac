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
- **The platform owns termination.** Step, turn, hop, and time limits are
  enforced by the runtime. Do not impose a private budget on yourself and do
  not stop because a run feels long. Keep retrieving while the question still
  has unfilled fields and you still have leads.
- Print digests by **selecting fields**, never by cutting the response string.
  `str(response)[:N]` is wrong: `wiki/page/evidence` returns
  `{'page': {...}, 'facts': [...]}` with the long `page` object first, so a
  positional cut silently discards every fact. Extract named fields, print
  `facts` before `page`, and print a count so an empty render stays
  distinguishable from an empty result.
- **The runtime trims command output at about 8000 characters, and the tail is
  what disappears.** A batched probe walking a long slug list loses its last
  targets silently: on 2026-09-04 a probe requested `Ac型罐` tenth in a list and
  its morphology was cut off, which was then reported as missing. So put the
  highest-value targets first, cap every printed field to a few hundred
  characters, print counts instead of bodies, and split a long slug list across
  turns rather than trusting one giant script.
- Memory may be unavailable and a run can start cold. Re-derive from the probe
  instead of assuming earlier context survived.

## How To Call TDB

Call HTTP endpoints directly unless MCP tools for this gateway are already
available. For fuller endpoint details, read
`references/gateway_api_doc.md`.

### Which Endpoints Can Be Trusted

Measured on this gateway on 2026-09-03. Every discovery endpoint under-reports.
Only `fact/get` is exact.

| endpoint | behaviour |
| --- | --- |
| `ontology/fact/get?fact_id=` | exact; the only endpoint that never lies |
| `ontology/fact/search` | `q` and `predicate` filter correctly, but the result set is **incomplete** |
| `ontology/fact/list` | returns a partial set; recently written facts are often absent, and `status=pending` is not a valid status so that filter degrades to no filter |
| `wiki/page/evidence` | matches facts by **page title** against fact end labels, so it systematically under-reports; `facts=0` never means "no facts exist" |
| `ontology/statement/list` | ignores every filter (`q`, `subject_concept_id`, `predicate`, `status`); only `limit`/`offset` work |

Consequences you must respect:

- **Never conclude absence from one endpoint's empty result.** Absence requires
  `fact/search` by label **and** by predicate, plus the page body, coming back
  empty together.
- **Never quote a count as a total.** "`fact/search` returned 18" means 18 were
  returned, not that 18 exist. Say "at least N", never "there are exactly N".
- Legacy rows carry `fact_id = 0`; they cannot be fetched by id and are not
  provenance-bearing. Do not treat them as strong evidence.
- **Search is eventually consistent.** A freshly written fact is fetchable by
  `fact/get` immediately but can be missing from `fact/search` for a while —
  observed directly: `predicate=has_property` returned 19 rows, then 20 a minute
  later, the new row being the one just written. So an empty search result may
  mean "not indexed yet", never "does not exist". When a run has just written or
  expects recent writes, re-query before concluding, and say so in the answer.

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
- **Reverse lookup by predicate** — the highest-yield query for "which object
  came from which unit" questions:
  `GET /v2/ontology/fact/search?predicate=excavated_at&limit=100`.
  This is how the type-to-excavation-unit bindings surface; guessing entity
  names one at a time does not find them.
- **Predicates carry two coexisting namings.** `excavated_at` and
  `tdb.relation.excavated_at` are *different result sets* (29 vs 50 rows when
  measured). The same split applies to `characterized_by`, `consists_of`,
  `has_property`, `located_at`, `has_feature`. Query **both** spellings for
  every predicate and merge, or you silently lose a third of the data.
- Relation candidates that were never promoted hold real extracted content with
  `tdb_evidence_id`; reach them with
  `GET /v2/ontology/relation-candidate/list` (supports `subject_label`)
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

### One Concept, Several Slugs

Measured on 2026-09-04. The same typological unit is usually split across
near-duplicate slugs, and the payload sits on only one of them. Opening the
wrong one returns a page that looks empty and a `facts=0`.

| slug | what it actually holds |
| --- | --- |
| `Aa型罐` / `Ab型罐` | hierarchy only (`consists_of A型罐`); no morphology |
| `Ac型罐` | morphology: 外折沿、折腹、假圈足 |
| `Aa型` / `Ab型` / `Ac型` | morphology, but `Also Known As Aa型碗` - the **bowl** |
| `酱釉碗A型` | morphology: 唇口、斜弧腹、矮圈足 (`Also Known As A型碗`) |
| `A型酱釉碗` | hierarchy only (`consists_of 酱釉碗`) |
| `A型碗` | a third node: 侈口、深弧腹、矮圈足, generic bowl, all glazes |

- Probe **both word orders** for every type name: `酱釉碗A型` *and* `A型酱釉碗`,
  `酱釉罐A型` *and* `A型罐`. These are different nodes holding different halves
  of the answer, not aliases.
- Probe the suffixed *and* bare forms: `Ac型罐` *and* `Ac型`. The vessel-class
  suffix marks the vessel-specific node; the bare form is often a different
  vessel class with different measurements.
- Read `Also Known As` before attributing morphology. `Aa型` carries bowl
  morphology while an accepted fact links it to `酱釉罐A型`; the alias, not the
  link, tells you which vessel those measurements describe.
- A body holding only `Consists Of` is not a concept without morphology.
  `B型酱釉碗` and `C型酱釉碗` have hierarchy-only bodies, while
  `ontology/concept/evidence` returns 敛口/深弧腹/饼足内凹 and
  直口/斜弧腹/圈足/口沿刮釉 for them. **Read the page body and the fact layer for
  every type**; each carries a different half.

## Wiki Probe

This is the **first retrieval move** for every question that names a typed,
coded, or labelled entity: type/subtype codes (`Bb型`, `Aa型`), artifact or
material names (`酱釉罐`, `青白釉瓶`), sites, kilns, periods, and methods.

The runtime allows **one `plan_cmd` per turn**. Do not emit one call per
anchor. Run the whole probe chain inside a single script.

Use the script below **as written**. Substitute `ANCHORS`; change nothing else.
Rewriting it from memory is how the fact lines get lost.

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
        ev = g('/wiki/page/evidence', domain=DOMAIN, slug=slug,
               fact_limit=60, evidence_limit=3)
        facts = ev.get('facts') or []
        print(f'  SLUG {slug} | {h.get("page_type")} | conf={h.get("confidence"):.2f}'
              f' | {h.get("authority_kind")} | facts={len(facts)}')
        for it in facts:
            f = it.get('fact') or {}
            src = (it.get('evidence') or [{}])[0]
            print(f'    FACT {f.get("src_concept_label")} -{f.get("predicate")}->'
                  f' {f.get("dst_concept_label")} | conf={f.get("confidence")}'
                  f' | {f.get("status")} | ev={it.get("evidence_count")}'
                  f' | stream={str(src.get("stream_id"))[-28:]}')
        if not facts:
            body = ((g('/wiki/page', domain=DOMAIN, slug=slug) or {})
                    .get('page') or {}).get('content') or ''
            for ln in [x for x in body.splitlines() if x.strip()][:12]:
                print('    BODY', ln.strip()[:160])

    # wiki/page/evidence under-reports; ask the fact layer directly too
    for f in (g('/ontology/fact/search', domain=DOMAIN, q=a, limit=60)
              .get('facts') or []):
        print(f'  FACTQ {f.get("src_concept_label")} -{f.get("predicate")}->'
              f' {f.get("dst_concept_label")} | {f.get("status")}'
              f' | id={f.get("fact_id")}')

# Reverse lookup: the only reliable way to surface object -> unit bindings.
# Both spellings are live and return DIFFERENT rows, so query each and merge.
PREDICATES = ['excavated_at', 'located_at', 'consists_of', 'has_property']
rows = {}
for pred in PREDICATES:
    for spelling in (pred, 'tdb.relation.' + pred):
        for f in (g('/ontology/fact/search', predicate=spelling, limit=100)
                  .get('facts') or []):
            rows[(f.get('src_concept_label'), spelling,
                  f.get('dst_concept_label'))] = f
print(f'\n### BY-PREDICATE  {len(rows)} rows')
for (sub, pred, obj), f in sorted(rows.items()):
    print(f'  {sub} -{pred.split(".")[-1]}-> {obj} | id={f.get("fact_id")}')
```

Read the digest before deciding anything. A `SLUG` line that exactly matches
the queried term is a **hit**, and its `FACT` lines are the answer material.

`facts=0` does not mean the page is empty. Many concept pages carry their
content in the page **body** while no relation was ever promoted to an accepted
fact — `A型罐`, `Ac型罐`, `Aa型罐`, `Ab型罐` are all like this, and their bodies
hold the very hierarchy and morphology variables a typology question asks for.
The script therefore falls back to `wiki/page` and prints `BODY` lines whenever
`facts=0`; read those with the same weight as `FACT` lines, and cite the page
rather than a statement id.

Self-check every probe: if a `SLUG` line reports `facts=N` with `N > 0` but no
`FACT` lines follow, the printing is broken, not the corpus. Fix the script and
re-run. Never report "no page evidence returned" on that basis.

Never call `finish` on a turn whose only retrieval was `wiki/search`. A hit
list obliges a drill-down, not a conclusion.
When `FACT` lines are sparse, still open the matching slug with `wiki/page` and
read the page body. Many compiled pages preserve useful type hierarchies,
aliases, and explanatory bullets that have not been promoted to accepted facts.

Escalate whenever a **field the question asks for is still unfilled** — not
only when the probe came back empty. A probe that found a type but not its
morphology variables, foot/base form, or excavation unit is an incomplete
probe. Climb this ladder for each unfilled field before writing
`Not established`:

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
| structured | `ontology/fact/*`, `wiki/*` | concepts, typed facts, provenance — **query `fact/search` directly; `wiki/page/evidence` under-reports** |
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
6. Expand using retrieved labels as new anchors. Keep expanding while a round
   still yields new slugs or new facts; stop when a round adds nothing, not
   when a counter runs out.
7. Reconcile structured facts against source text. Label anything plausible
   but unsupported as `Not established`.

## Evidence Discipline

- `facts=0` from `wiki/page/evidence` means that page's title matched no fact
  label. The concept may still carry facts (`fact/search`), unpromoted
  candidates (`relation-candidate/list`), or content in its page body. Check all
  three before saying anything is missing.
- Distinguish "this endpoint returned nothing" from "the corpus holds nothing".
  Only the second justifies `Not established`, and only after `fact/search` by
  label, `fact/search` by predicate (both spellings), the page body, and
  `relation-candidate/list` have all come back empty.
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
- The page body and the fact layer carry different halves of a type entry. A
  thin body does not license `Not established`, and neither does a thin fact
  list. Run `concept/search` then `concept/evidence` for every type name whose
  body held only hierarchy.
- Grade a fact by its `review_note`. `auto-promoted by pipeline
  promote_ontology_facts` is routine. `promoted from relation_candidate by
  manual backfill <date>` is a hand edit, and one has been observed to attach
  the wrong node: on 2026-09-03 `酱釉罐A型` was linked to the *bowl* subtypes
  `Aa型`/`Ab型` this way (`fact_id` 2300, 2301). When a backfilled fact
  contradicts a page body, report both readings and label which is which.
- `flags=['subject_untraceable']` on a page relation means the subject could not
  be traced to source text. Cite it as a weak ontology lead, never as the
  established hierarchy. `罐A型 consists_of Ⅰ式、Ⅱ式` carries this flag.
- A contradiction in the corpus is part of the answer, not an obstacle to it.
  `酱釉罐A型` says two subtypes divided by 底部形制 while `A型罐` says three
  divided by 颈部、腹部形制. Report the conflict with both fact ids; collapsing it
  to one reading destroys what the reader needs to judge the record.
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
- Report gaps against the **original question's scope**, not only the entities
  you happened to retrieve. If the question spans six vessel classes and you
  covered one, name the five you did not retrieve. A gap phrased as "field X is
  missing for the entity I found" invites another pass at the same entity; a
  gap phrased against full scope points at what is actually missing.
- Separate `not retrieved` from `not present`. Write `not present` only after
  the escalation ladder is exhausted, and say which layers you exhausted and
  why the field cannot be obtained.
- End every answer with a **Confirmed facts ledger**: one row per fact, as
  `slug | predicate | value | stream`. Structured rows, never prose. Mark it
  `reusable — preserve verbatim, do not summarize`. Callers aggregate answers
  by summarizing them, and a structured ledger survives that where prose does
  not.

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

- Concluding `Not established` from a single endpoint's empty result, when
  every discovery endpoint on this gateway under-reports.
- Reporting a returned count as a corpus total.
- Reading `facts=0` from `wiki/page/evidence` as "this concept has no facts".
- Querying one spelling of a predicate and missing the rows filed under the
  other.
- Hunting entity names one at a time for excavation units instead of reverse
  lookup by `predicate=excavated_at` / `located_at`.

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
- Opening `Aa型罐` (hierarchy only), reading `facts=0`, and reporting that
  subtype's morphology as missing while `Aa型` or the fact layer holds it.
- Probing one word order (`A型酱釉碗`) and missing the node that carries the
  content (`酱釉碗A型`).
- Attributing morphology from a node whose `Also Known As` names a different
  vessel class.
- Losing the tail of a batched probe to the 8000-character output trim, then
  reporting the dropped targets as `Not established`.
- Picking one side of a corpus contradiction instead of reporting both with
  their fact ids.
- Passing `domain: "paper"` before the gateway actually binds that domain.
- Trusting unscoped hits when `resolved_stream_ids` is empty.
- Treating a bibliography hit as evidence for an argument in the paper body.
- Answering from the first semantic hit without checking provenance.
- Flattening qualifiers or uncertainty into a universal claim.
- Treating search rank as confidence.
- Cutting a response object positionally (`str(resp)[:N]`) so `facts` falls
  off the end, then reporting that no evidence was returned.
- Rewriting the probe script from memory instead of using it as given.
- Treating a non-empty probe as licence to skip escalation while required
  fields are still unfilled.
- Stopping while leads remain because the run feels long; the platform, not
  the skill, decides when to stop.

## Quick Start

1. Check `GET http://10.124.48.91:8996/v2/search/domain-stream/list`.
2. Use `domain: "archeology"` unless the live binding list says otherwise.
3. Run the Wiki Probe on 2-4 short anchors from the question.
4. Open every matching slug with `wiki/page/evidence` and read its facts.
5. Also read `wiki/page` bodies for matching slugs; use `response.page.content`.
6. For type/table questions, enumerate `wiki/pages` to find sibling type pages.
7. For every type name, probe **both word orders** (`酱釉碗A型` / `A型酱釉碗`)
   and both the suffixed and bare forms (`Ac型罐` / `Ac型`).
8. Run `fact/search` by label **and** by predicate (both spellings) for every
   field the question asks for.
9. Run `concept/search` then `concept/evidence` for every type whose page body
   held only hierarchy - the morphology often lives only in the fact layer.
10. Escalate to `relation-candidate/list` for every field still unfilled,
    before writing `Not established`.
11. Use `search/query` for prose and lexical mode for exact strings.
12. Answer with numeric citations and explicit limits.
