---
name: tdb-archeology-qa
description: Answer archaeology questions grounded in the TDB gateway at 10.124.48.91:8989 (domain "archeology"), combining wiki, ontology, statements/provenance, and search into an evidence-backed historical answer instead of a triple dump. Verified against the live gateway and docs/tdb_agent_user_guide.md.
---

# TDB Archaeology QA

Answer archaeology questions with TDB as an **evidence system**, not a trivia lookup.
Find reachable knowledge (wiki / ontology / search), walk provenance back to source
text, and use that evidence as a handle to discover more. Organize the final answer
around the question, and treat qualifiers as part of the claim.

## Deployment (validated 2026-07-27 against live gateway on 10.124.48.91 and docs/tdb_agent_user_guide.md)

- gateway: `http://10.124.48.91:8989`, all v2 routes under the `/v2` prefix
- domain: **`archeology`** (this is the only correct value — see the guard below)
- MCP: if using `tdb-memory-server`, point it at this gateway
  (`TDB_GATEWAY_BASE_URL=http://10.124.48.91:8989`); otherwise call the HTTP endpoints
- answer language: reply in the user's language; default to Chinese for archaeology
  content, since the corpus is Chinese-language material
- corpus grows as books are ingested (already well beyond the first book); do not
  hardcode counts or promise coverage. Check current scope live via `resolved_stream_ids`
  from a `search/query`, or `GET /v2/search/domain-stream/list`.

### How this corpus is loaded

New material reaches this gateway through DAC Data Management → **TDB 入库**
(`/tdb-pipeline`), which submits runs to the TDB pipeline controller with
`domain: "archeology"`. That target writes to this same gateway
(`http://10.124.48.91:8989`), so anything ingested there becomes answerable here —
usually within one pipeline run. The isolated `:8996` paper test database is a
different target and is **not** visible to this skill.

### Domain guard (critical)

The wiki/ontology **domain** is `archeology` (no second "a"). The **streams** are named
`archaeology.phase1.*` (with the second "a"); a gateway domain→stream binding bridges
the two, so you only ever pass `domain: "archeology"` and let the gateway resolve streams.

A wrong domain (e.g. `archeology_expert`, `archaeology`) does **not** error. `search/query`
returns `resolved_stream_ids: []` and then searches the **entire unscoped corpus**,
still returning hits — silently cross-corpus and wrong.

> Rule: `resolved_stream_ids` is about **scope**, not matches — do not confuse it with
> hit count. After the first `search/query`:
> - empty `resolved_stream_ids` **with** non-empty `hits` → wrong/unbound domain: the
>   search ran unscoped over the whole corpus. STOP and report a binding misconfiguration.
> - non-empty `resolved_stream_ids` but zero `hits` → scope is correct, the query just
>   found nothing; rephrase or expand — do **not** treat this as a misconfiguration.
> Sanity-check bindings with `GET /v2/search/domain-stream/list`.

## How to call TDB

Call the HTTP endpoints below directly (if TDB MCP tools are present they wrap these same
endpoints — but do not assume they exist; default to HTTP). For fuller endpoint details,
read `references/gateway_api_doc.md`, copied from `tdb/gateway/docs/api_doc.md`. **These are
evidence-gathering tools, not an answer engine** — the gateway does not decompose the
question or judge sufficiency for you. You (the agent) must: (1) understand what the
question asks, (2) pick anchors (concept / page / relation / passage), (3) call these
endpoints for local evidence, (4) decide to expand or stop. Note the HTTP verbs:
reads are **GET with query-string params**; only search and evidence-pack are POST.

Discovery / search:

- `POST /v2/search/query` `{ "query", "domain": "archeology", "mode": "hybrid", "limit": 30 }`
  → `hits` + `resolved_stream_ids` (raw source text). Override with
  `stream_id`/`stream_ids`/`stream_prefix` only for tighter manual debugging.
  Default `mode:"hybrid"`, but switch to **`mode:"lexical"` to find or verify exact terms
  and enumerated lists** (subfield names, proper nouns, dates) — vector similarity can bury
  an exact match under paraphrase, so confirm any enumerated/verbatim claim with a lexical pass.
