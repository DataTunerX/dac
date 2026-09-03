# Case 5 — DAC builds a new DAC (label-writing service)

- **Scenario:** 4 (New application generation)
- **Status:** 🟡 LIKELY READY — rehearse once before the demo
- **Runtime:** generation ~2–3 min · use ~60 s
- **Screen:** chat at `/`

## What this proves

The platform extends itself. Ask for a capability that does not exist; DAC writes
the skill, publishes it to skill-hub, and creates the DataAgentContainer that
loads it. The new agent then joins capability routing like any other — and gets
picked, by name, on the next question.

## Talk track (preview card)

> Everything so far used capabilities we shipped. This one doesn't exist yet.
> I'm going to ask for a service that writes museum object labels — and the
> platform will write the skill, publish it, and stand up the agent that runs it.
> Then I'll ask it for a label, and routing will find something that was not
> there five minutes ago.

## Step 1 — generate

```
开发部署一个新的服务，能够根据馆藏的要求产生馆藏物标（label）。物标需要包含：藏品名称、年代、质地、尺寸、登记号，以及一段面向观众的说明文字。
```

Watch: routing → **Appgen-Agent**, then the skill publish and the DAC creation
reported back.

## Step 2 — verify it exists

Show the new agent on **智能体** (`/agents`) — switch the type filter off
业务智能体, the generated agent is a **skill** DAC in namespace `default`.

## Step 3 — use it

```
给006号藏品写一个馆藏物标
```

Object 006 is `渤海绿釉莲纹柱础护圈` (渤海 698–926, 陶器) — verified present in
the collection.

## Why this should work

`appgen` is published in skill-hub and `appgen-agent` is running. A previous run
of the same path produced `currency-convert-agent`, which is still in the cluster
— that is the artifact of a successful earlier generation.

## Rehearse this one

It is the only READY-ish case with no confirmed end-to-end run in the visible
history. Run it once against a throwaway capability name before the demo, then
delete the agent, so you know the publish + CR creation path is healthy today.

## Watch out

The generated skill's **description becomes its agent card**, and the card is the
only thing routing reasons over. If the generated description is vague, Step 3
may route somewhere else. If that happens, name it explicitly:
`用<新agent名>给006号藏品写一个馆藏物标`.
