# Architectural Drawings TDB data contract

The reference Birchfield stream is:

`architectural_drawings.birchfield.floorplan`

The gateway is `http://10.124.48.91:8998` by default. Override it with
`ARCHITECTURE_TDB_GATEWAY`; override the domain and stream with
`ARCHITECTURE_TDB_DOMAIN` and `ARCHITECTURE_TDB_STREAM_ID`.

## Retrieval layers

1. `/v2/search/query` is semantic discovery and returns `hits` with content
   and metadata such as entity type, geometry, quality, and source text.
2. `/v2/ontology/fact/list` and `/fact/search` provide exact relation rows;
   constrain them with the Birchfield `stream_id`.
3. `/v2/ontology/statement/get` is the preferred semantic readback once a fact
   exposes `statement_id`.
4. `/v2/ontology/statement/provenance` returns source spans, event IDs, source
   JSON paths, and references to the scene graph.

The TDB materializes these source structures as searchable events, state
properties, ontology facts, semantic statements, and provenance references.

Important semantics:

- `adjacent_to` means geometric proximity only.
- `accessible_via` is the preferred relation for room navigation.
- `inside` supports containment questions such as text or fixture in a space.
- `opens_on` links an opening to a space; inspect both relation status and
  connected-space metadata before claiming a door connects two rooms.
- `accepted` is the confirmation boundary. `candidate`, `needs_review`, and
  `inferred` are not equivalent to accepted/verified.
- Area/length values may inherit a `100 px/m` assumption and can be marked
  `inherited_unverified`.
- OCR text may include recognition errors; use `alternatives`, raw text, and
  OCR confidence when available.

## Stable query examples

Natural-language discovery:

```http
POST /v2/search/query
{"stream_id":"architectural_drawings.birchfield.floorplan",
 "query":"Which room contains a toilet?","mode":"hybrid","limit":5}
```

Exact containment:

```http
GET /v2/ontology/fact/list?src_concept_id=archdraw:birchfield:fixture:fixture_000&predicate=inside&stream_id=architectural_drawings.birchfield.floorplan
```

Use the returned `statement_id` with statement get/provenance before presenting
the relationship as a confirmed answer.