- `POST /v2/qa/evidence-pack` `{ "question", "domain": "archeology", "wiki_limit": 5, "evidence_limit": 3 }`
  → `wiki_hits` / `concept_hits` / `fact_hits` in one call — a quick multi-layer discovery
  aid. It shows what TDB recalls from the question text; it does not do multi-hop QA, so use
  it to seed anchors, then drive to statements yourself.

Wiki (domain-scoped):

- `GET /v2/wiki/search?domain=archeology&q=...`, `GET /v2/wiki/page?domain=archeology&slug=...`,
  `GET /v2/wiki/pages?domain=archeology`
- `GET /v2/wiki/page/evidence?domain=archeology&slug=<slug>&fact_limit=20&evidence_limit=5`
  (needs `domain`+`slug`; never guess `page_id`) → facts around a page that landed in ontology.

Ontology + statements (semantic core):

- `GET /v2/ontology/fact/search?domain=archeology&q=<term>&limit=20` (discovery; responses
  carry `statement_id`). Use a **short `q=<term>`** — a single distinctive term retrieves
  best; a long sentence retrieves poorly. Also `/fact/get`, `/fact/list`.
- `GET /v2/ontology/concept/evidence?concept_id=<id>&fact_limit=20&evidence_limit=5`
  → accepted facts on both sides of a concept (works for projection concepts too). For a hit
  that already exposes `statement_id`, the statement path (`statement/get` +
  `statement/provenance`) is the more direct readback.
- Statement-first readback (preferred whenever `statement_id` is present):
  `GET /v2/ontology/statement/get?statement_id=<id>`
  and `GET /v2/ontology/statement/provenance?statement_id=<id>&include_locators=true&evidence_limit=5`.
- Legacy/compat provenance: `GET /v2/ontology/fact/provenance?fact_id=<id>&evidence_limit=5`;
  for statement-first hits with no legacy fact, pass `fact_id=0&statement_id=<id>`.
- Evidence→statement reverse lookup (ledger): `GET /v2/ledger/evidence/statements?evidence_id=<uuid>&include_locators=true&limit=20`
  — confirm a piece of evidence is actually attached to a statement.

Stable path for entity / relationship / "as-of" questions (more reliable than pure text
search — see `docs/tdb_agent_user_guide.md` §5.1): resolve the entity, then read its state:
`GET /v2/entity/list?q=<name>` → `GET /v2/state/edge/asof?src_id=<id>&predicate=<p>&as_of_valid_time=<ts>`
→ `GET /v2/entity/get?entity_id=<dst_id>`. Prefer this for person affiliation and typed
relationships when the corpus supports it.

### Execution contract

- **Auth:** none. The gateway is open on the trusted network — send requests with no
  credentials. (Any OpenClaw/agent front-door token is unrelated to the gateway.)
- **Pagination:** there is no cursor. `search/query` takes `limit` (default 30, **max 200**) —
  raise it to see more; that is the ceiling. Evidence endpoints cap with `fact_limit` /
  `evidence_limit`. Ask for a larger `limit`; do not wait for a `next` token.
- **Failures / retries:** endpoints are reliable, but transient `5xx`/timeouts can still
  happen (aggregation-heavy paths — `evidence-pack`, `fact/search`, `wiki/page/evidence` —
  most). On a `timeout` / `5xx` / `429`, retry ~2–3× with backoff; a transient error is
  **not** evidence of an empty corpus, and do not hammer a stuck backend. If `mode:"hybrid"`
  keeps timing out, fall back to `mode:"lexical"`.
- **Response shapes** (real fields, not invented):
  - `search/query` → `{ "resolved_stream_ids": [...], "hits": [ { "content", "stream_id",
    "lexical_score", "vector_score", "hybrid_score", "metadata" } ] }`. Read `content` for
    text; `resolved_stream_ids` for scope (see the guard).
  - `ontology/fact/search` → `{ "facts": [ { "predicate", "src_concept_label",
    "dst_concept_label", "qualifier", "statement_id", "fact_id", "status" } ] }`. A
    `fact_id: 0` with a real `statement_id` is the normal semantic-projection case.
  - `ontology/statement/get` → `{ "statement": {...}, "qualifiers": [...] }`;
    `ontology/statement/provenance` → `{ "references": [...] }` (the source evidence).
  - `qa/evidence-pack` → `{ "query_variants", "wiki_hits": [ { "matched_by", "page",
    "facts" } ], "concept_hits", "fact_hits" }`.
