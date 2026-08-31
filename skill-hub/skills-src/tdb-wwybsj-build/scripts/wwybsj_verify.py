#!/usr/bin/env python3
"""
wwybsj_verify.py — the acceptance queries, answered through the gateway.

These used to be SQL in SKILL.md. They are here instead, for two reasons:

  - this skill holds no database handle, by design (see wwybsj_common.py);
  - a competency question that lives in prose gets copied wrong. One that lives
    in a script gets run.

The ontology is "done" when these come back clean. Each check prints what it
found, not merely pass/fail, because the interesting output of Q3 is the
contradiction itself.

Usage:
    python3 wwybsj_verify.py                # all checks
    python3 wwybsj_verify.py --check q3     # one
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wwybsj_common import (  # noqa: E402
    all_registry_nos, call_summary, list_statements, load_term_usage,
    wiki_page_slugs,
)

P = "wwybsj.predicate."

# Who is allowed to have written each layer. Two writers at L2 is correct, not a
# smell: wwybsj_stance_v1 re-upserts `dating_corroboration` with the computed
# stance, so those rows carry its name rather than wwybsj_l2_v1's. Anything NOT
# on this list is either an orphan from a bumped EXTRACTOR string or a writer
# nobody declared — both worth stopping for.
EXPECTED_EXTRACTORS: dict[str, set[str]] = {
    "L0": {"wwybsj_l0_v2"},
    "L1": {"wwybsj_l1_v2"},
    "L2": {"wwybsj_l2_v1", "wwybsj_stance_v1"},
    "L3": {"wwybsj_l3_v1"},
}


def q0_inventory() -> int:
    """Q0 — layer census. The one check that catches a half-copied domain."""
    from wwybsj_common import load_domain
    rows = load_domain()
    by_layer = Counter(r["layer"] or "(无 layer)" for r in rows)
    print("  层        条数")
    for layer in ("L0", "L1", "L2", "L3"):
        print(f"  {layer:8s}{by_layer.get(layer, 0):>8d}")
    other = {k: v for k, v in by_layer.items() if k not in ("L0", "L1", "L2", "L3")}
    if other:
        print(f"  其他     {other}")
    print(f"  合计     {len(rows):>8d}")
    print(f"  文物     {len(all_registry_nos()):>8d} 件")
    print(f"  词项     {len(load_term_usage()):>8d} 个")
    print(f"  wiki 页  {len(wiki_page_slugs()):>8d}")
    if not by_layer.get("L0"):
        print("  ✗ L0 为空——域没建，或者网关指向了另一个库")
        return 1
    return 0


def q1_before_300ce() -> int:
    """Q1 — datable earlier than 300 CE. Needs the typed interval, not the label."""
    rows = list_statements(property_id=f"{P}dated_to")
    early = [r for r in rows
             if isinstance((r["value_json"] or {}).get("end_year"), int)
             and r["value_json"]["end_year"] < 300]
    print(f"  断代 end_year < 300 的文物：{len(early)} 件 / 有 typed 区间 "
          f"{sum(1 for r in rows if (r['value_json'] or {}).get('end_year') is not None)} 件"
          f" / 共 {len(rows)} 条 dated_to")
    for r in sorted(early, key=lambda r: r["value_json"]["end_year"])[:8]:
        v = r["value_json"]
        print(f"    {r['registry_no']}  {v.get('era_label','')}  "
              f"{v.get('start_year')}~{v.get('end_year')}  {v.get('registry_literal','')}")
    return 0


def q3_period_conflicts() -> int:
    """
    Q3 — consistency: one era label registered as mutually inconsistent spans.

    A finding here is a real registry defect, not a bug in this check. The
    known one is 东周, registered as -770~-256 / -257 / -258.
    """
    spans: dict[str, set[str]] = {}
    for r in list_statements(property_id=f"{P}dated_to"):
        v = r["value_json"] or {}
        label = v.get("era_label")
        if not label or v.get("start_year") is None:
            continue
        spans.setdefault(label, set()).add(f"{v['start_year']}~{v['end_year']}")
    bad = {k: sorted(s) for k, s in spans.items() if len(s) > 1}
    print(f"  年代标签 {len(spans)} 个，其中区间不一致 {len(bad)} 个")
    for label, variants in sorted(bad.items()):
        print(f"    {label}: {' | '.join(variants)}")
    return 0


def q6_reverse_join() -> int:
    """Q6 — reverse join: which local artifacts instantiate each remote concept."""
    anchors = {r["subject_id"]: r["value_json"] or {}
               for r in list_statements(property_id=f"{P}aligned_to")}
    holders: dict[str, set[str]] = {}
    for pred in ("instantiates", "made_of"):
        for r in list_statements(property_id=f"{P}{pred}"):
            term = r["value_entity_id"]
            if term in anchors:
                holders.setdefault(term, set()).add(r["subject_id"])
    by_remote: dict[str, set[str]] = {}
    reachable_ids: set[str] = set()
    for term, subs in holders.items():
        name = anchors[term].get("remote_canonical_name") or term
        by_remote.setdefault(str(name), set()).update(subs)
        reachable_ids.update(anchors[term].get("concept_ids") or [])
    all_ids = {c for v in anchors.values() for c in (v.get("concept_ids") or [])}
    print(f"  锚点覆盖的远端 concept id：{len(all_ids)} 个"
          f"（其中经 instantiates/made_of 可从藏品到达：{len(reachable_ids)} 个）")
    print(f"  {'远端概念':22s}{'本馆藏品数':>10s}")
    for name, subs in sorted(by_remote.items(), key=lambda kv: -len(kv[1]))[:12]:
        print(f"  {name:22s}{len(subs):>10d}")
    if not reachable_ids:
        print("  ✗ 没有任何远端可达路径——L1 没跑，或锚点全被否决")
        return 1
    return 0


def q7_orphan_extractors() -> int:
    """
    Q7 — orphaned rows from an earlier extractor version.

    Changing a statement_key shape or an EXTRACTOR string does not overwrite the
    old rows; it stops regenerating them. They then sit there forever, counted by
    every report, regenerated by nothing.
    """
    from wwybsj_common import contract_predicate_ids
    by_pair: dict[tuple[str, str], int] = {}
    for pid in contract_predicate_ids():
        for r in list_statements(property_id=pid):
            by_pair[(r["layer"], r["created_by"])] = \
                by_pair.get((r["layer"], r["created_by"]), 0) + 1
    print(f"  {'层':6s}{'created_by':26s}{'条数':>8s}")
    for (layer, who), n in sorted(by_pair.items()):
        print(f"  {layer:6s}{who:26s}{n:>8d}")
    unexpected = sorted({(layer, who) for (layer, who) in by_pair
                         if who not in EXPECTED_EXTRACTORS.get(layer, set())})
    if unexpected:
        print("  ! 出现未登记的 extractor：" +
              ", ".join(f"{l}/{w}（{by_pair[(l, w)]} 条）" for l, w in unexpected))
        print("    孤儿行不会被 --execute 覆盖，只会停止再生；确认后删除，"
              "或把新版本写进 EXPECTED_EXTRACTORS。")
        return 1
    return 0


CHECKS = {
    "q0": ("Q0 分层清点", q0_inventory),
    "q1": ("Q1 断代早于公元 300 年", q1_before_300ce),
    "q3": ("Q3 年代标签区间一致性", q3_period_conflicts),
    "q6": ("Q6 反向 join：远端概念 ← 本馆藏品", q6_reverse_join),
    "q7": ("Q7 孤儿 extractor 行", q7_orphan_extractors),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", choices=sorted(CHECKS), action="append",
                    help="只跑指定检查，可重复；默认全跑")
    args = ap.parse_args()

    problems = 0
    for key in (args.check or sorted(CHECKS)):
        title, fn = CHECKS[key]
        print(f"\n{'=' * 68}\n{title}\n{'=' * 68}")
        problems += fn()
    print(f"\n{call_summary()}")
    print("\n✓ 验收查询全部通过。" if not problems
          else f"\n✗ {problems} 项需要处理（见上）。")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
