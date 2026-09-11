---
name: circuit-diagram-qa
description: Use when answering questions about automotive circuit diagrams, components, terminals, nets, wiring, control relationships, topology, geometry, or extraction evidence that should be grounded in the circuit-diagrams TDB gateway.
---

# Circuit Diagram QA

Answer circuit-diagram questions as an evidence task, not as an electrical-engineering guess. Use the TDB gateway to identify the relevant page, resolve page-scoped concepts, inspect the requested relationship, and trace any asserted relationship to the source page JSON. Reply in the user's language.

## Deployment

The provided circuit-diagram target is:

- Gateway: `http://10.124.48.91:9012`
- Domain: `circuit_diagrams`
- Stream: `circuit_diagrams.bmw_328i_1997`

The gateway is unauthenticated on the trusted network. Use HTTP directly with `curl` when no TDB MCP wrapper is available. Keep `stream_id` on stream-sensitive calls; do not search the whole corpus accidentally.

Before relying on the target, check `GET /health`, `GET /v2/health`, and `GET /v2/search/domain-stream/list?domain=circuit_diagrams`. The binding should include `circuit_diagrams.bmw_328i_1997`.

## Network permission and TDB access

The private TDB gateway may be reachable from an approved network context while blocked by the default command sandbox. A failed `curl` is not enough to conclude that TDB or the API is down.

1. Run a read-only health check with bounded timeouts, preferably `curl --connect-timeout 3 --max-time 8 -fsS "$TDB_GATEWAY/v2/health"`; fall back to `/health` if needed.
2. Classify the failure before retrying. `Operation not permitted`, repeated TCP failures across TDB ports, or a sandbox/network-policy message indicates local egress restriction. `Connection refused` after a permitted TCP attempt may indicate the remote service or port is unavailable; do not silently relabel it as a query miss.
3. If the default sandbox blocks the private address, request the approved network context for the same read-only health/query command using the host's escalation mechanism. Do not change gateway configuration, add credentials, use a database connection, or retry blindly.
4. After network access is granted, repeat `/v2/health`, `/health`, and the domain-stream check, then run the actual read-only query. Only a successful HTTP response establishes gateway reachability; only the search response's scope fields establish retrieval scope.
5. Record the distinction in the answer/debug trail: for example, `default sandbox blocked TCP egress; the gateway query was not evaluated`, rather than `TDB had no data`. If the approved retry succeeds, say that the gateway was reachable in the approved network context.

This network diagnostic is separate from corpus-scope diagnosis. Once connected, inspect `resolved_stream_ids` (when returned): a correctly scoped stream with zero hits is a retrieval miss; non-empty hits with an empty scope list are unscoped and must not be cited as circuit-diagram evidence. Use bounded retries with backoff for transient `5xx`, `429`, or timeout responses, and stop after a few attempts.

Example read-only diagnostic:

```sh
curl --connect-timeout 3 --max-time 8 -fsS "$TDB_GATEWAY/v2/health" | jq .
curl --connect-timeout 3 --max-time 8 -fsS "$TDB_GATEWAY/health" | jq .
```

## Evidence rules

- `accepted` is the loader's confirmed tier. `candidate` is reviewable extraction output, not a confirmed circuit fact.
- Confidence is a floating-point range; do not compare decimal strings for exact equality.
- Repeated printed parts are page-scoped concepts. A concept such as `...p001.rect_0013` is not automatically the same physical vehicle component as a similarly named concept on another page.
- `directly_connected_to` is reconstructed topology from source extraction. It is not a substitute for electrical-engineering validation.
- `has_terminal` and `terminal_on_net` are mostly candidates in this dataset. Never present every terminal assignment as verified.
- Component labels can contain OCR errors (`$WITCH`, `AIC`, missing spaces). Try aliases, a shortened name, and nearby page text when an exact search misses.
- A search hit is navigation evidence until its content or semantic graph actually supports the claim. Do not infer a relationship from ranking or from a label alone.
- The page JSON/`metadata.semantic_graph` is the source of truth for geometry, extraction limitations, raw wire joins, and relationships not promoted into the ontology.
- Do not use local corpus files as a substitute for the gateway unless the user explicitly authorizes leaving the API boundary.

## Query workflow

1. **Plan the question.** Split it into the component, action or relationship, direction, page/vehicle context, and any terminal/net/geometry constraint. Write the short claims that must be proven, such as `X controls Y`, `signal A provides_signal_to B`, or `terminal T is on net N`.
2. **Discover the page.** Use `POST /v2/search/query` with the domain, stream, a natural-language query, `mode:"hybrid"`, and a small limit. Use a lexical pass for exact labels, page numbers, or complete relationship enumerations. Inspect `metadata.semantic_graph.page` and `source_file`.
3. **Resolve the page-scoped concept.** Use `GET /v2/ontology/concept/search?q=<short component name>&limit=10`. Select the concept whose ID belongs to the page under investigation; do not use a same-named concept from another page.
4. **Read the relationship.** Prefer `GET /v2/ontology/concept/neighbors` with the concept ID, `direction=in|out`, the requested predicate, and a useful limit. For predicate-wide discovery use `GET /v2/ontology/fact/list` with `stream_id`, `predicate`, `status=all|accepted`, `limit`, and `offset`.
5. **Trace provenance.** For each relationship used in the answer, resolve its returned `fact_id` dynamically and call `GET /v2/ontology/fact/provenance?fact_id=...&stream_id=...&evidence_limit=5`. Confirm that the evidence span directly states the relationship and record the source file, JSON path, page, and qualifier. If the response exposes a `statement_id`, use the statement get/provenance path when available, while retaining the page evidence.
6. **Inspect raw page metadata when needed.** Query the page again and inspect `metadata.semantic_graph.validation`, `limitations`, `wire_join_evidence`, and `relationships[]`. For completeness checks, a lexical page query with a high limit may be more reliable than a materialized fact list.
7. **Expand only when needed.** Mine recovered source text for aliases, neighboring components, net names, or page anchors and run one or two narrow follow-up queries. Stop with a labeled gap rather than looping or filling it from memory.