- **Content noise:** `hits[].content` carries layout markup — `<sup>…</sup>`,
  `<!-- page: N -->`, `<!-- tdb:block_type=… -->`, and table pipes. **Skip chunks whose
  `block_type` is `footnote` / `citation` / `toc` / `page_marker`** — they rank as hits (a
  bare citation can even be the top hit) but are not evidence. Strip these artifacts from
  anything you quote.
- **Ranking is weak — do not read hit score as confidence.** Hybrid scores are low and flat
  (~0.15–0.23) even for the best hit, so rank barely discriminates. Corroborate any exact
  claim (a number, name, date, or enumerated list) with a **second query — ideally a
  `mode:"lexical"` pass** — before asserting it.

## Workflow

Scale effort to the question:

- **Fast path** (single factual lookup, e.g. "X 的年代"): search the proper noun / key term
  (`search/query` + `ontology/fact/search?q=<term>`) → if a hit has `statement_id`, read
  `statement/get`(+`provenance`) → answer. One round is enough.
- **Full path** (broad / comparative / causal / "是谁/为什么/什么关系/什么意思"): run the
  full loop below, **2 expansion rounds by default** — a 3rd is allowed only when one
  specific, cheap anchor would close a named gap, then stop. Answer with labeled gaps
  rather than looping.

Full loop:

1. **Plan.** List the concrete concepts you will check, and the short falsifiable
   statements you need to validate (see *Concept split* / *Statement matching*).
2. **Discover (proper-noun-first).** Concurrently fire `search/query` on the question *and*
   on each distinctive proper noun as a standalone query, `ontology/fact/search?q=<short
   term>` on the key terms, and `qa/evidence-pack` for a quick multi-layer recall. The
   **statement layer is where the grounded knowledge lives, so always drive there**
   (`fact/search` → `statement/get`), whichever call first surfaces a `statement_id`.
3. **Deepen structured hits.** For each promising hit: if it exposes `statement_id`,
   switch to `statement/get` + `statement/provenance` (this is the primary grounding path);
   otherwise use `wiki/page/evidence` or `fact/provenance`. Capture qualifiers.
4. **Walk provenance to source text.** Pull the supporting sentence/paragraph behind each
   fact or statement you intend to use.
5. **Expand (≤2 rounds).** Treat recovered evidence as retrieval pivots (see *Iterative
   expansion*); harvest anchors and re-query wiki/ontology/search. Keep only what stays
   grounded in TDB evidence.
6. **Reconcile & answer.** Only after the layers have actually been attempted, compose a
   question-shaped answer. "Attempted" means you tried the layer; if a layer is thin,
   missing, or errors, say so in the debug block rather than skipping silently.

Do not jump from a broad `search/query` hit straight to the answer without attempting
concept split, evidence-pack/ontology, and provenance. Do not silently downgrade from
structured evidence to raw text — if you fall back, label it.

### Concept split

Before retrieving, list the concrete concepts implied by the question, question-shaped not
corpus-shaped. Split compound requests into operational concepts: object/institution;
action/process; people/roles; constraints, causes, stages, or significance. Use this list
to drive query planning and expansion.

**Pull out distinctive proper nouns** — person names (e.g. 金正耀), sites (妇好墓, 台家寺),
artifacts, mines, dynasties, named methods/terms — and search each as a **standalone anchor
early**, not just as part of a long question string. A proper-noun query is often the
highest-recall path to the exact passage, and corpus phrasing is sensitive: the on-point
chunk may miss a paraphrased query but surface on the bare name. Search the name before
concluding the topic is `Not established`.

### Statement matching

Before composing, list the short, falsifiable, answer-bearing statements you must validate
(e.g. `X 早于 Y`, `X 包含 A/B/C`, `X 不等于 Y`, `X 尚无证据`). Match each to an evidence
class (see *Evidence discipline*). If a statement cannot be matched, mark it
`Not established` — never upgrade it by intuition.

