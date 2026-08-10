"""Context compaction for long skill ReAct runs.

## Problem

``SkillRunner.run`` appends every assistant and tool message to an in-memory
list and resends the full history on each step. When that history approaches or
exceeds the model context window, providers reject the request (or silently
truncate). Without compaction, the run fails with no recovery.

## Solution

Compaction is **enabled by default** with a 200K context window.
Set ``SKILL_SDK_COMPACTION_ENABLED=false`` to opt out, or
``SKILL_SDK_CONTEXT_WINDOW=128000`` to override the window size.

Mechanisms:

1. **Threshold compaction** — before each LLM invoke, if
   ``context_tokens > context_window - reserve_tokens``, summarize older turns
   with a dedicated LLM call and keep approximately ``keep_recent_tokens`` of
   recent messages verbatim.
2. **Overflow recovery** — if the provider raises a context-overflow error,
   compact once and retry the same step. A second overflow returns
   ``status=context_overflow``.
3. **Silent overflow** — if usage reports input above the window on a completed
   response, compact without retrying.

## Defaults

| Setting | Default | Env var |
|---------|---------|---------|
| ``enabled`` | ``true`` | ``SKILL_SDK_COMPACTION_ENABLED`` |
| ``context_window`` | ``200000`` | ``SKILL_SDK_CONTEXT_WINDOW`` |
| ``reserve_tokens`` | ``16384`` | — |
| ``keep_recent_tokens`` | ``20000`` | — |

## Usage

### Default (enabled)

```python
from skill_sdk import SkillRunner

# Compaction is on by default — 200K window, auto-compact + overflow recovery.
runner = SkillRunner(llm)
```

### Disable

```python
runner = SkillRunner(llm, compaction=None)
```

### Custom config

```python
from skill_sdk import SkillRunner, CompactionConfig, CompactionSettings

runner = SkillRunner(
    llm,
    compaction=CompactionConfig(
        context_window=128_000,
        settings=CompactionSettings(),
    ),
)
```

### Environment variable overrides

```bash
# Disable compaction
SKILL_SDK_COMPACTION_ENABLED=false python ...

# Set a custom context window
SKILL_SDK_CONTEXT_WINDOW=32768 python ...
```

After compaction the model sees:

```
[SystemMessage ...]
[HumanMessage: structured summary]
[recent Human / AI / Tool messages]
```

## Cut rules

- Valid cut points: human and assistant messages (including injected summaries).
- Never cut on ``ToolMessage`` (must stay with the preceding tool-call assistant).
- If a single turn exceeds the keep budget, the turn is split: history summary +
  turn-prefix summary, merged with ``---``.

## Hooks

``CompactionConfig.on_before_compact`` may cancel or supply a custom summary.
``CompactionConfig.on_compact`` fires after a successful compaction.

## Out of scope

- Cross-run disk persistence of compaction boundaries (skill runs are ephemeral).
- Branch / tree navigation summaries.
- Per-tool output truncation (already handled by existing tool plugins).
"""
