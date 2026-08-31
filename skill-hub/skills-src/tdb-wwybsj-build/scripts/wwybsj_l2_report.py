#!/usr/bin/env python3
"""
wwybsj_l2_report.py — what L2 actually produced, and what it refused to produce.

Reads the written statements (not the plan file), so it reports the state of the
domain rather than the intent of the last run. Everything comes through the v2
gateway; this skill holds no database handle.
"""
from __future__ import annotations
import json, sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wwybsj_common import list_statements, statement_references  # noqa: E402

CACHE = Path("/Users/ningwu/eis/a2a/agents/wwybsj/out/l2/candidate_cache.json")
PLAN = Path("/Users/ningwu/eis/a2a/agents/wwybsj/out/l2/l2_plan.json")

P = "wwybsj.predicate."
SLOTS = ("typological_parallel", "dating_corroboration", "probable_original_context")


def section(title: str) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


# One read of everything L2 can write, reused by every section below.
assertions = [r for slot in SLOTS for r in list_statements(property_id=f"{P}{slot}")
              if r["layer"] == "L2"]
gaps = [r for r in list_statements(property_id=f"{P}has_research_gap")
        if r["layer"] == "L2"]

section("L2 写入总量")
per_pred: dict[str, set[str]] = {}
for r in assertions + gaps:
    per_pred.setdefault(r["name"], set()).add(r["subject_id"])
counts = Counter(r["name"] for r in assertions + gaps)
for pred, n in counts.most_common():
    print(f"  {pred:28s} {n:>6d} 条   覆盖 {len(per_pred[pred]):>4d} 件")

section("断言 vs 缺口（每件文物三个槽位）")
filled = Counter((r["value_json"] or {}).get("slot", "") for r in assertions)
missing = Counter((r["value_json"] or {}).get("slot", "") for r in gaps)
for slot in sorted(set(filled) | set(missing)):
    print(f"  {slot:28s} 已填 {filled[slot]:>5d}   缺口 {missing[slot]:>5d}")

section("缺口原因分布")
for reason, n in Counter((r["value_json"] or {}).get("reason", "") for r in gaps).most_common():
    print(f"  {str(reason):34s} {n:>6d}")

section("证据层级分布（已写入的断言）")
for scope, n in Counter((r["value_json"] or {}).get("evidence_scope", "")
                        for r in assertions).most_common():
    print(f"  {str(scope):22s} {n:>6d}")

section("断代旁证的 stance")
for stance, n in Counter(
        (r["value_json"] or {}).get("stance", "")
        for r in assertions if r["name"] == "dating_corroboration").most_common():
    print(f"  {str(stance):22s} {n:>6d}")

section("远端引用闭环（每条断言必须能回链远端原文）")
# There is no bulk statement_reference read, so this is one /statement/provenance
# call per assertion — a few hundred, which is why it is the last section.
with_ref = 0
events: set[str] = set()
for i, r in enumerate(assertions, 1):
    refs = [x for x in statement_references(r["statement_id"])
            if x.get("property_id") == "wwybsj.ref.remote_passage"]
    if refs:
        with_ref += 1
        for x in refs:
            ev = (x.get("value") or {}).get("event_id")
            if ev:
                events.add(ev)
    if i % 100 == 0:
        print(f"  读取 provenance {i}/{len(assertions)}…", file=sys.stderr)
print(f"  {'有远端引用':22s} {with_ref:>6d}")
print(f"  {'缺引用（不应出现）':22s} {len(assertions) - with_ref:>6d}")
print(f"  被引用的不同远端 event: {len(events)}")

if PLAN.exists():
    plans = json.loads(PLAN.read_text(encoding="utf-8"))
    section("九道闸门各拦下多少（来自最近一次批次的 plan）")
    gates: dict[str, int] = {}
    for p in plans:
        for r in p.get("rejected", []):
            gates[r["gate"]] = gates.get(r["gate"], 0) + 1
    if gates:
        for g, n in sorted(gates.items(), key=lambda kv: -kv[1]):
            print(f"  {g:30s} {n:>6d}")
    else:
        print("  （无拦截）")

if CACHE.exists():
    cache = json.loads(CACHE.read_text(encoding="utf-8"))
    section("检索与候选过滤")
    drops: dict[str, int] = {}
    scopes: dict[str, int] = {}
    zero = 0
    for e in cache.values():
        for w, n in (e.get("dropped") or {}).items():
            drops[w] = drops.get(w, 0) + n
        for c in e.get("candidates", []):
            scopes[c["evidence_scope"]] = scopes.get(c["evidence_scope"], 0) + 1
        if not e.get("candidates"):
            zero += 1
    total = sum(scopes.values())
    print(f"  去重查询 {len(cache)} 个 · 候选 {total} 条 · 零候选查询 {zero} 个")
    print(f"  候选层级: {scopes}")
    print(f"  被过滤:   {dict(sorted(drops.items(), key=lambda kv: -kv[1]))}")
