# DAC demo — operator guide

Run the demo one case at a time:

```
/demo          # agenda + preview of the current case, runs nothing
/demo next     # run the current case, then preview the next
/demo skip     # advance without running
/demo goto 4   # jump to a case
/demo status   # where we are
```

`/demo next` is the only form that touches the browser. Everything else previews.

## Environment (verified 2026-09-02)

| Thing | Value |
| --- | --- |
| Platform | `http://10.124.48.126:32002/` (NodePort 32002; `.124` and `.125` also serve it) |
| Login | `admin` / `changeme` |
| UI language | Chinese |
| Cluster | all 17 pods in ns `dac` Running |
| Domain TDBs | `10.124.48.91:8989–8995` (7 domains), `:8997` wwybsj, `:8996` archaeology papers test — all healthy, all hold data |
| wwybsj collection | 465 objects, registration numbers 1–465 with no gaps |

**The in-cluster `tdb` service is empty.** `tdb.dac.svc:8080` has the full schema
and zero rows — `search_document`, `ontology_fact`, `entity`,
`domain_stream_binding` all 0. Every answer in this demo comes from the external
gateways on `10.124.48.91`. Do not point at the in-cluster TDB pod as the source
of anything.

## Run of show

| # | Case | Scenario | Status | ~Time |
| --- | --- | --- | --- | --- |
| 1 | LLM alone vs. DAC | 1.1 | ⚠️ needs decision | 3 min |
| 2 | **4 DACs collaborate** (汉代玉器) | 1.2 + 1-Goal-1 | ✅ verified today | 4 min |
| 3 | Ingestion changes the answer | 2 | ⚠️ needs decision | 6 min |
| 4 | New acquisition #472 | 3 | ✅ ready | 4 min |
| 5 | DAC builds a new DAC | 4 | 🟡 rehearse first | 4 min |
| 6 | Storage HLD + competitive | 5 | ❌ blocked | — |
| 7 | Architecture drawings | 6 | ❌ blocked | — |
| 8 | Circuit board data | 7 | ❌ blocked | — |

Cases 2 and 4 are solid and are the spine of the demo, and both were verified
against the live platform today. If time collapses, run those two.

## Open decisions — these need you

1. **Case 1 — which paper?** Two papers were ingested into the archaeology test
   library on 08-30. Pick the one the base LLM should not know, and write the
   before/after question pair into `cases/01-llm-vs-dac.md`. Without this, Case 1
   has no contrast to show.
2. **Case 3 — which S3 prefix?** The pipeline needs a source that is *not yet
   ingested*. Re-running the 08-30 prefix ingests nothing and cannot change any
   answer. Name a fresh prefix.
3. **Cases 6–8 — cut or rebuild?** All three lack data on this platform. My
   recommendation is to cut them and cover the storage/architecture/circuit story
   as roadmap. Say the word if you want option 2 in `cases/06-storage-hld.md`
   instead (web-sourced competitive analysis — demoable today, but it is web
   research, not DAC knowledge).

## Multi-agent routing — how to actually get it

**Fan-out works.** Verified live 2026-09-02: a four-part question produced
`mode=multi_root, 任务数=4`, dispatched in parallel to Wwybsj-TDB-Agent,
Archeology-Papers-Test-TDB-Agent, History-TDB-Agent and
Anthropology-sociology-TDB-Agent, each running its own skill, then synthesised
into one answer. That is Scenario 1's "more than 3 DACs" goal, met.

**The lever is question phrasing, not configuration.** The planner emits
`needs_split` per question:

- Numbered parts + 「请分别说明」, each part belonging to a different domain →
  `needs_split=true`, one task per domain, `multi_root`.
- The same subject written as one flowing paragraph → `needs_split=false`,
  `single_root`, one agent. The scenario document's original 汉代玉器 wording
  does exactly this — it was rewritten in Case 2 for that reason.

**The old watch-all problem is fixed.** All domain agents carry
`SKILL_SYNC_WATCH_ALL=false` with exactly one skill in `SKILLS`, applied
fleet-wide at the 2026-09-01T16:17:22Z restart. Candidates now report honestly
(`can_handle:false, can_contribute:true` for agents outside their domain)
instead of every agent claiming everything at 0.98 confidence. Routing also
picks the *right* root now — pre-fix traces sent museum questions to the papers
test agent.

Traces from before that restart still show the old behaviour. Don't use them to
judge current capability, and don't demo from them.

## Known risks

**Never navigate or reload during a run.** An interrupted run is lost completely
— it does not persist and will not appear in history afterwards. Confirmed
today: the agent finished its work server-side, and the run still vanished.

**Runs are slow.** Single-agent 40–120 s; the 4-agent multi_root run took ~3.5–4
minutes; the wwybsj build 121 s. The routing plan renders in the first ~60 s, so
narrate that while the answers come in.

**The retry loop may not appear.** Scenario 1 asks to show the eval-retry loop.
Successful runs finish in one attempt (`尝试次数 1`); the only multi-attempt
traces in the history are *failures* (`local_skill_declined`, 3 attempts). There
is no reliable way to show a healthy multi-iteration loop on demand. Either drop
that goal or show it from the 08-31 failure trace and explain what the loop was
doing.

**Rehearsal residue in the live TDB.** Registration numbers 466, 467, 468, 470,
471, 480, 490, 500 and 520 were inserted by earlier rehearsals. This is why
Case 4 uses **472** rather than the 466 in the scenario document. Verified free:
469, 472–476, 600, 666. Every rehearsal of Case 4 burns one — check before the
demo and update the case file.

## Fallbacks

Every past run is replayable at `/?run_id=<id>` with its full trace. If a live
run fails, open the fallback listed in the case file rather than retrying.
Recorded fallbacks:

- Case 2 → `cc3f7832-dba5-4c7c-b3e1-f34f3852040d` (4-agent multi_root, verified 09-02)
- Case 2 (short) → `8d5d0b61-0d97-4fd6-aa05-30c2e268586a` (2-agent multi_root)
- Case 4 → `91f28a01-2205-4efd-8647-bc146abae137` (item 0520 built, 121 s)
