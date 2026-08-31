#!/usr/bin/env python3
"""
wwybsj_review.py — the curator review queue, sorted by how much each decision moves.

1017 items are pending: 30 L1 anchors, 5 L1 candidates, 502 L2 assertions,
465 L3 paragraphs. Handing a curator that list unsorted wastes their time, because
the items are not equally consequential:

    one L1 anchor decision      affects up to 229 artifacts
    one L2 assertion decision   affects 1 artifact
    one L3 paragraph decision   affects 1 artifact's label text

So the queue is ordered by IMPACT (artifacts affected), and L1 comes first by
construction. Reviewing 35 L1 items is worth more than reviewing all 465
paragraphs.

VERDICTS ARE DATA
Same discipline as alignment_review.json: a verdict is a row in a JSON file with
the reviewer, the reason, and — for an amendment — the replacement text. Nothing
is decided inside this script. `--apply` writes the verdicts back and flips the
review qualifiers; it never invents a verdict.

Usage:
    python3 wwybsj_review.py --queue                       # 全部，按影响力排序
    python3 wwybsj_review.py --queue --kind l1 --limit 40
    python3 wwybsj_review.py --queue --out queue.json      # 供人工填裁决
    python3 wwybsj_review.py --apply verdicts.json --execute
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wwybsj_common import (  # noqa: E402
    OUT_DIR, TARGET_DOMAIN, call_summary, get_statement, list_statements,
    load_term_usage, post, statement_references,
)

REVIEW_OUT = OUT_DIR / "review"
Q = "wwybsj.qualifier."
REVIEWER_DEFAULT = "curator"


# The three L2 slot predicates. `has_research_gap` is deliberately absent: a
# gap is a statement about the absence of evidence, and there is nothing for a
# curator to accept or reject in it.
L2_SLOT_PREDICATES = ("typological_parallel", "dating_corroboration",
                      "probable_original_context")


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------

def queue_l1() -> list[dict]:
    """Anchors and candidates. Impact = artifacts whose term this is."""
    # Impact = how many artifact statements point at this term. Counted from the
    # six term-valued predicates, which is where every such reference lives.
    uses_by_term = load_term_usage()
    rows = (list_statements(property_id="wwybsj.predicate.aligned_to")
            + list_statements(property_id="wwybsj.predicate.alignment_candidate"))
    out = []
    for r in rows:
        sid, key, subj = r["statement_id"], r["statement_key"], r["subject_id"]
        prop, v = r["name"], r["value_json"]
        status = r["qualifiers"].get("review_status", "") or ""
        if status in ("machine_reviewed_pending_curator",):
            pass       # already carries a machine verdict; curator still confirms
        out.append({
            "kind": "l1", "statement_id": sid, "statement_key": key,
            "target": subj, "predicate": prop, "review_status": status,
            "impact_artifacts": uses_by_term.get(subj, 0),
            "what": f"{subj.rsplit('.',1)[-1]} → {v.get('remote_canonical_name')}"
                    f" [{v.get('match_relation', v.get('match_kind'))}]"
                    f" ×{v.get('cluster_size', 1)}",
            "evidence": (v.get("review") or {}).get("evidence", "")
                        or v.get("review_reason", ""),
            "machine_reason": (v.get("review") or {}).get("reason", ""),
        })
    return out


def queue_l2() -> list[dict]:
    rows = [r for pred in L2_SLOT_PREDICATES
            for r in list_statements(property_id=f"wwybsj.predicate.{pred}")
            if r["layer"] == "L2"]
    out = []
    for r in rows:
        sid, key, subj = r["statement_id"], r["statement_key"], r["subject_id"]
        slot, v = r["metadata"].get("slot", ""), r["value_json"]
        # One provenance call per statement — there is no bulk reference read.
        span = next((ref.get("source_span") or ""
                     for ref in statement_references(sid)
                     if ref.get("property_id") == "wwybsj.ref.remote_passage"), "")
        out.append({
            "kind": "l2", "statement_id": sid, "statement_key": key,
            "target": subj, "predicate": slot, "review_status": "unreviewed",
            "impact_artifacts": 1,
            "what": f"{slot}: {v.get('object_surface','')[:60]}"
                    + (f" [{v.get('stance')}]" if v.get("stance") else ""),
            "evidence": span[:300],
            "machine_reason": v.get("stance_explanation") or v.get("reason", ""),
        })
    return out


def queue_l3() -> list[dict]:
    rows = list_statements(property_id="wwybsj.predicate.has_exhibit_prose")
    return [{"kind": "l3", "statement_id": r["statement_id"],
             "statement_key": r["statement_key"],
             "target": r["subject_id"], "predicate": "has_exhibit_prose",
             "review_status": "false", "impact_artifacts": 1,
             "what": (r["value_json"].get("text") or "")[:90],
             "evidence": f"依据 {len(r['value_json'].get('derived_from') or [])} 条本域断言",
             "machine_reason": ""} for r in rows]


KIND_ORDER = {"l1": 0, "l2": 1, "l3": 2}


def build_queue(kinds: set[str]) -> list[dict]:
    items: list[dict] = []
    if "l1" in kinds:
        items += queue_l1()
    if "l2" in kinds:
        items += queue_l2()
    if "l3" in kinds:
        items += queue_l3()
    # L1 first because one decision there moves up to 229 artifacts; within a
    # kind, the widest-reaching item first.
    items.sort(key=lambda i: (KIND_ORDER[i["kind"]], -i["impact_artifacts"],
                              i["target"]))
    for n, i in enumerate(items, 1):
        i["queue_position"] = n
    return items


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

VERDICTS = {"accept", "reject", "amend"}
# Where each kind records its review state, and what "accepted" looks like there.
REVIEW_QUALIFIER = {"l1": ("review_status", "curator_accepted", "curator_rejected"),
                    "l2": ("review_status", "curator_accepted", "curator_rejected"),
                    "l3": ("reviewed", "true", "rejected")}


def apply_verdicts(path: Path, execute: bool) -> int:
    payload = json.loads(path.read_text(encoding="utf-8"))
    reviewer = payload.get("reviewer") or REVIEWER_DEFAULT
    verdicts = payload.get("verdicts", [])
    by_key = {i["statement_key"]: i for i in build_queue({"l1", "l2", "l3"})}

    plan, problems = [], []
    for v in verdicts:
        key = v.get("statement_key")
        item = by_key.get(key)
        if not item:
            problems.append(f"未知 statement_key: {key}")
            continue
        if v.get("verdict") not in VERDICTS:
            problems.append(f"{key}: 非法 verdict {v.get('verdict')!r}")
            continue
        if v["verdict"] == "amend" and item["kind"] != "l3":
            problems.append(f"{key}: 只有 L3 散文支持 amend（改写文本）")
            continue
        if v["verdict"] == "amend" and not str(v.get("amended_text") or "").strip():
            problems.append(f"{key}: amend 必须给出 amended_text")
            continue
        if v["verdict"] == "amend":
            # A curator's replacement text runs the SAME gates as generated prose.
            # Otherwise the review path is a hole in the gate wall: the first test
            # amendment carried another artifact's dimensions (0004's 口径42/高210.5
            # written onto 0001, whose values are 口径40.5/高11.4) and nothing would
            # have stopped it.
            import wwybsj_l3 as L3
            rn = item["target"].rsplit(".", 1)[-1]
            ok, gate_problems, _ = L3.gate(L3.load_material(rn),
                                           {"text": v["amended_text"]})
            if not ok:
                problems.append(f"{key}: 改写文本未通过 L3 闸门 — "
                                f"{'; '.join(gate_problems)[:140]}")
                continue
        plan.append({"item": item, "verdict": v})

    print(f"裁决 {len(verdicts)} 条 · 可应用 {len(plan)} · 有问题 {len(problems)}")
    for p in problems[:10]:
        print(f"  ✗ {p}")
    if problems:
        # A verdict file with errors is not partially applied: fix it and re-run.
        print("\n裁决文件有错，未做任何写入。")
        return 1
    for p in plan[:10]:
        print(f"  {p['verdict']['verdict']:7s} [{p['item']['kind']}] "
              f"{p['item']['target']}  {p['item']['what'][:56]}")
    if len(plan) > 10:
        print(f"  … 另有 {len(plan)-10} 条")
    if not execute:
        print("\nPREVIEW ONLY — 加 --execute 才写入。")
        return 0

    # Rewrite only the review qualifiers, and for an amendment the text. Every
    # statement is re-upserted WITH its full qualifier set, because the gateway
    # deletes qualifiers before inserting (a lesson that cost 130 references).
    fails = 0
    for p in plan:
        item, v = p["item"], p["verdict"]
        qual_name, accept_val, reject_val = REVIEW_QUALIFIER[item["kind"]]
        new_state = (accept_val if v["verdict"] in ("accept", "amend")
                     else reject_val)
        # Re-read the statement whole, through the gateway, because the upsert
        # below has to send it back complete: the gateway deletes qualifiers and
        # references before inserting, so anything not resent is destroyed.
        stmt = get_statement(item["statement_id"])
        if stmt is None:
            print(f"  ✗ {item['statement_key']}: statement 已不存在", file=sys.stderr)
            fails += 1
            continue
        existing = sorted(stmt["qualifier_rows"], key=lambda q: q["ordinal"])
        value = dict(stmt["value_json"] or {})
        if v["verdict"] == "amend":
            value["text"] = v["amended_text"].strip()
            value["char_count"] = len(value["text"])
            value["amended_by_curator"] = True
        quals = []
        seen = set()
        for q in existing:
            prop = q["property_id"]
            name = prop.replace(Q, "")
            seen.add(name)
            payload_v = ({"text": new_state} if name == qual_name else q["value"])
            quals.append({"statement_key": item["statement_key"], "property_id": prop,
                          "value_type": q["value_type"], "value_json": payload_v,
                          "ordinal": int(q["ordinal"])})
        if qual_name not in seen:
            quals.append({"statement_key": item["statement_key"],
                          "property_id": f"{Q}{qual_name}", "value_type": "string",
                          "value_json": {"text": new_state}, "ordinal": len(quals)})
        for extra, val in (("reviewed_by", reviewer),
                           ("review_note", str(v.get("note") or ""))):
            quals.append({"statement_key": item["statement_key"],
                          "property_id": f"{Q}{extra}", "value_type": "string",
                          "value_json": {"text": val}, "ordinal": len(quals)})
        refs = sorted(statement_references(item["statement_id"]),
                      key=lambda r: r["ordinal"])
        body = {
            "entities": [{"entity_id": f"{Q}{n}", "entity_kind": "property",
                          "semantic_role": "annotation_property",
                          "property_datatype": "string", "namespace": TARGET_DOMAIN,
                          "status": "active",
                          "metadata_json": {"domain": TARGET_DOMAIN, "label": n}}
                         for n in ("reviewed_by", "review_note", qual_name)],
            "statements": [{"statement_key": item["statement_key"],
                            "subject_id": stmt["subject_id"],
                            "property_id": stmt["property_id"],
                            "value_type": stmt["value_type"],
                            **({"value_entity_id": stmt["value_entity_id"]}
                               if stmt["value_entity_id"] else {}),
                            "value_json": value,
                            "status": ("reviewed" if v["verdict"] != "reject"
                                       else "rejected"),
                            "confidence": float(stmt["confidence"] or 0),
                            "created_by": stmt["created_by"],
                            "metadata_json": stmt["metadata"]}],
            "qualifiers": quals,
            "references": [{"statement_key": item["statement_key"],
                            "property_id": r["property_id"],
                            "value_type": r["value_type"],
                            "value_json": r["value"],
                            **({"source_span": r["source_span"]}
                               if r.get("source_span") else {}),
                            "ordinal": int(r["ordinal"])} for r in refs],
        }
        res = post("/ontology/semantic/upsert-batch", body)
        if "error" in res:
            print(f"  ✗ {item['statement_key']}: {res['error'][:80]}", file=sys.stderr)
            fails += 1
    print(f"\n应用 {len(plan) - fails} 条，失败 {fails} 条")
    print(call_summary())
    return 1 if fails else 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--queue", action="store_true")
    mode.add_argument("--apply", metavar="VERDICTS_JSON")
    p.add_argument("--kind", action="append", choices=["l1", "l2", "l3"], default=[])
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--out")
    p.add_argument("--execute", action="store_true")
    args = p.parse_args()

    if args.apply:
        return apply_verdicts(Path(args.apply), args.execute)

    kinds = set(args.kind) or {"l1", "l2", "l3"}
    items = build_queue(kinds)
    counts: dict[str, int] = {}
    for i in items:
        counts[i["kind"]] = counts.get(i["kind"], 0) + 1
    print(f"待复核 {len(items)} 项 {counts}")
    print(f"按影响力排序：一条 L1 裁决最多影响 {max((i['impact_artifacts'] for i in items if i['kind']=='l1'), default=0)} 件文物\n")
    print(f"{'#':>4} {'类':4}{'影响':>5}  {'对象':26} 内容")
    print("-" * 116)
    for i in items[:args.limit]:
        print(f"{i['queue_position']:>4} {i['kind']:4}{i['impact_artifacts']:>5}  "
              f"{i['target'].replace('wwybsj.','')[:26]:26} {i['what'][:56]}")
    if len(items) > args.limit:
        print(f"     … 另有 {len(items)-args.limit} 项（--limit 调整）")

    out = Path(args.out) if args.out else (REVIEW_OUT / "queue.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "schema_version": "wwybsj_review_queue.v1",
        "note": ("按影响力排序的待复核队列。填 verdicts 后用 --apply 应用。"
                 "verdict 取值 accept / reject / amend（amend 仅 L3，需给 amended_text）。"),
        "reviewer": "<填写复核人>",
        "verdicts": [{"statement_key": i["statement_key"], "kind": i["kind"],
                      "target": i["target"], "what": i["what"],
                      "verdict": "", "note": ""} for i in items],
        "queue": items}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n队列（含待填 verdicts 模板）：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
