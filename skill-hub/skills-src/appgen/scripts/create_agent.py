#!/usr/bin/env python3
"""Create the DataAgentContainer that loads a published skill.

  python3 create_agent.py --skill weather-report [--agent-name weather-agent]

Publishing a skill only makes it available: agents load skills from an
explicit list, so without an agent nothing can call it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from appgen_common import (  # noqa: E402
    AGENT_NAMESPACE, SKILL_NAMESPACE, AppGenError, k8s_request, skill_exists, validate_name)

API = "/apis/dac.dac.io/v1alpha1/namespaces/{ns}/dataagentcontainers"


def card_name(agent: str) -> str:
    """History-TDB-Agent style: title-case the dashed parts."""
    return "-".join(p[:1].upper() + p[1:] for p in agent.split("-") if p)


def build_manifest(agent: str, skill: str, version: str, description: str,
                   expert_llm: str, planner_llm: str, max_steps: str, max_loops: str) -> dict:
    return {
        "apiVersion": "dac.dac.io/v1alpha1",
        "kind": "DataAgentContainer",
        "metadata": {"name": agent, "namespace": AGENT_NAMESPACE,
                     "labels": {"dac.io/created-by": "appgen"}},
        "spec": {
            "dacType": "skill",
            "agentCard": {
                "name": card_name(agent),
                "description": description,
                # The card is the only thing the capability check reasons over,
                # so the skill entry has to carry a usable description.
                "skills": [{"id": skill, "name": skill, "description": description,
                            "tags": [], "examples": []}],
            },
            # An explicit policy also stops the agent subscribing to the whole
            # hub namespace, so it claims only its own domain when routing asks.
            "skillPolicy": {"skills": [{"name": skill, "namespace": SKILL_NAMESPACE,
                                        "version": version}]},
            "dataPolicy": {"dataSourceType": "", "semanticGroupID": "", "sourceNameSelector": []},
            "model": {"expertLLM": expert_llm, "plannerLLM": planner_llm},
            "expertAgentMaxSteps": max_steps,
            "orchestratorAgentMaxLoops": max_loops,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", required=True)
    ap.add_argument("--agent-name", default="", help="defaults to <skill>-agent")
    ap.add_argument("--description", default="", help="defaults to the skill's own description")
    ap.add_argument("--skill-version", default="1.0.0")
    ap.add_argument("--expert-llm", default=os.getenv("APPGEN_DEFAULT_LLM", "gpt-5.6-luna"))
    ap.add_argument("--planner-llm", default=os.getenv("APPGEN_DEFAULT_LLM", "gpt-5.6-luna"))
    ap.add_argument("--max-steps", default="30")
    ap.add_argument("--max-loops", default="2")
    args = ap.parse_args()

    try:
        skill = validate_name(args.skill, "skill name")
        agent = validate_name(args.agent_name or f"{skill}-agent", "agent name")

        if not skill_exists(skill):
            raise AppGenError(
                f"skill {skill!r} is not published in namespace {SKILL_NAMESPACE}; "
                "run create_skill.py first"
            )

        description = args.description.strip() or f"Agent that runs the {skill} skill."
        manifest = build_manifest(agent, skill, args.skill_version, description,
                                  args.expert_llm, args.planner_llm,
                                  args.max_steps, args.max_loops)

        path = API.format(ns=AGENT_NAMESPACE)
        try:
            k8s_request(path, method="POST", payload=manifest)
            created = True
        except AppGenError as exc:
            if "409" not in str(exc):
                raise
            # Already there: make it match what was asked for rather than fail.
            existing = k8s_request(f"{path}/{agent}")
            manifest["metadata"]["resourceVersion"] = existing["metadata"]["resourceVersion"]
            k8s_request(f"{path}/{agent}", method="PUT", payload=manifest)
            created = False
    except AppGenError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    print(json.dumps({
        "ok": True,
        "agent": agent,
        "namespace": AGENT_NAMESPACE,
        "skill": skill,
        "action": "created" if created else "updated",
        "note": "the operator builds the Deployment; it takes a few seconds to become ready",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