## Lazy materialization and completeness

The current fact-list path uses a semantic-statement projection that can materialize rows lazily. A predicate-only fact list may therefore show fewer facts than the source contains, especially after a clean load. Treat `fact/list` as discovery, not a completeness count.

When the user asks for *all* relationships of a type, search the page cards with a lexical query and filter the preserved graph:

```sh
curl -fsS -X POST "$TDB_GATEWAY/v2/search/query" \
  -H 'content-type: application/json' \
  --data '{"domain":"circuit_diagrams","stream_id":"circuit_diagrams.bmw_328i_1997","query":"BMW 328i 1997 circuit diagram page","mode":"lexical","limit":50}' \
| jq '[.hits[].metadata.semantic_graph.relationships[]? | select(.type == "controls")]'
```

State the distinction explicitly: ontology neighbors/facts show materialized relationships; the source semantic graph is the completeness path for relationships preserved in page JSON.

## Relationship read paths

| Question | Preferred path | Extra evidence rule |
|---|---|---|
| What does X control? | concept search → outgoing `controls` neighbors | provenance must support each asserted edge |
| What provides a signal to X? | incoming `provides_signal_to` neighbors | preserve direction and status |
| What switches power to X? | `fact/list` with `switches_power_to` | resolve fact provenance |
| What is directly connected to X? | `directly_connected_to` neighbors | label as reconstructed topology |
| Where is X grounded? | outgoing `grounded_at` neighbors | require `accepted` for confirmation |
| Which net contains terminal T? | outgoing `terminal_on_net` | candidate is not verified |
| Which terminals belong to X? | outgoing `has_terminal` | inspect status and provenance |
| Why does TDB claim relation Y? | fact provenance | report qualifier, source file, and JSON path |
| What raw wire joins were found? | page search → `wire_join_evidence` | report extraction limitations too |

## Answer shape

For a simple lookup, give the direct answer, status/confidence, and a compact evidence note. For a broad, comparative, topology, or debugging question, include:

1. Direct answer with inline numeric citations such as `[1]`.
2. Relationship direction and page context.
3. Evidence chain: page/concept → fact or neighbor → provenance/source span → conclusion.
4. A short limitations note covering candidates, OCR, reconstructed topology, lazy materialization, or raw wire-join caveats when relevant.
5. `References` with readable source notes and minimal trace IDs (`stream_id`, `fact_id`/`statement_id`, source file, JSON path).

Use `Not established` for a plausible relationship that lacks a direct accepted/provenance-bearing basis. Do not silently upgrade `candidate`, weak provenance, a nearby component, or an engineering expectation into a confirmed fact. If sources disagree, report the disagreement and identify which evidence is accepted or more direct.

## Common failure modes

- Searching without `domain`/`stream_id` and accidentally mixing documents.
- Treating a page-scoped concept ID as a global vehicle component.
- Calling `fact/list` once and claiming it is complete.
- Presenting a candidate terminal/net assignment as verified.
- Treating `directly_connected_to` as validated electrical connectivity.
- Ignoring `wire_join_evidence`, `validation`, or `limitations` when geometry/topology is asked.
- Guessing through OCR errors instead of searching aliases and nearby text.
- Reporting a relation without reading its provenance.
- Purging or reloading a database casually. `/v2/ingest/text` appends page events; execute a clean load only once on an isolated target and never purge another domain.

## Quick verification

```sh
export TDB_GATEWAY=http://10.124.48.91:9012
export TDB_DOMAIN=circuit_diagrams
export TDB_STREAM=circuit_diagrams.bmw_328i_1997

curl -fsS "$TDB_GATEWAY/health" | jq -e '.status == "ok"'
curl -fsS --get "$TDB_GATEWAY/v2/search/domain-stream/list" \
  --data-urlencode "domain=$TDB_DOMAIN" --data-urlencode "stream_id=$TDB_STREAM" \
  --data-urlencode 'limit=10' \
  | jq -e --arg stream "$TDB_STREAM" '.bindings | any(.stream_id == $stream and .status == "active")'
curl -fsS --get "$TDB_GATEWAY/v2/ontology/concept/search" \
  --data-urlencode 'q=AUTOMATIC CLIMATE CONTROL MODULE' --data-urlencode 'limit=10' \
  | jq -e '.concepts | length > 0'
```
