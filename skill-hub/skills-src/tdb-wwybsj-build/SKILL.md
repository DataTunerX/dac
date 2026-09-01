---
name: tdb-wwybsj-build
description: >
  Use when adding a WWYBSJ artifact from registry JSON, building or rebuilding
  the local `wwybsj` cultural-relic TDB domain, auditing its layered ontology,
  aligning controlled terms to the remote archeology corpus, or verifying the
  generated wwybsj statements and wiki pages through gateway APIs.
---

# tdb-wwybsj-build

Build and verify the local `wwybsj` TDB domain from museum registry records.
The skill moves and annotates knowledge; it must not invent cultural, historical,
or archaeological claims.

## Non-Negotiables

- Research reads only from remote `archeology`; writes go only to local `wwybsj`.
- Use gateway APIs only. Do not add SQL, `psql`, or database connection strings.
- L0 facts are registry facts. They are `observed`, deterministic, and must cite
  the registry provenance event.
- Research claims must cite remote source text with `stream_id`, `event_id`, and
  `source_span`. If that evidence is missing, write an evidence gap instead of a
  claim.
- Keep identifiers prefixed: `wwybsj.artifact.*`, `wwybsj.predicate.*`,
  `wwybsj.term.*`, `wwybsj.ref.*`, `wwybsj.qualifier.*`.
- Every statement written for this domain must carry `metadata_json.domain =
  "wwybsj"`.
- L1 alignment decisions are data in `alignment_review.json`, not ad hoc code.
- The base registry snapshot is bundled at `data/wwybsj.json`; new records belong
  in the overlay, not in the snapshot.

## Routing

Read only the reference needed for the current task:

- Adding one or more artifacts: read
  [references/build-workflows.md](references/build-workflows.md).
- Rebuilding or validating the domain: read
  [references/build-workflows.md](references/build-workflows.md) and
  [references/gateway-api.md](references/gateway-api.md).
- Changing L0/L1/L2/L3 semantics, predicates, or validation: read
  [references/architecture.md](references/architecture.md) and inspect
  `predicate_contract.json`.
- Debugging retrieval, coverage, L1 alignment, timeouts, or noisy evidence: read
  [references/research-heuristics.md](references/research-heuristics.md) and
  [references/known-failures.md](references/known-failures.md).
- Producing user-facing summaries after a build: read
  [references/reporting.md](references/reporting.md).

## Data And Configuration

| Purpose | Default | Override |
|---|---|---|
| Source gateway | `http://10.124.48.91:8989` | `WWYBSJ_SOURCE_GATEWAY` |
| Target gateway | `http://10.124.48.91:8997` | `WWYBSJ_TARGET_GATEWAY` |
| Base registry JSON | `data/wwybsj.json` | `WWYBSJ_DATA_JSON` |
| Output directory | `out/` | `WWYBSJ_OUT_DIR` |
| New-item overlay | `out/wwybsj_new_items.json` | `WWYBSJ_NEW_ITEMS` |

L2 and L3 use the vendored LLM helper under
`vendor/tdb_pipeline/llm_config_common.py` plus
`vendor/tdb_pipeline/dac.json`. They must not require an external
`/Users/ningwu/eis/tdb/pipeline` checkout to import `llm_config_common`.

The bundled base snapshot has 465 flat registry records and 34 fields. `id` is
the JSON row id; `ww_bianhao` is the collection registry number and is the
artifact identity.

## Layer Model

```text
L0 registry facts     observed    artifact -> typed values / local terms
L1 term alignment     inferred    local term -> remote archeology concept cluster
L2 research claims    attributed  artifact -> claims backed by remote text
L3 exhibit prose      hypothesized generated prose stored as data
wiki projection       rendered    deterministic page from L0/L1/L2/L3
```

Remote archaeology facts are referenced, not copied. L1 stores handles back to
remote concept clusters so downstream readers can resolve context on demand.

## Common Commands

Check gateways:

```bash
curl -s http://10.124.48.91:8989/health && echo
curl -s http://10.124.48.91:8997/health
```

Add a pasted record and run the full single-record chain:

```bash
cd /Users/ningwu/eis/.codex/skills/tdb-wwybsj-build/scripts
python3 wwybsj_new_item.py --json "$PAYLOAD"
python3 wwybsj_new_item.py --json "$PAYLOAD" --execute --build
python3 wwybsj_l2.py --registry-no <登记号> --execute
python3 wwybsj_stance.py --recompute --execute
python3 wwybsj_l3.py --registry-no <登记号> --execute
python3 wwybsj_wiki.py --registry-no <登记号> --execute
python3 wwybsj_verify.py --check q0
```

Full rebuild:

```bash
cd /Users/ningwu/eis/.codex/skills/tdb-wwybsj-build/scripts
python3 wwybsj_ingest.py --all --execute
python3 wwybsj_l0.py --all --execute
python3 wwybsj_l1.py --execute
python3 wwybsj_l2.py --all --execute --resume
python3 wwybsj_stance.py --recompute --execute
python3 wwybsj_l3.py --all --execute --resume
python3 wwybsj_wiki.py --all --execute
python3 wwybsj_verify.py
python3 wwybsj_predicates.py --validate
python3 wwybsj_l2_report.py
```

`wwybsj_new_item.py --execute --build` runs only ingest, L0, and L1. It is not a
full completion signal; run L2, stance, L3, wiki, and verification afterward
unless the user explicitly asked to stop earlier.

## Script Map

```text
wwybsj_common.py      shared paths, registry loading, gateway wrappers
wwybsj_new_item.py    parse new records, write overlay, optional ingest/L0/L1
wwybsj_ingest.py      registry records -> provenance events
wwybsj_l0.py          deterministic observed registry statements
wwybsj_l1.py          local term -> remote concept-cluster anchors
wwybsj_research.py    read-only retrieval against remote archeology
wwybsj_l2.py          research statement generation with evidence gates
wwybsj_stance.py      recompute stance/corroboration statements
wwybsj_l3.py          exhibit prose generation with gates
wwybsj_wiki.py        deterministic wiki page projection
wwybsj_verify.py      competency checks
wwybsj_predicates.py  predicate registration and contract validation
wwybsj_l2_report.py   L2 output and gap report
```

## Validation

Use gateway readback, not plan files or intended counts, when reporting status.
The normal acceptance set is:

```bash
python3 wwybsj_verify.py
python3 wwybsj_predicates.py --validate
python3 wwybsj_l2_report.py
```

For local skill maintenance, also run:

```bash
python3 scripts/test_wwybsj_common_paths.py
python3 scripts/test_wwybsj_vendored_llm.py
python3 scripts/test_wwybsj_l3_gate.py
```
