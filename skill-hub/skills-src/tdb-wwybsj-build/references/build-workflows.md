# Build Workflows

Use these commands when adding artifacts, rebuilding the domain, or verifying a
completed run. All commands assume:

```bash
cd /Users/ningwu/eis/.codex/skills/tdb-wwybsj-build/scripts
```

## Data Files

- Base registry snapshot: `../data/wwybsj.json`
- New-item overlay: `../out/wwybsj_new_items.json`
- Override base path with `WWYBSJ_DATA_JSON=/path/to/wwybsj.json`
- Override output directory with `WWYBSJ_OUT_DIR=/path/to/out`
- Override overlay path with `WWYBSJ_NEW_ITEMS=/path/to/items.json`

Do not edit `data/wwybsj.json` for new artifacts. It is the frozen registry
snapshot. Use the overlay so the same ingest, L0, L1, L2, L3, and wiki scripts
see base plus new records.

## Add One Or More Artifacts

Dry-run first. The dry-run summary becomes the provenance text that L0 facts
cite, so inspect it before writing:

```bash
python3 wwybsj_new_item.py --json "$PAYLOAD"
```

Accepted payload shapes:

- one object
- an array of objects
- `{"records": [...]}`
- `{"data": [...]}`

Friendly Chinese aliases are accepted for common fields, including `名称`,
`编号`, `类别`, `质地`, `质地大类`, `年代`, `级别`, `来源`, `尺寸`, `质量`,
and `质量单位`.

Write the overlay and run the base chain:

```bash
python3 wwybsj_new_item.py --json "$PAYLOAD" --execute --build
```

`--build` runs only:

```text
wwybsj_ingest.py --id <id> --execute
wwybsj_l0.py --registry-no <登记号> --execute
wwybsj_l1.py --execute
```

Then finish the semantic and presentation layers:

```bash
python3 wwybsj_l2.py --registry-no <登记号> --execute
python3 wwybsj_stance.py --recompute --execute
python3 wwybsj_l3.py --registry-no <登记号> --execute
python3 wwybsj_wiki.py --registry-no <登记号> --execute
python3 wwybsj_verify.py --check q0
```

If L2 or L3 fails because of LLM, retrieval, or timeout behavior, report the
layer, error, and retry command. Do not write fabricated research claims or
fallback exhibit prose.

## Full Rebuild

```bash
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

Full L2/L3 rebuilds are slow because they depend on remote retrieval and LLM
calls. Do not promise fixed timing; use observed stderr progress and summaries.

## Validation

Use gateway readback:

```bash
python3 wwybsj_verify.py
python3 wwybsj_predicates.py --validate
python3 wwybsj_l2_report.py
```

Competency checks:

| Check | Purpose |
|---|---|
| Q0 | Layer counts, artifact count, term count, wiki page count |
| Q1 | Artifacts dated before CE 300 using typed intervals |
| Q3 | Conflicting intervals for the same period label |
| Q6 | Reverse join from remote concepts to local artifacts |
| Q7 | Orphan extractor rows |

Run Q0 after copying databases, repointing gateways, or packaging the skill.

## New-Item Guardrails

`wwybsj_new_item.py` intentionally rejects unknown fields and duplicate registry
numbers. Missing category, material, or period produces warnings rather than a
hard failure because the registry can be incomplete; do not fill those values
from common sense.

The script fills all 34 registry columns before writing overlay records so the
existing L0 parsers see the same shape as the base dump.
