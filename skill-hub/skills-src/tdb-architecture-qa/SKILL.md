---
name: tdb-architecture-qa
description: Use when answering questions about the Birchfield architectural floor plan, including rooms, openings, fixtures, OCR notes, geometry, relationships, navigation, and evidence from the Architectural Drawings TDB. Does not cover other buildings, sites, or non-architectural domains.
---

# Architecture QA

Use this skill for questions about the Birchfield architectural floor plan in
the Architectural Drawings TDB: rooms, doors, windows, fixtures, OCR text,
geometry, adjacency, accessibility, paths, dimensions, and evidence.

## Source of truth

The source of truth is the isolated TDB gateway:

- Gateway: `ARCHITECTURE_TDB_GATEWAY` or `http://10.124.48.91:8998`
- Domain: `ARCHITECTURE_TDB_DOMAIN` or `architectural_drawings`
- Stream: `ARCHITECTURE_TDB_STREAM_ID` or
  `architectural_drawings.birchfield.floorplan`

Keep the stream boundary on every stream-scoped query. Do not read the local
scene-graph JSON and do not silently fall back to local files if the gateway is
unavailable. Report the gateway error or missing evidence instead.

The loaded Birchfield stream contains spaces, openings, fixtures, wall
components, OCR annotations, point/bounding-box/polygon geometry, quality
properties, and source-level provenance from the scene-graph and OCR inputs.

## Query routing

1. Check `GET /health` and `GET /v2/health` when connection or dataset scope is
   uncertain.
2. Resolve the active stream with
   `GET /v2/search/domain-stream/list?domain=architectural_drawings&status=active`.
3. Use `POST /v2/search/query` with the fixed `stream_id`, the user's natural-
   language question, `mode: "hybrid"`, and a small `limit` for discovery.
4. For exact relationships, use `GET /v2/ontology/fact/list` or
   `GET /v2/ontology/fact/search` with `stream_id`, filtering predicates such
   as `inside`, `opens_on`, `accessible_via`, `adjacent_to`, `labels`, or
   `mounted_on`.
5. If an exact fact has a `statement_id`, use
   `GET /v2/ontology/statement/get` and
   `GET /v2/ontology/statement/provenance` as the primary evidence path.
6. Use the hit's `event_id`, `source_edge_id`, `source_json_path`, source span,
   qualifiers, and metadata to explain where the claim came from.

For room lists or broad inventories, use search hits and the stream quality
summary, then corroborate important claims with exact facts. For paths, use
`accessible_via` only; do not construct a route from search ranking or
`adjacent_to`. For geometry, report returned coordinates/polygons and the
quality/scale caveat; do not infer precise measurements from embeddings.

## Evidence discipline

- Preserve `stream_id`, `concept_id`, `entity_id`, `text_id`, `opening_id`,
  `fixture_id`, `fact_id`, `statement_id`, `event_id`, and `source_edge_id`
  when they support a claim.
- `accepted` relationships may be presented as confirmed. `candidate`,
  `needs_review`, `inferred`, `unresolved`, and `missing_from_source` must be
  described as inferred, uncertain, or unavailable—not confirmed.
- `accessible_via` is the preferred navigation relation. `adjacent_to` is
  geometric proximity and does not prove passability.
- Inspect qualifiers as part of the claim, especially association method,
  directedness, confidence, and source location.
- Respect TDB quality warnings: dimensions/areas may rely on the uncalibrated
  `100 px/m` assumption; walls may be mask components rather than centerlines;
  openings may not resolve to exactly two spaces; and OCR may be noisy.
- If TDB returns no evidence, say "not established in the Birchfield TDB"
  instead of guessing.

## Response shape

Answer in the user's language. Give the direct result first, then a short
evidence block containing the stream, IDs, status/confidence, source span or
JSON path, and relevant quality warning. For paths, list the room sequence and
opening/relation IDs, explicitly marking candidate paths as inferred.

Read [references/gateway_api_doc.md](references/gateway_api_doc.md) when
detailed field semantics, endpoint selection, or an ambiguous result requires
it.
