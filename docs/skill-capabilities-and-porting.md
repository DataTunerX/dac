# Skill Capabilities and Porting Guide

This project has a skill runtime made of three main pieces:

- `skill_sdk`: loads skill zip packages and runs a ReAct loop over the selected skill.
- `skill-hub`: indexes and serves skill zip packages over HTTP.
- `skill-agent`: downloads selected skills from `skill-hub`, loads them, advertises them as A2A capabilities, and executes them for user requests.

## Runtime Flow

1. Put skill zip files in `skill-hub/skills/`.
2. Build/deploy the `skill-hub` image. The image copies those zip files into `/app/skills/`.
3. Configure `bizSkillAgent.config.skills` in `installer/dac/values.yaml` or an override values file.
4. On startup, `skill-agent` downloads `{name}.zip` from `skill-hub` into `/app/skills/`.
5. `skill-agent` loads every zip with `SkillLoader`.
6. For each request, `SkillRunner` first chooses a matching skill by `name` and `description`, then runs the selected skill using its `SKILL.md` instructions, bundled scripts/resources, and built-in tools.

Relevant files:

- `skill_sdk/skill_sdk/skill/loader.py`
- `skill_sdk/skill_sdk/skill/runner.py`
- `skill-hub/skill_hub/server.py`
- `skill-agent/agent/skill_agent.py`
- `installer/dac/templates/biz-skill-agent-deployment.yaml`
- `installer/dac/templates/skill-hub-deployment.yaml`

## How Other Agents Use Skills

There are three usage patterns.

### 1. As a Standalone A2A Agent

`skill-agent` is the normal shared skill entry point.

At startup it:

1. downloads the configured zip packages from `skill-hub`,
2. loads them into one process-wide `SkillRunner`,
3. builds a dynamic `AgentCard`,
4. registers that card into Redis through the agent registry heartbeat.

The dynamic card contains:

- `description`: a summary of all loaded skills,
- `skills`: one `AgentSkill` entry per loaded skill.

That means other agents do not need to know zip internals. They see an A2A agent named `SkillAgent` whose card advertises capabilities such as `web_fetch`, `extract_pdf`, or `code_execution`.

When another agent sends a normal A2A request to `SkillAgent`, the executor calls:

```text
SkillRunner.plan_and_run(query=...)
```

The runner then chooses the best loaded skill internally.

Relevant files:

- `skill-agent/agent/server.py`
- `skill-agent/agent/skill_agent.py`

### 2. Through Routing / Capability Check

The routing layer can broadcast a capability-check request to registered agents.

For `SkillAgent`, this uses metadata:

```json
{
  "message_type": "capability_check"
}
```

`SkillAgent` answers with JSON saying whether its loaded skill inventory can handle the query, plus confidence and reason. If it can handle the task, the router can route the user request to `SkillAgent` as a normal A2A target.

Relevant files:

- `routing-agent/routing_agent/server.py`
- `skill-agent/agent/skill_agent.py`

### 3. Embedded LocalSkill Inside Some Agents

The orchestrator has a second path called `LocalSkill`.

Instead of calling the standalone `SkillAgent` over HTTP, the orchestrator can load skills into its own process and append a synthetic agent card:

```text
name: LocalSkill
url: local://skill-runner
```

When the planner selects `LocalSkill`, the orchestrator intercepts the task and directly calls its local:

```text
SkillRunner.plan_and_run(query=task.description)
```

This avoids an A2A network hop, but the skills are private to that orchestrator process unless also served through `skill-agent`.

For a normal DD/SG DAC with explicit local attachments, the execution engine
sets `LOCAL_SKILL_FORCE_ATTACHED=true`. The orchestrator bypasses the external
agent-routing planner so execution stays inside that DAC. With exactly one
attachment it calls `SkillRunner.run(...)` directly; with multiple attachments
the in-process `SkillRunner.plan_and_run(...)` selects the matching attached
skill. No attached skill is executed through a remote A2A agent.

Relevant files:

- `orchestrator-agent/orchestrator_agent/orchestrator_agent_semantic_domain.py`

### 4. Code-Agent Internal Use

`code-agent` has a specialized internal `SkillRunner` path for the `read-code` skill.

