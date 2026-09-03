# Case 3 — Ingestion pipeline changes what a DAC knows

- **Scenario:** 2 (text → data → local TDB)
- **Status:** ⚠️ READY except the source prefix — see Open item
- **Runtime:** ask ~40 s · ingest several min · ask again ~40 s
- **Screens:** chat at `/`, then **数据管理 → TDB 入库流水线** (`/tdb-pipeline`)

## What this proves

The DAC's mind is data, not weights. Ask before ingest: it cannot answer. Run
the pipeline. Ask again: the same question is now answered from the new text,
with provenance.

## Talk track (preview card)

> Nothing about the model changes in the next four minutes. We drop a paper into
> a bucket, the pipeline chunks it, builds ontology and wiki layers, and writes
> it into the archaeology test library. The same question that failed at the top
> of this case gets answered at the bottom of it.

## The three gaps in the scenario doc — all closed

The doc flags three unknowns. The 入库 page answers each:

| Doc's question | Answer |
| --- | --- |
| Where to input the target DAC's name? | **入库目标** dropdown — 9 targets, each labelled with its gateway and the skill agent that shares that TDB |
| How to trigger the pipeline? | **新建入库任务** → 提交任务; runs async, progress in the table |
| Who creates that DAC's local TDB? | Nobody — ingestion and Q&A **share one TDB per domain**. Writing to `:8996` is exactly what `tdb-archeology-papers-test-qa` reads. |

## Steps

1. Chat: ask the "before" question → expect no substantive answer.
2. Go to `/tdb-pipeline`, click **新建入库任务**.
3. Target **考古学（论文测试库，隔离）** — gateway `:8996`, collection `academic_papers`.
4. Source type **S3 / MinIO**, paste the source prefix.
5. Submit; show the row going `running` with a progress count.
6. When it succeeds, return to chat and re-ask → answered, with the new source cited.

## Verified

A prior run proves the whole path: `run-20260830T170400Z-075cf3`, target
`archeology → http://10.124.48.91:8996`, source
`s3://archaeology-source/papers/ActaAnthropologicaSinica/`, 2/2 files, 0 failures.

## ⛔ Target `:8996`, never `:8989` — ingest time scales with domain size

Stage `11/wiki` begins by downloading **every active wiki page in the target
domain** to build a case-insensitive slug map, paging 500 at a time
(`build_wiki_pages.py` → `load_existing_wiki_slugs`). It logs nothing while doing
it, so it looks hung.

| target | wiki pages | round trips | stage 11 cost |
| --- | --- | --- | --- |
| `:8996` papers test library | < 10,000 | ~20 | seconds |
| `:8989` production archeology | ~600–700k | ~1,300 | **~50 min per file** |
| `:8990` history | ~100–400k | ~200–800 | many minutes |

Worse, `OFFSET` deepens as it goes — 0.65 s at offset 0, ~3.4 s at 400k — so the
total is quadratic in domain size, and the cost is paid **per file**, regardless
of how small the file is.

The 08-30 run finished quickly only because it targeted `:8996`. The 09-02 run
`run-20260902T153401Z-4c31d5` targeted `:8989` and was still in stage 11 after
an hour. **Keep the demo on 考古学（论文测试库，隔离）.**

## Open item — resolve before the demo

Pick an S3 prefix holding a paper that is **not yet ingested**, and write the
before/after question here. Re-running the 08-30 prefix ingests nothing new
unless 强制重新入库 is ticked — and a forced re-run cannot change any answer,
which kills the whole point of the case.

Ingestion takes minutes. If the slot is tight, start this one before Case 2 and
come back to it.
