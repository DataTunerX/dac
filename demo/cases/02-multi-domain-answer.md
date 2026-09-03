# Case 2 — Four DACs collaborate on one question (汉代玉器)

- **Scenario:** 1.2 Comprehensive answering — and it satisfies Scenario 1 Goal 1
- **Status:** ✅ READY — verified live 2026-09-02
- **Runtime:** ~3.5–4 min end to end
- **Screen:** chat at `/`

## What this proves

One museum question is **split into four tasks and dispatched to four different
DACs in parallel**, each running its own domain skill against its own TDB. The
platform then synthesises one graded answer that separates registered fact from
comparable material from textual authority from social theory.

Verified run `cc3f7832-dba5-4c7c-b3e1-f34f3852040d`:

| Task | DAC | Skill | Time | Chars |
| --- | --- | --- | --- | --- |
| 1 馆藏登记事实 | Wwybsj-TDB-Agent | `tdb-wwybsj-answering` | 52 s | 3313 |
| 2 考古学证据 | Archeology-Papers-Test-TDB-Agent | `tdb-archeology-papers-test-qa` | 28 s | 878 |
| 3 历史文献依据 | History-TDB-Agent | `tdb-history-qa` | — | 3639 |
| 4 人类学/社会学解释 | Anthropology-sociology-TDB-Agent | `tdb-anthropology-sociology-qa` | 83 s | 3475 |

Final synthesis: **4382 chars**, `mode=multi_root`, `状态 done`.

## Talk track (preview card)

> This is the question a curator actually has, and no single expert can answer
> it. Watch the platform take it apart: our own collection records, the
> excavation literature, the Han ritual texts, and the sociology of ancestor
> worship — four different knowledge bases, four different agents, dispatched in
> parallel. Then it puts the answer back together and tells you which parts it
> cannot prove.

## Prompt (paste verbatim — the phrasing is load-bearing)

```
汉代玉器：身体、死亡与身份。请分别说明以下四部分：（1）本馆汉代玉蝉、玉衣片、玉璧的馆藏登记事实；（2）同类汉墓玉器的考古学证据；（3）秦汉丧葬礼制中饭含与玉衣制度的历史文献依据；（4）死者祭拜与家族纽带、集体记忆的人类学与社会学解释。
```

**Do not paraphrase this into flowing prose.** The four numbered parts and
「请分别说明」 are what make the planner return `needs_split=true, 任务数=4`. The
document's original one-paragraph version of this question resolves to
`single_root` with one agent — same subject, one quarter of the demo.

## Steps

1. Paste the prompt, send. Do **not** navigate or reload until it finishes.
2. Expand **已思考**. Narrate `multi_root_plan_reason` — read out `任务数=4`,
   `needs_split=true`, and the `why_agent` justification per task.
3. As each finishes, point at `multi_root_task_finished` naming the four agents.
4. On the final answer, show the evidence layering and the 不能确证 boundary.

## Verified data

All four objects exist in the live wwybsj TDB (`:8997`):

| 登记号 | 名称 |
| --- | --- |
| 0349 | 汉玉蝉 |
| 0265 | 汉玉衣片 |
| 0394 | 西汉玉衣片 |
| 0244 | 汉代玉璧 |

## Watch out

- **Never reload during a run.** A run interrupted mid-stream is lost entirely —
  it does not appear in history afterwards. Confirmed the hard way today.
- ~4 minutes is a long silence. Use the routing plan as the narration: it is
  fully rendered within the first ~60 s, well before any answer arrives.
- Task 2 routes to **Archeology-Papers-Test**-TDB-Agent (the isolated papers
  library), not a general archaeology agent. Its answer is the shortest (878
  chars) because that library only holds the papers ingested on 08-30.

## Fallback

`/?run_id=cc3f7832-dba5-4c7c-b3e1-f34f3852040d` — the verified 4-agent run above.
Also `/?run_id=8d5d0b61-0d97-4fd6-aa05-30c2e268586a` — a 2-agent multi_root run
(archaeology + geo-environment) if you want a shorter example.