It uses `read-code` for code snippet recall with grep, glob, LSP, and `readline_in_range`. This is not the general shared skill mechanism. It is a private implementation detail of `code-agent`'s code-reading workflow.

Relevant files:

- `code-agent/agent/skill_runner_service.py`
- `code-agent/agent/tools/skill_read_code_recall.py`
- `code-agent/agent/code_agent.py`

### Practical Rule

For a new general-purpose skill, publish it through `skill-hub` and load it in `skill-agent`.

Use embedded SkillRunner only when the skill is tightly coupled to one agent's local state, local filesystem, cloned repo, or language-server setup.

## Skill Package Format

A skill zip must contain a skill root directory, either at the zip root or under one top-level folder.

Required files:

```text
my-skill/
  _meta.json
  SKILL.md
```

Optional files:

```text
my-skill/
  scripts/
    helper.py
    helper.sh
    helper.js
  assets/
  references/
  hooks/
```

`_meta.json` must contain at least:

```json
{
  "version": "1.0.0"
}
```

`SKILL.md` must start with YAML frontmatter:

```markdown
---
name: my-skill
description: Short trigger-oriented description used by the planner.
---

# My Skill

Detailed instructions for how the runner should solve the task.
```

The loader records:

- `name`, `description`, and markdown body from `SKILL.md`.
- `version` from `_meta.json`.
- executable files under `scripts/`.
- non-empty top-level resource directories such as `assets/` or `references/`.

Script interpreters are inferred for `.py`, `.sh`, `.js`, `.ts`, `.rb`, `.pl`, and `.php`, or from shebangs.

## Built-In Execution Capabilities

The runner always exposes:

- `plan_cmd`: execute a local command with policy checks, timeout, concurrency limit, and destructive-command blocking.
- `readline_in_range`: read specific line ranges from local files.
- `finish`: return the final answer.

When enabled/injected, it can also expose:

- `code_exec`: LLM-generated Python execution in a constrained sandbox, used by the `code_execution` skill.
- auto-discovered `ToolPlugin` tools from `skill_sdk.tool`, including:
  - `extract_pdf`
  - `web_fetch`
  - `tavily_search`
  - `tavily_extract`
  - `glob`
  - `grep`
  - `lsp`
  - `readline_in_range`

Some tools require environment variables:

- Tavily search/extract: `TAVILY_API_KEY`, optional `TAVILY_BASE_URL`.
- PDF vision mode: `PDF_VISION_API_KEY` or provider-specific keys such as `DASHSCOPE_API_KEY` / `OPENAI_API_KEY`, plus `PDF_VISION_PROVIDER`, `PDF_VISION_MODEL`, and optional `PDF_VISION_BASE_URL`.
- LSP/code-reading: language servers must exist in the image/runtime, for example `gopls`, `clangd`, `rust-analyzer`, `jdtls`, `vtsls`, or `basedpyright-langserver`.

## Current Bundled Skill Catalog

The `skill-hub/skills/` directory currently contains:

| Skill | Version | Capability |
| --- | --- | --- |
| `base64tool` | `1.0.0` | Base64 encode/decode text. |
| `bundle-hash` | `1.0.0` | Combined sha256 over a directory. |
| `code_execution` | `1.0.0` | Python sandbox execution for numerical/data tasks. |
| `colorconv` | `1.0.0` | Convert hex colors and RGB. |
| `extract_pdf` | `1.0.0` | Extract text/images from local or remote PDFs. |
| `file-search` | `1.0.0` | File name/content search using `fd` and `rg`. |
| `github` | `1.0.0` | GitHub operations through the `gh` CLI. |
| `hashgen` | `1.0.0` | md5/sha1/sha256 for strings/files. |
| `jsonfmt` | `1.0.0` | Validate and pretty-print JSON. |
| `pwdgen` | `1.0.0` | Generate random passwords. |
| `read-code` | `1.0.0` | Search and read local code using grep/glob/LSP. |
| `regextest` | `1.0.0` | Test regexes and report matches/groups. |
| `tavily-search` | `1.0.0` | Web search and URL extraction through Tavily. |
| `timestamp` | `1.0.0` | Convert epoch seconds and ISO datetimes. |
| `urlparse` | `1.0.0` | Decompose URLs into components. |
| `uuidgen` | `1.0.0` | Generate UUID v4 values. |
| `weather` | `1.0.0` | Current weather and forecasts. |
| `web_fetch` | `1.0.0` | Fetch public web pages with SSRF protection and extraction. |
| `wordcount` | `1.0.0` | Count words, lines, and characters. |

