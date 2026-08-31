#!/usr/bin/env python3
"""
wwybsj_stance.py — recompute dating_corroboration `stance` as a COMPUTED value.

WHY
The LLM produced `stance=supports` for 123 of 123 dating corroborations and
`questions` for none. A judgement that never disagrees is not a judgement. Spot
checks found it wrong: registry 唐代 (618–907) against a passage saying
「不能早于5世纪，晚则不能晚于8世纪前后」 was called `supports`, and 渤海
(698–926) against 「唐开元元年（713年）至后唐天成元年（926年）」 was called
`supports` even though the start years differ by 15.

So stance stops being an opinion and becomes an interval comparison over data
L0 already holds. Where it cannot be computed, it says `undetermined` — which is
the honest answer for the ~97 citations that state no years at all.

PERIOD INTERVALS ARE DERIVED FROM THE REGISTRY ITSELF
Only 23 of 123 artifacts carry a parsed interval of their own, but the registry
states years for SOME record of most periods (渤海（698年—926）, 唐(618~907)…),
so the interval can be lifted to the period term and reused. That derivation is
`inferred`, is written to period_intervals.json for audit, and records:

  * conflicts — 东周 appears as -770~-256 AND -257 AND -258 in the registry. The
    span is widened and `conflict: true` is recorded, never silently resolved.
  * merged sub-periods — 唐天宝年间 (742–756) was normalized into 唐, and a reign
    span is not a dynasty span. Intervals from records whose own label equals the
    canonical term are preferred.

Usage:
    python3 wwybsj_stance.py --derive          # 只推导并打印时期区间表
    python3 wwybsj_stance.py --recompute
    python3 wwybsj_stance.py --recompute --execute
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wwybsj_common import (  # noqa: E402
    OUT_DIR, TARGET_DOMAIN, call_summary, list_statements, post,
)

INTERVALS_PATH = Path(__file__).resolve().parent.parent / "period_intervals.json"
EXTRACTOR = "wwybsj_stance_v1"
P = "wwybsj.predicate."
Q = "wwybsj.qualifier."


# ---------------------------------------------------------------------------
# Period intervals, derived from the registry
# ---------------------------------------------------------------------------

def derive_intervals() -> dict[str, Any]:
    # in_period ⋈ dated_to on the artifact, joined in Python: two paged gateway
    # reads instead of one SQL self-join.
    dated = {r["subject_id"]: r for r in
             list_statements(property_id=f"{P}dated_to")}

    by_period: dict[str, list[dict]] = {}
    for ip in list_statements(property_id=f"{P}in_period"):
        d = dated.get(ip["subject_id"])
        if not d:
            continue
        v = d["value_json"] or {}
        if v.get("start_year") is None:
            continue
        period = ip["value_entity_id"].replace("wwybsj.term.period.", "")
        by_period.setdefault(period, []).append({
            "start": int(v["start_year"]), "end": int(v["end_year"]),
            "normalization": ip["qualifiers"].get("label_normalization", "") or "",
            "literal": v.get("registry_literal", ""),
        })

    out: dict[str, Any] = {}
    for period, obs in by_period.items():
        # A reign span is not a dynasty span: prefer records whose own registry
        # label already WAS the canonical term over ones merged into it.
        canonical = [o for o in obs if o["normalization"] == "canonical"]
        basis_set = canonical or obs
        variants = sorted({(o["start"], o["end"]) for o in basis_set})
        start, end = min(v[0] for v in variants), max(v[1] for v in variants)
        entry = {"start_year": start, "end_year": end,
                 "observations": len(basis_set),
                 "used_only_canonical_labels": bool(canonical),
                 "variants": [f"{a}~{b}" for a, b in variants],
                 "conflict": len(variants) > 1}
        if len(variants) > 1:
            entry["conflict_note"] = (
                "登记簿对该时期给出多个不同区间，已取并集为跨度并如实标记冲突，"
                "不做静默归一")
        dropped = sorted({(o["start"], o["end"]) for o in obs} - set(variants))
        if dropped:
            entry["excluded_from_merged_labels"] = [f"{a}~{b}" for a, b in dropped]
        out[period] = entry
    return out


def load_or_derive(refresh: bool) -> dict[str, Any]:
    if INTERVALS_PATH.exists() and not refresh:
        return json.loads(INTERVALS_PATH.read_text(encoding="utf-8"))["periods"]
    periods = derive_intervals()
    INTERVALS_PATH.write_text(json.dumps(
        {"schema_version": "wwybsj_period_intervals.v1",
         "note": ("时期→年份区间，从登记簿自身已有 range_parsed 的记录推导（inferred）。"
                  "优先采用标签本身即规范形的记录——年号跨度不是朝代跨度（唐天宝年间"
                  "742–756 被归并进唐，但唐的跨度是 618–907）。多个不同区间取并集并"
                  "标记 conflict，不做静默归一。"),
         "derived_by": EXTRACTOR, "periods": periods},
        ensure_ascii=False, indent=2), encoding="utf-8")
    return periods


# ---------------------------------------------------------------------------
# Year parsing from a cited passage
# ---------------------------------------------------------------------------

# 前475 · 公元25 · 713年 · 5世纪 · 前13世纪
_BCE = "前"
_YEAR_TOKEN = re.compile(r"(前)?\s*(?:公元)?\s*(前)?\s*(\d{1,4})\s*(年|世纪)")


def parse_years(text: str) -> list[int]:
    """Every year the passage states, in CE (negative = BCE). Centuries → midpoint."""
    out: list[int] = []
    for m in _YEAR_TOKEN.finditer(text or ""):
        bce = bool(m.group(1) or m.group(2))
        n = int(m.group(3))
        if m.group(4) == "世纪":
            # a century is a range; use its span rather than a point
            lo, hi = (n - 1) * 100 + 1, n * 100
            out.extend([-hi, -lo] if bce else [lo, hi])
        else:
            out.append(-n if bce else n)
    return sorted(set(out))


# ---------------------------------------------------------------------------
# Stance
# ---------------------------------------------------------------------------

def compute_stance(interval: dict | None, cited: list[int]) -> tuple[str, str]:
    if interval is None:
        return "undetermined", "该时期在登记簿中没有任何年份区间可用于比对"
    if not cited:
        return "undetermined", "引用表述中没有可解析的年份"
    lo, hi = interval["start_year"], interval["end_year"]
    c_lo, c_hi = min(cited), max(cited)
    if c_lo >= lo and c_hi <= hi:
        # A citation narrower than the registry span corroborates PART of it. It
        # does not contradict the wider claim — 渤海 698–926 against a passage
        # saying 713–926 leaves 698–713 simply uncorroborated, not refuted — but
        # the distinction is worth keeping visible.
        narrower = (c_lo > lo or c_hi < hi)
        return "supports", (f"引用年份 {c_lo}~{c_hi} 落在登记时期 {lo}~{hi} 之内"
                            + ("（引用范围窄于登记，登记区间的其余部分未被旁证覆盖）"
                               if narrower else ""))
    if c_hi < lo or c_lo > hi:
        return "questions", f"引用年份 {c_lo}~{c_hi} 与登记时期 {lo}~{hi} 完全不重叠"
    return "partial_overlap", (f"引用年份 {c_lo}~{c_hi} 与登记时期 {lo}~{hi} 部分重叠，"
                               f"未完全落入")


def load_targets() -> list[dict]:
    period_of = {r["subject_id"]: r["value_entity_id"].replace(
                     "wwybsj.term.period.", "")
                 for r in list_statements(property_id=f"{P}in_period")}
    return [{"statement_id": c["statement_id"], "statement_key": c["statement_key"],
             "subject_id": c["subject_id"], "value": c["value_json"],
             "period": period_of.get(c["subject_id"], "")}
            for c in list_statements(property_id=f"{P}dating_corroboration")]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--derive", action="store_true")
    mode.add_argument("--recompute", action="store_true")
    p.add_argument("--execute", action="store_true")
    p.add_argument("--refresh-intervals", action="store_true")
    args = p.parse_args()

    periods = load_or_derive(args.refresh_intervals or args.derive)
    if args.derive:
        print(f"{'时期':8s}{'区间':>16s}{'观测数':>7s}{'冲突':>6s}  变体")
        for k, v in sorted(periods.items(), key=lambda kv: kv[1]["start_year"]):
            print(f"{k:8s}{str(v['start_year'])+'~'+str(v['end_year']):>16s}"
                  f"{v['observations']:>7d}{'是' if v['conflict'] else '':>6s}  "
                  f"{' | '.join(v['variants']) if v['conflict'] else ''}"
                  + (f"  [已排除归并标签区间 {v['excluded_from_merged_labels']}]"
                     if v.get("excluded_from_merged_labels") else ""))
        print(f"\n{len(periods)} / 20 个时期可推出区间 → {INTERVALS_PATH}")
        return 0

    targets = load_targets()
    changed, tally, flips = [], {}, {}
    for t in targets:
        cited = parse_years(t["value"].get("object_surface", ""))
        stance, why = compute_stance(periods.get(t["period"]), cited)
        old = t["value"].get("stance", "")
        tally[stance] = tally.get(stance, 0) + 1
        if old != stance:
            flips[f"{old}→{stance}"] = flips.get(f"{old}→{stance}", 0) + 1
        changed.append({**t, "stance": stance, "why": why, "llm_stance": old,
                        "cited_years": cited})

    print(f"断代旁证 {len(targets)} 条")
    print(f"计算结果: {tally}")
    print(f"相对 LLM 判断的变化: {flips}")
    ex = [c for c in changed if c["stance"] in ("questions", "partial_overlap")]
    print(f"\n--- 被改判为质疑/部分重叠的 {len(ex)} 条 ---")
    for c in ex[:10]:
        print(f"  {c['subject_id'].rsplit('.',1)[-1]} [{c['period']}] {c['stance']}: {c['why']}")
        print(f"      引用: {c['value'].get('object_surface','')[:60]}")
    if not args.execute:
        print("\nPREVIEW ONLY — 加 --execute 才写入。")
        return 0

    # Rewrite value_json.stance in place; keep the LLM's verdict for audit.
    statements, qualifiers = [], []
    for c in changed:
        v = dict(c["value"])
        v["stance"] = c["stance"]
        v["stance_basis"] = "computed_interval_comparison"
        v["stance_explanation"] = c["why"]
        v["stance_cited_years"] = c["cited_years"]
        v["llm_stance"] = c["llm_stance"]
        statements.append({
            "statement_key": c["statement_key"], "subject_id": c["subject_id"],
            "property_id": f"{P}dating_corroboration", "value_type": "json",
            "value_json": v, "status": "extracted", "confidence": 0.6,
            "created_by": EXTRACTOR,
            "metadata_json": {"domain": TARGET_DOMAIN, "layer": "L2",
                              "statement_key": c["statement_key"],
                              "slot": "dating_corroboration"}})
        for o, (k, val) in enumerate({
                "epistemic_mode": "attributed", "basis": "remote_source_text",
                "defeasible": {"value": True}, "slot": "dating_corroboration",
                "review_status": "unreviewed",
                "retrieval_run": c["value"].get("retrieval_key", ""),
                "stance_basis": "computed_interval_comparison"}.items()):
            qp = f"{Q}{k}"
            is_text = isinstance(val, str)
            qualifiers.append({"statement_key": c["statement_key"], "property_id": qp,
                               "value_type": "string" if is_text else "json",
                               "value_json": {"text": val} if is_text else val,
                               "ordinal": o})
    ent = [{"entity_id": f"{Q}stance_basis", "entity_kind": "property",
            "semantic_role": "annotation_property", "property_datatype": "string",
            "namespace": TARGET_DOMAIN, "status": "active",
            "metadata_json": {"domain": TARGET_DOMAIN, "label": "stance_basis"}}]
    fails = 0
    for st in range(0, len(statements), 60):
        batch = {"entities": ent if st == 0 else [],
                 "statements": statements[st:st + 60],
                 "qualifiers": [q for q in qualifiers
                                if q["statement_key"] in
                                {s["statement_key"] for s in statements[st:st + 60]}],
                 "references": []}
        r = post("/ontology/semantic/upsert-batch", batch)
        print(f"  {'✓' if 'error' not in r else '✗ ' + r['error'][:80]} "
              f"{len(batch['statements'])} 条")
        fails += 1 if "error" in r else 0
    print(call_summary())
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
