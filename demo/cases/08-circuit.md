# Case 8 — Circuit board data

- **Scenario:** 7
- **Status:** ❌ BLOCKED — no data loaded
- **Target prompt:** `电路图2号里面的最大芯片是什么？`

## Why it is blocked

Same as Case 7, for the same reasons: no data sources, no semantic groups, no
ingestion target, and nothing in the repo referencing circuits or components.

The format gap is if anything wider — "the largest chip on board 2" needs
component-level extraction with package sizes, i.e. a parts table per board.
The text pipeline cannot produce that from an image.

## What it would take

Board images or netlists ingested, a component-extraction step, and a skill that
answers over the component table. Build work, not configuration.

## Recommendation

Cut. Same treatment as Case 7 — roadmap slide, not a live query.