### Statement-first read discipline

- `ontology/fact/search|list|get` are discovery surfaces, valuable mainly when they expose
  `statement_id`. A `fact_id` of `0` on a semantic-projection hit is **not a miss** — it
  means the stable identity is the `statement_id`, not a legacy fact row.
- Once `statement_id` is present, make `statement/get` + `statement/provenance` the primary
  read path; treat the legacy fact row as a compatibility breadcrumb only. If you must use
  the legacy fact-provenance entry for such a hit, pass `fact_id=0&statement_id=<id>`.
- If a fact row and a statement read disagree, the statement API is authoritative.
- If statement read succeeds but legacy provenance is thin, do not downgrade the answer;
  continue with statement evidence + `search/query` source-text expansion.

### Iterative expansion

When round one is thin, do not stop and do not fall back to memory — mine what you already
retrieved for new anchors, then run one more targeted round (2 by default; a 3rd only to
chase one specific cheap anchor, then stop).

- Build anchors from the strongest hit: exact cause/contrast phrases and question-shaped
  noun phrases from source text; **proper nouns (names, sites, artifacts, mines)** as bare
  standalone queries; concept labels and relation targets from statements; qualifier terms
  (`time`/`period`/`place`/`culture`/`difference`/`role`).
- Prefer anchors from the evidence *text*, not bare normalized relation labels.
- Run short, narrow follow-ups (a short exact phrase; and a conceptized restatement split
  into `src`-like / `dst`-like / `cause`-like variants) — not one long re-query of the
  original question.
- If `search/query` is stronger than ontology in round one, promote its wording into
  ontology-retry anchors before concluding ontology is empty. Only after a real retry may
  the debug block say "no ontology statement after retry" (distinct from "ontology empty").
- If an expanded anchor yields `statement_id`, immediately read `statement/get` +
  `statement/provenance`.

### Qualifier discipline

- A fact without its qualifier may be an incomplete reading of the claim.
- Qualifiers (`time`, `period`, `place`, `culture`, `difference`, `scope`, `role`, …) can
  narrow validity or state a contrast — preserve them in the answer; do not generalize past
  them.
- Two statements with the same subject-predicate-object but different qualifiers are
  different historically situated claims, not duplicates.

## Evidence discipline

Keep these support classes separate, and never overstate:

- `Structured support`: directly from wiki or ontology fact/statement records
  (separate the `Statement core` = subject/predicate/object from its `Qualifier context`)
- `Relation-evidence support`: provenance/page-evidence attached to a structured hit.
  Grade each (only `usable` may anchor a main claim):
    - `usable` — the returned sentence/span **directly states** the relation and is
      relevant to the question.
    - `weak fallback` — provenance resolved but the text is generic, tangential, or only
      loosely related; may guide more search, cannot anchor a claim.
    - `mismatched` — the returned text does **not** support the relation (wrong sense,
      wrong entity, or contradicts it); treat it as a signal to drop that relation.
- `Evidence-expanded source-text support`: follow-up retrieval launched from that evidence
- `Source-text support`: a provenance sentence or search hit, even if not fully structured
- `Not established`: plausible but not currently supported well enough

Boundaries and honesty:

- Allowed by default: gateway-exposed wiki/ontology/search/statement APIs. Do **not** read
  local corpus files directly unless the user explicitly allows leaving the API boundary.
- A search semantic match is not evidence unless the returned text actually contains the
  claim. Retrieval success ≠ evidentiary success.
- But do not under-answer just because a claim is not yet a clean triple — when raw source
  text clearly says more, use it.
- Only organize the answer around a relation once it has a real `statement_id` or clearly
  provenance-bearing identifier; otherwise demote it to navigation support.

### Cross-book synthesis

The corpus spans multiple books (`overview_of_chinese_bronzes`, `archaeometry`,
`ancient_chinese_metal_technology`, …), and a good answer often draws on several. Handle
that explicitly:

- **Attribute each claim to its `book.chapter`** (the `stream_id` / statement provenance
  tells you which). Do not blur sources into one anonymous voice.