Default chart configuration currently loads:

```yaml
bizSkillAgent:
  config:
    skills:
      - weather
      - web_fetch
      - tavily-search
      - code_execution
      - extract_pdf
```

So other bundled skills exist in `skill-hub`, but will not be loaded by `skill-agent` unless listed in `bizSkillAgent.config.skills`.

## Porting a Claude or OpenClaw Skill

Use this decision tree.

### 1. Instruction-Only Skill

If the source skill is mainly instructions, references, examples, or workflow policy:

1. Keep the original markdown body.
2. Add DAC-compatible frontmatter with `name` and `description`.
3. Add `_meta.json`.
4. Put supporting docs under `references/` or `assets/`.
5. Zip it and add it to `skill-hub/skills/`.
6. Add its `name` to `bizSkillAgent.config.skills`.

This is the easiest path for Claude-style skills that are effectively specialized prompt/instruction packs.

### 2. Skill with Local Helper Scripts

If the source skill has shell/Python/Node helpers:

1. Put helpers under `scripts/`.
2. Mention exact invocation patterns in `SKILL.md`.
3. Make sure dependencies exist in the `skill-agent` image.
4. If helpers rely on local files, put those files under `assets/` or `references/`.

The runner will show the LLM discovered scripts and suggested invocations.

### 3. Skill Requiring an External API

If the source skill calls an API:

1. Prefer a script wrapper under `scripts/` for simple APIs.
2. Prefer a `ToolPlugin` in `skill_sdk/skill_sdk/tool/` for reusable structured tools.
3. Add required environment variables to the Helm chart.
4. Document missing-key behavior in `SKILL.md`.

Existing examples: `tavily-search`, `web_fetch`, and `extract_pdf`.

### 4. Skill Requiring MCP or Browser Automation

This platform's `skill-agent` does not directly run Codex/Claude MCP tool calls. It runs local commands and Python `ToolPlugin` tools.

For a Claude/OpenClaw skill that says "use Playwright MCP", "use browser connector", or "use app connector", choose one:

- Port the workflow to local scripts that use Playwright/Selenium inside the container.
- Implement a `ToolPlugin` that calls a service exposing the desired browser/API capability.
- Keep that workflow outside `skill-agent` and implement it as a dedicated A2A agent.

The local `.codex_skill_import/expense-report` skill is an example that would not port cleanly as-is, because it depends on Playwright MCP browser tools. It needs a browser-capable runtime or a dedicated agent/tool bridge.

### 5. Skill Requiring Subagents or Parallel Research

This runner does not expose subagent spawning to skills. Port by:

- using scripts that fan out internally,
- implementing a dedicated agent for the workflow, or
- simplifying the skill to sequential tool use.

The local `.codex_skill_import/domain-knowledge-builder` skill is mostly instruction-only plus web/research workflow. It can be ported as a DAC skill if you accept sequential execution through `web_fetch`/`tavily-search`, or it can become a stronger dedicated agent if true parallelism is required.

## Minimal Port Example

Create:

```text
skill-hub/skills-src/my-skill/
  _meta.json
  SKILL.md
  scripts/helper.py
  references/notes.md
```

Then zip:

```bash
cd skill-hub/skills-src
zip -r ../skills/my-skill-1.0.0.zip my-skill
```

Configure:

```yaml
bizSkillAgent:
  config:
    skills:
      - my-skill
```

Rebuild and push `skill-hub`, then restart `skill-agent` so it downloads the new zip.

## Porting Checklist

Before calling a port complete:

- `SKILL.md` starts with frontmatter containing `name` and `description`.
- `_meta.json` contains `version`.
- The zip does not contain unsafe paths such as `..`.
- `skill-hub` can list it via `/skills`.
- `skill-agent` has the skill name in `SKILLS`.
- Required CLI tools and language runtimes are installed in the image.
- Required API keys/env vars are configured in Helm.
- Destructive actions are avoided or require a separate controlled workflow.
- MCP-dependent behavior has been replaced with scripts, `ToolPlugin`s, or a dedicated agent.
