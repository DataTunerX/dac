# Case 6 — Storage: HLD + competitive analysis

- **Scenario:** 5.1 and 5.2
- **Status:** ❌ BLOCKED — do not put this in the run-of-show as-is
- **Screen:** chat at `/`

## Why it is blocked

The 08-31 rehearsal of exactly this failed:

```
生成一个competitive analysis report for 下面几个产品：Dorado 6000，NetApp…
→ SkillAgent · sd_skill_finished
   状态 fail · 技能状态 no_suitable_skill · 原因码 local_skill_declined
   尝试次数 3
```

Run: `/?run_id=31f79175-4278-4573-b9ac-4688019dee49`

The planner tried three times and correctly declined: **there is no storage
skill and no storage corpus on this platform.** Nothing in skill-hub covers
storage products, HLD authoring, or competitive analysis, and no storage DAC
exists. The two RFI rehearsals the same evening are the same story.

## What it would take

One of:

1. **Ingest a storage corpus** — datasheets, spec docs, RFI responses — into a
   new domain via the same 入库 pipeline as Case 3, then generate a storage
   skill+agent with appgen (Case 5). This is the honest version and is not a
   one-evening job.
2. **Scope it down to what works today.** The failure was *no local skill*, not
   *no capability* — `web_fetch` succeeded on a comparable task on 09-01. A
   competitive analysis explicitly sourced from vendor pages is demoable now,
   but it is a web-research demo, not a DAC-knowledge demo, and it will not
   produce the ~10-page document 5.1 asks for.

## Recommendation

Cut both 5.1 and 5.2 from the demo, or run option 2 and say plainly that the
storage corpus is not loaded yet. Attempting 5.2 as written will reproduce the
`no_suitable_skill` failure in front of the audience.

Decision needed from you — see `demo/README.md` → Open decisions.
