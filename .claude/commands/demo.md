---
description: Run the DAC demo one case at a time — preview, then execute on "next"
---

Drive the DAC demo defined in `demo/`. Argument: `$ARGUMENTS`

## State

`demo/state.json` holds `current` (the case number that has NOT yet run) and the
case table. Read it at the start of every invocation. Write it back only when the
position actually changes.

## Subcommands

| Argument | Do this |
| --- | --- |
| *(empty)* | Print the agenda, then the **preview card** for `current`. Execute nothing. |
| `next` | Execute case `current`, then set `current += 1` and print the next preview card. |
| `goto N` | Set `current = N`, print its preview card. Execute nothing. |
| `skip` | `current += 1`, print the new preview card. Execute nothing. |
| `back` | `current -= 1`, print its preview card. Execute nothing. |
| `status` | Print position and per-case status. Execute nothing. |
| `reset` | `current = 1`, print its preview card. Execute nothing. |

**Only `next` executes anything.** Every other form is preview-only. This matters:
the operator is standing in front of an audience and a surprise browser action is
worse than a missing one.

## Printing a preview card

Read the case file and render, in this shape — terse enough to read aloud:

```
━━ NEXT: Case <n> of 8 · <title> ━━
Scenario <x> · <status> · ~<runtime>
Screen: <screen>

<the "Talk track" block, verbatim>

I will: <the Steps, compressed to one line each>

Type /demo next to run it.
```

If the case status is `blocked`, print the card, state in one line why it is
blocked, and say it will not be executed — then advise `/demo skip`.

## Executing a case (`next`)

1. Re-read the case file. Follow its Steps exactly.
2. Drive the browser with the Playwright MCP tools. Platform:
   `http://10.124.48.126:32002/`, login `admin` / `changeme`. If the session has
   dropped, log in again before starting.
3. For a chat step: open a **fresh** chat (`开启新对话`) unless the case says to
   continue an existing one. Paste the prompt verbatim from the case file — never
   paraphrase, and never fix its typos.
4. Answers take 40–120 s. Poll with snapshots. While waiting, say what to look at
   on screen; do not fill the silence with narration the operator has to talk over.
5. When it completes, report only: what came back, and whether the case's stated
   proof landed. Quote the specific trace values (routing mode, selected agent,
   skill, attempts, citations) — those are the evidence.
6. If a case has an **Open item** that is still unresolved, do not improvise a
   substitute. Stop, say which decision is missing, and hold at that case without
   advancing.

## If a case fails live

Do not retry silently and do not narrate the failure at length. Say in one line
what failed, then offer the case's **Fallback** run_id if it has one. Advance only
when the operator says so.

## Never

- Never run more than one case per `next`.
- Never execute a `blocked` case.
- Never re-run a case that would destroy its own "before" state (Case 4's
  artifact number, Case 3's un-ingested source) without saying so first and
  getting a fresh value.
