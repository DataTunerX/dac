# Case 1 — LLM alone vs. DAC (the deterministic contrast)

- **Scenario:** 1.1 Deterministic
- **Status:** ⚠️ NEEDS ONE DECISION (which paper) — see Open item
- **Runtime:** ~3 min
- **Screen:** chat at `/`

## What this proves

A plain LLM answers from training data and misses recent work. The same question
against DAC returns the newly ingested paper, with citations. The difference is
the ingested corpus, not a better model.

## Talk track (preview card)

> Same question, two answers. First the model on its own — fluent, but it stops
> at its training cutoff. Then DAC, which reads the paper we ingested last week
> and cites it. Watch the routing trace underneath: the platform decides which
> domain owns the question before anyone answers.

## Steps

1. Ask the control question in a fresh chat.
2. Point at the answer: no mention of the recent paper.
3. Ask the DAC-routed question.
4. Expand **已思考** → show `RoutingAgent · route_plan_with_capability_check`.
5. Point at the citation naming the ingested source.

## Open item — resolve before the demo

The archeology papers test library (`:8996`) already holds 2 papers ingested
2026-08-30 from `s3://archaeology-source/papers/ActaAnthropologicaSinica/`.
Decide which of these is the "recent paper" the base LLM should not know, and
write the exact question pair here. The 09-01 rehearsal used a zoology question
that resolved to `web_fetch`, i.e. the open web — that is NOT this case and will
undercut the point.

## Fallback

None yet — this case has no clean rehearsal run to fall back to.
