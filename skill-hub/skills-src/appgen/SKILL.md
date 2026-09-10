---
name: appgen
description: Create and verify a new DAC skill and the skill agent that runs it. Use when the user asks to build, generate, scaffold or publish a new skill, capability or agent — for example "make a skill that converts currencies" or "create an agent for X". Publishes the skill package, creates the matching DataAgentContainer, then verifies the skill is loaded by a reachable agent before reporting success.
---

# AppGen

Turn a described capability into a working DAC skill **and** the agent that runs
it. Three steps, in order: publish the skill, create the agent that loads it,
then verify the published package and live agent.

Both steps are needed. Publishing a skill only makes it *available* — agents
load skills from an explicit list, so a published skill with no agent is
unreachable.

## When to use

- "create a skill that …", "build me an agent that …", "add a capability for …"
- The user describes something DAC cannot currently do and wants it to exist

Do **not** use this to answer a domain question. If the user is asking about
archaeology, geo-environment, museum collections and so on, that is a job for
the existing domain agents, not a reason to generate a new skill.

## Step 1 — publish the skill

```bash
python3 scripts/create_skill.py \
  --name currency-convert \
  --description "Convert an amount between two currencies using published rates." \
  --detail-file body.md
```

`--script helper.py` (repeatable) ships extra files under `scripts/`.
`--overwrite` replaces a skill of the same name; without it an existing name is
an error, so you never clobber someone's skill by accident.

### Writing the description — this matters more than it looks

`--description` becomes the agent card, and **the agent card is the only thing
the routing capability check reasons over**. It never inspects the skill's files
or data. A vague description produces an agent that mis-claims work it cannot do.

- Say what the skill answers or does, concretely.
- Name the boundary too: what it does *not* cover, and what it needs from the
  user. An agent whose card admits a limit will decline correctly instead of
  guessing.
- One or two sentences. It is copied verbatim into the card.

Good: `Convert an amount between two currencies using published daily rates.
Does not provide historical series or financial advice.`

Poor: `Handles currency things.`

## Step 2 — create and verify the agent

```bash
python3 scripts/create_agent.py --skill currency-convert
```

`create_agent.py` does not report success immediately after creating the
DataAgentContainer. It waits up to 120 seconds and requires all of the following:

1. skill-hub lists the requested skill version;
2. the DataAgentContainer binds that exact namespace/name/version;
3. its status contains `Available=True` and an endpoint;
4. the endpoint serves `/.well-known/agent-card.json` and advertises the skill.

Use `--verify-timeout` and `--verify-interval` only when the cluster needs a
different bounded rollout window. To re-check an existing deployment without
creating or updating it:

```bash
python3 scripts/verify_deployment.py \
  --skill currency-convert \
  --agent-name currency-convert-agent \
  --skill-version 1.0.0
```

Defaults to agent name `<skill>-agent`. Options: `--agent-name`,
`--description`, `--expert-llm`, `--planner-llm`, `--max-steps`.

The agent is created with an explicit `skillPolicy`, which also stops it
subscribing to the whole skill-hub namespace — so it advertises only its own
skill when routing broadcasts a capability check.

Creating the DataAgentContainer needs Kubernetes permission on
`dataagentcontainers`. If the script reports it has no ServiceAccount token or
is forbidden, publish the skill anyway and tell the user to create the agent
from the DAC UI (智能体 → new agent, dacType skill) — the skill is already in
the hub and just needs binding.

## Reporting back

Both scripts print one JSON object. Report:

- the skill name, version and namespace
- the agent name and whether it was created or updated
- the verification object: published version, `Available` state, runtime
  endpoint, and `skill_loaded`
- if either step failed, the `error` field verbatim — do not paper over it

## Rules

- Never invent what the new skill does. If the request is too vague to write a
  precise description, ask for the missing detail first.
- Names are lowercase letters, digits and dashes; they become both a hub slug
  and a Kubernetes object name.
- Do not put credentials in a skill. A skill package is published to the hub and
  committed to the repo; secrets belong in the deployment as environment.
- Report exactly what was created. Do not claim an agent is ready when only the
  skill was published.
- Do not report the workflow complete unless deployment verification returns
  `ok: true`. A timeout means the resources may exist but are not proven ready;
  report that distinction and the last verification error.
