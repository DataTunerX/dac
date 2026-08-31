# Gateway API

The skill has two TDB gateways:

| Role | Gateway | Domain | Permission |
|---|---|---|---|
| Source | `http://10.124.48.91:8989` | `archeology` | read-only |
| Target | `http://10.124.48.91:8997` | `wwybsj` | read/write |

Override with `WWYBSJ_SOURCE_GATEWAY` and `WWYBSJ_TARGET_GATEWAY`.

Check health:

```bash
curl -s http://10.124.48.91:8989/health && echo
curl -s http://10.124.48.91:8997/health
```

Expected service response includes `status: ok` and `service: tdb-gateway`.

## Source Reads

Use the wrappers in `wwybsj_common.py` (`sget`, `spost`) or the higher-level
research scripts. Common endpoints:

```text
GET  /v2/wiki/search?domain=archeology&q=<term>&limit=N
GET  /v2/wiki/page?domain=archeology&slug=<slug>
GET  /v2/wiki/page/evidence?domain=archeology&slug=<slug>
GET  /v2/ontology/concept/search?q=<term>&limit=N
GET  /v2/ontology/relation-candidate/list?domain=archeology&subject_label=<t>&limit=N
GET  /v2/ontology/fact/list?stream_id=<sid>&limit=300&offset=N
GET  /v2/ontology/statement/get?statement_id=<sid>
GET  /v2/ontology/statement/provenance?statement_id=<sid>
GET  /v2/search/domain-stream/list?domain=archeology
POST /v2/search/query {"domain":"archeology","query":"...","limit":N}
```

The only valid remote research domain is `archeology`. Do not use
`archeology_expert`, `Archaeology`, or local legacy archaeology domains as the
source for this skill.

## Target Reads

Use `wwybsj_common.py` gateway read helpers:

| Helper | Purpose |
|---|---|
| `list_statements()` | statement paging by subject, predicate, or value entity |
| `load_domain()` | contract-driven domain snapshot |
| `get_statement()` | one statement plus qualifiers |
| `statement_references()` | provenance for one statement |
| `wiki_page_slugs()` / `wiki_page()` | wiki page listing and body readback |
| `object_type_ids()` | object-type FK checks before registration |
| `relation_types()` | relation-type readback |
| `load_term_usage()` | term list and coverage from actual statements |
| `all_registry_nos()` | all collection registry numbers |

`statement/list` does not provide a domain or prefix filter. Contract-driven
enumeration is the supported whole-domain read pattern.

`statement/list` hides rejected and deprecated rows by default. The shared
wrapper passes `status=all` for audit operations.

There is no batch provenance endpoint; validation that checks references must
fetch statement provenance one statement at a time.

## Target Writes

Main write path:

```text
POST /v2/ontology/semantic/upsert-batch
```

Payload groups:

- `entities`
- `statements`
- `qualifiers`
- `references`

The endpoint returns counts, not statement ids. Derive ids from deterministic
statement keys or read back by subject/predicate.

Other target writes:

```text
POST /v2/event/append
POST /v2/search/domain-stream/bind
POST /v2/wiki/page
POST /v2/ontology/statement/status
```

`statement/status` updates by `statement_id`, not `statement_key`.

## Enum Values

- `page_type`: `entity`, `concept`, `source_summary`, `comparison`, `index`, `log`
- `knowledge_level`: `fact_like`, `topic_like`, `concept_like`,
  `generalization_like`, `principle_like`, `theory_like`
- `authority_kind`: `accepted_ontology`, `compiled_summary`, `methodology`,
  `candidate_derived`
- `concept_type`: `entity`, `event`, `session`, `time`, `topic`, `phrase`,
  `location`, `activity`
- legacy fact `status`: `accepted`, `candidate`, `rejected`, `needs_review`

Statement-layer status values differ from legacy fact status values; inspect
existing scripts before adding new filters.
