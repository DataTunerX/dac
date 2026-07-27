---
name: dynamic-skill-demo
description: "Prove that Skill Hub distribution and Skill Agent hot loading work by running a newly published script and returning a recognizable JSON receipt. Use when testing a new skill push, automatic agent download, live skill reload, or AgentCard refresh without restarting the agent."
---

# Dynamic skill demo

Run the bundled `scripts/dynamic_demo.py` whenever the user asks to demonstrate
dynamic skill delivery or confirm that this skill is executable.

## Procedure

1. Execute the script with Python using its absolute `script_path` from the
   loaded skill metadata.
2. Pass the user's text with `--message` when supplied.
3. Return the JSON receipt exactly, then state that the receipt was produced by
   the dynamically loaded `dynamic-skill-demo` version `1.0.0`.

```bash
python3 <skill_dir>/scripts/dynamic_demo.py --message "hot reload works"
```

The command must emit one JSON object containing `dynamic_skill_loaded: true`.
Treat a non-zero exit or malformed output as a failed demonstration; do not
claim success without the receipt.
