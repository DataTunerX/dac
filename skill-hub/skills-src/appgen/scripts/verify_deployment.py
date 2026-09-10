#!/usr/bin/env python3
"""Verify that a generated skill is published and its skill agent is live.

Checks, in order:
1. skill-hub lists the requested skill version;
2. the DataAgentContainer exists and binds that exact skill version;
3. the CR reports Available=True with an endpoint;
4. the endpoint serves an A2A AgentCard that advertises the skill.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from appgen_common import (  # noqa: E402
    AGENT_NAMESPACE,
    SKILL_NAMESPACE,
    AppGenError,
    find_skill,
    http_json,
    k8s_request,
    validate_name,
)

API = "/apis/dac.dac.io/v1alpha1/namespaces/{ns}/dataagentcontainers"
CARD_PATH = "/.well-known/agent-card.json"


def _published_skill(skill: str, version: str) -> dict:
    entry = find_skill(skill)
    if entry is None:
        raise AppGenError(
            f"skill {skill!r} is not published in namespace {SKILL_NAMESPACE}"
        )
    available = [str(item) for item in entry.get("available_versions") or []]
    published_version = str(entry.get("version") or "")
    if version and version != published_version and version not in available:
        raise AppGenError(
            f"skill {skill!r} version {version!r} is not published; "
            f"available versions: {available or [published_version]}"
        )
    return {
        "name": skill,
        "namespace": SKILL_NAMESPACE,
        "version": version or published_version,
        "published": True,
    }


def _bound_skill(resource: dict, skill: str, version: str) -> dict | None:
    refs = (((resource.get("spec") or {}).get("skillPolicy") or {}).get("skills") or [])
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        if ref.get("name") != skill or ref.get("namespace") != SKILL_NAMESPACE:
            continue
        if version and str(ref.get("version") or "") != version:
            continue
        return ref
    return None


def _is_available(resource: dict) -> bool:
    conditions = ((resource.get("status") or {}).get("conditions") or [])
    return any(
        isinstance(condition, dict)
        and condition.get("type") == "Available"
        and str(condition.get("status")).lower() == "true"
        for condition in conditions
    )


def _card_has_skill(card: dict, skill: str) -> bool:
    for item in card.get("skills") or []:
        if isinstance(item, dict) and (item.get("id") == skill or item.get("name") == skill):
            return True
    return False


def verify_once(skill: str, agent: str, version: str) -> dict:
    skill_result = _published_skill(skill, version)
    path = f"{API.format(ns=AGENT_NAMESPACE)}/{agent}"
    resource = k8s_request(path)

    if _bound_skill(resource, skill, skill_result["version"]) is None:
        raise AppGenError(
            f"agent {agent!r} exists but is not bound to "
            f"{SKILL_NAMESPACE}/{skill}@{skill_result['version']}"
        )
    if not _is_available(resource):
        conditions = ((resource.get("status") or {}).get("conditions") or [])
        raise AppGenError(
            f"agent {agent!r} is not Available yet; conditions={conditions}"
        )

    endpoint = (resource.get("status") or {}).get("endpoint") or {}
    address = str(endpoint.get("address") or "").strip()
    port = endpoint.get("port")
    if not address or not port:
        raise AppGenError(f"agent {agent!r} is Available but has no endpoint")

    card_url = f"http://{address}:{port}{CARD_PATH}"
    card = http_json(card_url, timeout=10)
    if not isinstance(card, dict) or not _card_has_skill(card, skill):
        advertised = [
            item.get("id") or item.get("name")
            for item in (card.get("skills") or [])
            if isinstance(item, dict)
        ] if isinstance(card, dict) else []
        raise AppGenError(
            f"agent {agent!r} is reachable but does not advertise skill {skill!r}; "
            f"advertised={advertised}"
        )

    return {
        "ok": True,
        "skill": skill_result,
        "agent": {
            "name": agent,
            "namespace": AGENT_NAMESPACE,
            "resource_created": True,
            "available": True,
            "endpoint": card_url,
            "skill_loaded": True,
            "card_name": card.get("name"),
        },
    }


def wait_for_deployment(skill: str, agent: str, version: str, *,
                        timeout: float = 120, interval: float = 3) -> dict:
    deadline = time.monotonic() + max(0, timeout)
    attempts = 0
    last_error = "verification did not run"
    while True:
        attempts += 1
        try:
            result = verify_once(skill, agent, version)
            result["attempts"] = attempts
            return result
        except AppGenError as exc:
            last_error = str(exc)
        if time.monotonic() >= deadline:
            raise AppGenError(
                f"deployment verification timed out after {attempts} attempt(s): {last_error}"
            )
        time.sleep(max(0.1, interval))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", required=True)
    ap.add_argument("--agent-name", default="", help="defaults to <skill>-agent")
    ap.add_argument("--skill-version", default="1.0.0")
    ap.add_argument("--timeout", type=float, default=120)
    ap.add_argument("--interval", type=float, default=3)
    args = ap.parse_args()

    try:
        skill = validate_name(args.skill, "skill name")
        agent = validate_name(args.agent_name or f"{skill}-agent", "agent name")
        result = wait_for_deployment(
            skill, agent, args.skill_version,
            timeout=args.timeout, interval=args.interval,
        )
    except AppGenError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
