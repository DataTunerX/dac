# Case 7 — Architecture drawings (room layout)

- **Scenario:** 6
- **Status:** ❌ BLOCKED — no data loaded
- **Target prompt:** `设计图A01里面有几件卧室？`

## Why it is blocked

Nothing on the platform holds architectural drawings:

- No `DataDescriptor` resources exist in any namespace (`kubectl get datadescriptors -A` → none).
- No semantic groups are populated.
- No ingestion target in the 入库 allowlist covers drawings — the 9 targets are
  the 7 humanities domains, wwybsj, and the archaeology papers test library.
- Nothing in the repo or skill-hub references floor plans, rooms, or 卧室.

There is also a **format** problem, not just a missing-file problem. This
scenario needs a drawing parsed into structured room entities. The document
pipeline in Case 3 is a *text* pipeline — chunks, ontology, wiki layers. Counting
bedrooms in drawing A01 needs either vision extraction or a pre-built room table.
Neither is wired up.

## What it would take

1. Load the drawings somewhere the platform can read (S3 bucket + asset scan).
2. Establish how a drawing becomes structured rooms — VLM extraction in the
   data-sinker, or an out-of-band table loaded as a data source.
3. A skill that answers over that structure, plus its agent (Case 5's path).

That is a build, not a setup step.

## Recommendation

Cut. If the architecture story must be told, tell it as roadmap over a static
slide rather than as a live query that will return nothing.