- **When books converge on a point, say so** — cross-book agreement is stronger evidence
  than a single hit.
- **When books disagree, surface the disagreement**; do not average or silently pick one.
  Present both and note which is better provenance-backed.
- **Prefer the more specialized book for a topic**: `archaeometry` for method/isotopes,
  `ancient_chinese_metal_technology` for mining/smelting, `overview_of_chinese_bronzes` for
  typology/finds. A specialized-book hit outranks a passing mention elsewhere.

## Answer rules

- Ontology is for path-finding, not for capping the answer; relation evidence is for
  expansion, not only validation.
- Completeness is part of correctness: if TDB supports a fuller explanation through nearby
  pages, facts, qualifiers, or expanded evidence, use it before answering.
- If the question is only intelligible through sequence or causation, make the sequence /
  cause-and-effect explicit — don't just list related concepts.
- If provenance returns more question-relevant detail than the bare fact, include it.
- Answer like a careful history professor: place people, sites, artifacts, and events in
  time, context, significance, and consequences.

### Question patterns

- Person: identity → period → actions → historical role → limits of current evidence.
- Concept / event: meaning → context → mechanism/relationship → significance → limits.
- Relationship / transition: prior state → trigger/cause → transition → outcome →
  significance → limits.

## Output shape

Match the output to the effort tier. **Fast path** → just (1) a direct answer plus a
one-line evidence note (which statement/source backs it); skip the rest. **Full path** →
the full structure below. Don't wrap a one-fact lookup in the full ceremony.

1. **Direct answer** (a few sentences).
2. **Systematic explanation** (prior context → turning point/cause → change → significance,
   when the evidence supports it).
3. **Evidence chain**: concept/statement hit → relation/page evidence (annotated `usable` /
   `weak fallback` / `mismatched`) → evidence-expanded source text → conclusion.
4. **Debug block** (mandatory for broad/comparative/causal/debugging questions):
   - `planned concepts` and `planned statements`
   - `wiki hits`, `ontology hits` (which had `statement_id`; which provenance succeeded),
     `search hits` (include `resolved_stream_ids` when scope is in doubt)
   - `answer basis`: which layer carried the answer, what each other layer contributed,
     and which statements remain `Not established`
   - name actual hits; if a layer contributed nothing, say so plainly.
5. **Summarized answer** (a short final close).

If the user writes `debug mode`, keep this shape and make the debug block more detailed —
it is an output switch, not a change of retrieval strategy.

## Common failure modes

- Using the wrong domain and trusting unscoped hits (check `resolved_stream_ids`).
- Reading local corpus files instead of the TDB APIs.
- Stopping at the first triple / first search hit when the question needs a fuller answer.
- Stopping at a thin wiki page instead of following adjacent pages, page evidence, or
  statement provenance.
- Ignoring `qualifier`s, or flattening a time/place/culture-bounded claim into a universal.
- Treating search rank as evidence, or claiming statement/graph support when only
  `search/query` was actually used.
- Looping indefinitely instead of answering with labeled gaps (2 rounds by default; a 3rd
  only for one specific cheap anchor).
- Treating empty `resolved_stream_ids` as "no results" (it means unscoped/wrong domain) —
  or treating zero hits under a correct scope as a misconfiguration.
- Waiting for a pagination cursor that does not exist (raise `limit`, max 200), or giving
  up after a single backend timeout instead of retrying with backoff.

## Quick start

1. Reach the gateway at `http://10.124.48.91:8989` over HTTP, no auth (MCP tools, if
   present, wrap the same endpoints).
2. Run `search/query` with `domain: "archeology"` and confirm `resolved_stream_ids` is
   non-empty (empty + hits = wrong domain → stop and fix the binding).
3. Search distinctive proper nouns / key terms (`search/query` + `ontology/fact/search?q=`,
   plus `qa/evidence-pack` for quick recall); drive any `statement_id` to `statement/get` +
   `statement/provenance` — the statement layer is the grounding backbone.
4. Corroborate exact claims, expand ~2 rounds, then answer (fast path: answer straight from
   the first solid statement).
