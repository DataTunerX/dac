# WWYBSJ System 1 Answer Memory

Use this reference when `tdb-wwybsj-answering` handles a question that can reuse
or create a TDB System 1 answer artifact.

System 1 is a serving projection over previously grounded answers. It is not a
new evidence source, and it must not weaken the `wwybsj` / `archeology` evidence
boundary.

## Available Tools

Use these when exposed by the local TDB MCP or gateway:

- `s1_recall_answer_artifacts`
  - gateway equivalent: `POST /v2/memory/answer/artifact/recall`
  - backed by `memory_answer_artifact`
- `s1_record_answer_artifact`
  - gateway equivalent: `POST /v2/memory/answer/artifact/record`
  - use after a successful System 2 answer
- `s1_record_answer_validation`
  - gateway equivalent: `POST /v2/memory/answer/validation/record`
  - backed by `memory_answer_validation`

## Build the Recall Key

Before recall, normalize the question into a stable fingerprint. Do not use the
raw user wording alone as the key.

Use:

```json
{
  "domain": "wwybsj",
  "intent": "<intent>",
  "concepts": ["<item/type/material/period/question anchors>"],
  "slots": {
    "ww_bianhao": "<registry number when resolved>",
    "item_name": "<registered item name when resolved>",
    "period": "<period label when present>",
    "material": "<material when present>",
    "category": "<category when present>"
  },
  "entity_ids": ["<stable entity ids>"],
  "time_anchor": "registry_snapshot"
}
```

Intent mapping:

- `entity_lookup`: single-item identity, features, dimensions, material, period,
  condition, source, or previous item summary
- `enumeration`: `哪些`, `有哪些`, collection slice listing, type/material/period
  lists
- `aggregate_snapshot`: stable collection counts or distributions over the
  registry snapshot
- `comparison`: cultural, typological, material, or period comparison
- `unknown`: ambiguous prompts that need System 2 classification

Entity ids:

- Prefer an existing local ontology concept id from `wwybsj` if recovered.
- For registry-number questions, include a stable registry anchor such as
  `wwybsj.registry.<zero-padded ww_bianhao>`.
- Do not use the internal JSON `id` as the primary entity id unless the user
  explicitly asked for `record_id`, `内部id`, or `JSON id`.

## Recall Before Full Retrieval

At the start of every answer:

1. Resolve obvious registry-number or item-name anchors from local `wwybsj`
   wiki/search or `wwybsj.json` when needed for the fingerprint.
2. Call `s1_recall_answer_artifacts` with:
   - `domain_id="wwybsj"`
   - the mapped `intent`
   - the structured `question_fingerprint`
   - `entity_ids` when available
   - `serving_statuses=["active"]`
   - `limit=3`
3. If no candidate is returned, continue to the full retrieval workflow.
4. If a candidate is returned, inspect `freshness_policy`,
   `validation_contract`, `answer_payload`, `evidence_refs`, and `provenance`
   before deciding whether it can be served.

## Serve, Validate, or Fall Back

System 1 may directly serve only low-risk, previously grounded answers:

- single-item registry facts and already-reviewed item summaries
- stable collection slice lists or counts tied to the registry snapshot
- short museum-facing summaries whose evidence refs still point to local
  `wwybsj` facts

System 1 must trigger minimal revalidation before serving when:

- `freshness_policy.require_revalidation=true`
- the answer is an aggregate over a slice that may have changed
- the answer depends on a wiki page, statement, or provenance record that may
  have been updated
- the user asks for `最新`, `现在`, `最近`, or another current-state framing

If validation is run, record it with `s1_record_answer_validation`. Serve the
candidate only when validation passes. If validation fails or cannot be run,
fall back to System 2.

System 1 must not directly serve:

- exact excavation place, tomb/site origin, or direct comparandum claims unless
  the artifact evidence refs contain direct local support
- cultural influence, lineage, migration, workshop, or social-organization
  conclusions without System 2 review
- answers whose local/remote evidence boundary is missing or unclear
- stale, superseded, revoked, or provenance-empty candidates

When using a System 1 candidate, say so briefly in the evidence report:
`System 1: reused answer artifact <id>; validation <not required/passed>; evidence refs checked <yes/no>`.

## Record After System 2

After a full System 2 answer succeeds, record a reusable artifact when the answer
is grounded, bounded, and likely to recur.

Use `s1_record_answer_artifact` with:

- `domain_id="wwybsj"`
- mapped `intent`
- normalized question and structured fingerprint
- `entity_ids`
- final `answer_text`
- `answer_payload` with the main registry facts, interpretation layer, and
  limitations when practical
- `evidence_refs` containing local wiki/page slugs, statement ids, event ids,
  registry file path, or remote background refs used
- `provenance` that distinguishes `wwybsj` facts from `archeology` background
- `freshness_policy`
  - registry item facts: long TTL or `temporal_type="registry_snapshot"`
  - wiki/statement-derived summaries: require revalidation
  - current analytics: short TTL and require revalidation
- `validation_contract`
  - single item: re-check registry number/name/date/material/category fields
  - collection slice: re-check count and representative entity ids
  - interpretation: require System 2 review rather than direct fast serving

### Evidence refs schema

The local gateway validates `evidence_refs` as an array of evidence-reference
objects. Use only fields supported by `EvidenceRefSchema`:

- `resource_id`
- `artifact_id`
- `artifact_version_id`
- `decision_id`
- `event_id`
- `url`

For most `wwybsj` answer artifacts, prefer `{ "url": "...", "description": "..." }`
when using the MCP tool, or `{ "url": "..." }` when calling the gateway HTTP API
directly. Put human-readable evidence detail in `provenance` and
`answer_payload` as well, because gateway HTTP responses may omit fields outside
the route response schema.

Good evidence refs:

```json
[
  {
    "url": "tdb-local-file:///Users/ningwu/eis/.codex/skills/tdb-wwybsj-answering/wwybsj.json#registry_snapshot_465_records"
  },
  {
    "url": "tdb-http://localhost:8080/v2/wiki/search?domain=wwybsj&q=唐代海兽葡萄纹铜镜"
  },
  {
    "url": "tdb-http://10.124.48.91:8989/v2/wiki/search?domain=archeology&q=瓦当%20莲花纹"
  }
]
```

Do not use ad-hoc keys such as `type`, `domain`, `path`, `endpoint`, `query`, or
`note` inside `evidence_refs`. They may be stored in raw JSONB but disappear from
gateway recall output, producing empty-looking refs such as `{}`. If you need
those details, encode them in the `url` string and repeat them in `provenance`.

## Ingest Existing Q&A

Use this when the user has already answered questions and wants them stored in
System 1 so future turns can reuse them.

### Input contract

For each existing Q&A item, collect or derive:

- `question`: original user question
- `answer_text`: final answer to serve
- `evidence_refs`: local wiki slugs, statement ids, event ids, registry file
  path, source report path, or remote background refs used by the answer
- `evidence_boundary`: which claims are local `wwybsj` facts, which are remote
  `archeology` background, and which are interpretation
- optional `review_status`: `reviewed`, `draft`, `needs_evidence`, or
  `deprecated`
- optional `source_task_id` / `source_run_id` / `source_decision_id`

Do not import Q&A as `active` when the answer lacks evidence refs or collapses
local registry facts with remote interpretation. Store those as `stale` or skip
them until System 2 re-validates the answer.

### Ingest workflow

For each Q&A:

1. Classify the question intent using the same mapping as recall.
2. Resolve anchors against local `wwybsj` wiki/search and `wwybsj.json`:
   registry number, item name, period, material, category, and ontology concept
   id when available.
3. Build the same `question_fingerprint` that runtime recall will build.
4. Build `entity_ids`; prefer ontology concept ids, then
   `wwybsj.registry.<zero-padded ww_bianhao>`.
5. Normalize the question into a stable human-readable form.
6. Decide `serving_status`:
   - `active`: reviewed, evidence-bounded, and safe under System 1 rules
   - `stale`: useful but needs revalidation before serving
   - `revoked`: known wrong or superseded by curator review
7. Create `freshness_policy` and `validation_contract`.
8. Call `s1_record_answer_artifact`.
9. If the import performed a check, call `s1_record_answer_validation` with the
   observed values.

### Recommended artifact fields

Use this shape for `answer_payload`:

```json
{
  "registry_facts": {},
  "local_wwybsj_claims": [],
  "remote_archeology_context": [],
  "interpretive_claims": [],
  "limitations": [],
  "source_question": "<original question>",
  "ingest_source": "<file path, task id, or manual import note>"
}
```

Use this shape for `provenance`:

```json
{
  "ingest_method": "existing_qa_import",
  "local_wwybsj": ["<registry/wiki/statement refs>"],
  "remote_archeology": ["<background/source refs>"],
  "evidence_boundary_checked": true,
  "review_status": "reviewed"
}
```

Use this shape for `freshness_policy`:

```json
{
  "temporal_type": "registry_snapshot",
  "ttl_seconds": 31536000,
  "require_revalidation": false
}
```

Set `require_revalidation=true` when the Q&A depends on wiki prose, semantic
statements, current analytics, or interpretation that may change.

Use this shape for `validation_contract`:

```json
{
  "check_type": "wwybsj_registry_fields",
  "expected": {
    "ww_bianhao": "<registry number>",
    "ww_mingchen": "<item name>",
    "ww_niandai_jt": "<period>",
    "ww_leibie": "<category>",
    "ww_zhidi_c": "<material>"
  },
  "expected_match": "exact_or_empty_ok"
}
```

For comparison, lineage, and social-interpretation Q&A, use:

```json
{
  "check_type": "system2_review_required",
  "reason": "interpretive answer requires evidence-boundary review before direct serving"
}
```

### Idempotency

Use a deterministic `idempotency_key` so repeated imports do not duplicate the
same artifact:

```text
wwybsj:s1:<intent>:<fingerprint-hash>:<answer-hash>
```

If the same question gets a materially revised answer, create a new artifact and
mark the old one `superseded` or `revoked` when the tooling supports it. Do not
leave two conflicting `active` artifacts for the same fingerprint.

### Batch import guardrails

- Import `reviewed` Q&A first; keep drafts as `stale`.
- Sample-check a batch by running recall on representative questions before
  declaring the import usable.
- For item-number questions, verify that `ww_bianhao` rather than internal JSON
  `id` was used.
- For answer variants, prefer one canonical artifact plus aliases in
  `question_fingerprint.concepts` / `slots`, not many duplicate artifacts.
- If source evidence cannot be recovered, run System 2 once and record the
  validated result instead of importing the old answer blindly.
