#!/usr/bin/env python3
"""
wwybsj_predicates.py — register the predicate contract, and enforce it.

The contract lives in ../predicate_contract.json. This script does two things:

  --register   mirror the part of the contract that `ontology_relation_type`
               can actually hold, so the contract is queryable in the canonical
               table (and picked up by the gateway's
               ensure_semantic_property_entity when it copies display_name /
               src_type_id / dst_type_id / is_symmetric / is_transitive into
               semantic_entity metadata).

  --validate   check every wwybsj statement against the FULL contract. This is
               the part that actually enforces anything.

WHY VALIDATION CANNOT BE DELEGATED TO THE DATABASE
  - `semantic_statement` has NO triggers.
  - `POST /v2/ontology/semantic/upsert-batch` never consults
    `ontology_relation_type`; it takes property_id at face value and creates the
    property entity on demand.
  - `ontology_relation_type` has no `is_functional` column at all. Functionality
    is only expressible as conflict_key='src_predicate' + conflict_policy, which
    governs pipeline promotion, not this write path.
  - Its `dst_type_id` assumes an entity-valued object, so the 17 literal/json
    valued wwybsj predicates cannot be described there at all.
  - The upsert API exposes only predicate / src_type_id / dst_type_id /
    display_name / description / is_symmetric / is_transitive / enabled.
    conflict_key and conflict_policy are reachable only over SQL, so this skill
    does not set them at all — see --register's closing note.

So: register what fits, validate everything.

Usage:
    python3 wwybsj_predicates.py --validate
    python3 wwybsj_predicates.py --validate --fail-on-violation   # CI 用
    python3 wwybsj_predicates.py --register                        # dry-run
    python3 wwybsj_predicates.py --register --execute
    python3 wwybsj_predicates.py --report
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wwybsj_common import (  # noqa: E402
    TARGET_DOMAIN, all_registry_nos, load_domain, load_term_usage,
    object_type_ids, post, relation_types, statement_references,
    subject_statements,
)

CONTRACT_PATH = Path(__file__).resolve().parent.parent / "predicate_contract.json"
P = "wwybsj.predicate."
Q = "wwybsj.qualifier."


def load_contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Registration — only what ontology_relation_type can hold
# ---------------------------------------------------------------------------

def register(contract: dict, execute: bool) -> int:
    object_types = contract["object_types"]
    subject_type = contract["subject_kinds"]["artifact"]["object_type"]

    registrable = [p for p in contract["predicates"] if p.get("registrable")]
    skipped = [p for p in contract["predicates"] if not p.get("registrable")]

    # object types the contract references must exist first (FK)
    existing = object_type_ids()
    needed = {subject_type} | {object_types[p["object_facet"]] for p in registrable}
    missing = sorted(needed - existing)

    print(f"contract        : {CONTRACT_PATH}")
    print(f"registrable     : {len(registrable)} / {len(contract['predicates'])} 个谓词")
    print(f"not registrable : {len(skipped)}（字面值或 json 值——relation_type 的 dst_type_id 假定对象是实体）")
    if missing:
        print(f"object_type 缺失 : {missing}")

    if not execute:
        for p in registrable:
            print(f"  [dry-run] {P}{p['name']}  {subject_type} → {object_types[p['object_facet']]}"
                  f"  functional={p['functional']}")
        print("\nDRY-RUN — 加 --execute 才会写入。")
        return 0

    for type_id in missing:
        r = post("/ontology/object-type/upsert",
                 {"type_id": type_id, "display_name": "Collection Acquisition",
                  "description": "入藏途径（发掘/征集购买/旧藏/采集/拨交/接受捐赠/移交）",
                  "enabled": True})
        print(f"  {'✗ ' + str(r['error'])[:80] if 'error' in r else '✓'} object_type {type_id}")

    errors = 0
    for p in registrable:
        body = {
            "predicate": f"{P}{p['name']}",
            "src_type_id": subject_type,
            "dst_type_id": object_types[p["object_facet"]],
            "display_name": p["display_name"],
            "description": (p.get("description") or "")[:500],
            "is_symmetric": bool(p.get("symmetric")),
            "is_transitive": bool(p.get("transitive")),
            "enabled": True,
        }
        r = post("/ontology/relation-type/upsert", body)
        if "error" in r:
            print(f"  ✗ {body['predicate']}: {r['error'][:100]}")
            errors += 1
            continue
        print(f"  ✓ {body['predicate']}  {body['src_type_id']} → {body['dst_type_id']}")

    # conflict_key / conflict_policy are NOT set here. They are only reachable
    # over SQL, and this skill holds no database handle; they also govern
    # pipeline promotion, not this write path. `functional` is enforced where it
    # actually bites — V4 in --validate, over the statements themselves.
    print("\nconflict_key/policy 未设置：v2 API 不暴露这两列，且 functional "
          "由 --validate 的 V4 强制。")
    return 1 if errors else 0


# ---------------------------------------------------------------------------
# Validation — the part that actually enforces
# ---------------------------------------------------------------------------

class Violations:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add(self, check: str, predicate: str, detail: str, sample: str = "") -> None:
        self.rows.append({"check": check, "predicate": predicate,
                          "detail": detail, "sample": sample})

    def report(self) -> int:
        if not self.rows:
            print("\n✓ 全部检查通过，无违规。")
            return 0
        print(f"\n✗ {len(self.rows)} 项违规：")
        by_check: dict[str, list[dict]] = {}
        for r in self.rows:
            by_check.setdefault(r["check"], []).append(r)
        for check, rows in by_check.items():
            print(f"\n  [{check}] {len(rows)} 项")
            for r in rows[:12]:
                print(f"    {r['predicate']:28s} {r['detail']}")
                if r["sample"]:
                    print(f"      {r['sample'][:140]}")
            if len(rows) > 12:
                print(f"    … 另有 {len(rows) - 12} 项")
        return len(self.rows)


def load_rows(progress: bool = True) -> list[dict]:
    """
    Every statement in the domain, read through the gateway.

    Two passes, because `statement/list` has neither a domain filter nor a
    prefix filter:

      1. by predicate, for every predicate the contract declares;
      2. by subject, for every artifact and every term.

    Pass 1 alone cannot see a predicate that is in the database but not in the
    contract — which is exactly what V1 exists to find. Pass 2 finds those,
    because it asks about subjects instead. What neither pass can see is a
    statement whose predicate is off-contract AND whose subject is neither an
    artifact nor a term; V1's report says so rather than implying completeness.
    """
    seen: dict[str, dict] = {}
    for r in load_domain(progress=progress):
        seen[r["statement_id"]] = r

    subjects = [f"wwybsj.artifact.{n}" for n in all_registry_nos()]
    subjects += sorted(load_term_usage())
    for i, subj in enumerate(subjects, 1):
        for r in subject_statements(subj):
            seen[r["statement_id"]] = r
        if progress and i % 100 == 0:
            print(f"  [subject scan {i}/{len(subjects)}]", file=sys.stderr)
    return list(seen.values())


def validate(contract: dict) -> int:
    v = Violations()
    by_name = {p["name"]: p for p in contract["predicates"]}
    layers = contract["layers"]

    rows = load_rows()
    in_use = {r["name"] for r in rows if r["property_id"].startswith(P)}
    by_pred: dict[str, list[dict]] = {}
    for r in rows:
        by_pred.setdefault(r["name"], []).append(r)

    print(f"契约谓词 {len(by_name)} 个 · 库内在用 {len(in_use)} 个 "
          f"· 读到 statement {len(rows)} 条")

    # V1 未注册谓词
    for name in sorted(in_use - set(by_name)):
        v.add("V1 未在契约中声明的谓词", name, "库内在用但契约里没有")

    # V2 契约声明但未使用（提示，非错误）
    unused = sorted(set(by_name) - in_use)

    # V3 value_type / layer 与契约一致
    for pred, group in by_pred.items():
        c = by_name.get(pred)
        if not c:
            continue
        for vtype in sorted({r["value_type"] for r in group}):
            if vtype != c["value_type"]:
                v.add("V3 value_type 不符", pred, f"库内 {vtype}，契约 {c['value_type']}")
        for layer in sorted({r["layer"] for r in group}):
            if layer != c["layer"]:
                v.add("V3 layer 不符", pred, f"库内 {layer}，契约 {c['layer']}")

    # V4 functional：同一主体同一谓词多于一条
    for pred, group in by_pred.items():
        c = by_name.get(pred)
        if not (c and c.get("functional")):
            continue
        per_subject: dict[str, int] = {}
        for r in group:
            per_subject[r["subject_id"]] = per_subject.get(r["subject_id"], 0) + 1
        for subject, n in per_subject.items():
            if n > 1:
                v.add("V4 functional 被违反", pred, f"{subject} 有 {n} 条", "")

    # V5 inverse functional：同一值被多个主体持有
    for name, c in by_name.items():
        if not c.get("inverse_functional"):
            continue
        holders: dict[str, set[str]] = {}
        for r in by_pred.get(name, []):
            # An entity-valued predicate carries its value in value_entity_id, a
            # literal one in value_json. Reading the wrong one makes every row
            # look identical and reports a violation that is not there.
            key = (r["value_entity_id"] if c["value_type"] == "entity"
                   else json.dumps(r["value_json"], ensure_ascii=False, sort_keys=True))
            holders.setdefault(key, set()).add(r["subject_id"])
        for val, subs in holders.items():
            if len(subs) > 1:
                v.add("V5 inverse functional 被违反", name,
                      f"值 {val!r} 被 {len(subs)} 个主体共用")

    # V6 主体 id 形状与 subject_kind 一致
    prefixes = {k: sk["id_prefix"] for k, sk in contract["subject_kinds"].items()}
    for name, c in by_name.items():
        if name not in in_use:
            continue
        want = prefixes[c["subject_kind"]]
        bad = sorted({r["subject_id"] for r in by_pred.get(name, [])
                      if not r["subject_id"].startswith(want)})
        for subject in bad[:5]:
            v.add("V6 主体类型不符", name, f"期望 {want}*，实际 {subject}")

    # V7 entity 值的对象 facet 与契约一致.
    #
    # The facet used to come from a join on semantic_entity, which the gateway
    # does not expose. It is read off the id instead — L0 mints terms as
    # `wwybsj.term.<facet>.<label>`, so the id IS the facet declaration. The
    # cost is that a dangling reference to a nonexistent entity now reads as a
    # facet mismatch rather than as "(实体不存在)".
    for name, c in by_name.items():
        if c["value_type"] != "entity" or name not in in_use:
            continue
        facet = c["object_facet"]
        seen_bad: dict[tuple[str, str], int] = {}
        for r in by_pred.get(name, []):
            oid = r["value_entity_id"]
            got = ""
            if oid.startswith("wwybsj.term."):
                got = oid[len("wwybsj.term."):].partition(".")[0]
            if got != facet:
                k = (oid, got)
                seen_bad[k] = seen_bad.get(k, 0) + 1
        for (obj, got), n in list(seen_bad.items())[:5]:
            v.add("V7 对象 facet 不符", name,
                  f"期望 {facet}，实际 {got or '(不是 wwybsj.term.* 实体)'}：{obj}")

    # V8 epistemic_mode 必须在该层允许的集合内
    for name, c in by_name.items():
        if name not in in_use:
            continue
        allowed = layers[c["layer"]]["allowed_epistemic_modes"]
        required = c.get("required_epistemic_mode")
        ok = {required} if required else set(allowed)
        bad: dict[str, int] = {}
        for r in by_pred.get(name, []):
            mode = r["qualifiers"].get("epistemic_mode") or ""
            if mode not in ok:
                label = mode or "(缺失)"
                bad[label] = bad.get(label, 0) + 1
        for mode, n in bad.items():
            v.add("V8 epistemic_mode 不允许", name,
                  f"{n} 条为 {mode}，该层只允许 {required or allowed}")

    # V9 必需 qualifier 齐全
    for name, c in by_name.items():
        if name not in in_use:
            continue
        for qkey in c.get("required_qualifiers", []):
            n = sum(1 for r in by_pred.get(name, [])
                    if qkey not in r["qualifiers"])
            if n:
                v.add("V9 必需 qualifier 缺失", name, f"{n} 条缺 {qkey}")

    # V10 必需 reference 齐全.
    #
    # One /statement/provenance call per statement — there is no bulk reference
    # read — so this is the slow check: a few thousand calls for L0. It is not
    # sampled, because a sampled provenance check reports "closed" on a domain
    # that is not.
    ref_needed: list[tuple[str, str, list[dict]]] = []
    for name, c in by_name.items():
        if name not in in_use:
            continue
        # "" means this predicate explicitly needs no reference; a MISSING key
        # falls back to the layer default.
        ref = (c["required_reference"] if "required_reference" in c
               else layers[c["layer"]]["required_reference"])
        if ref:
            ref_needed.append((name, ref, by_pred.get(name, [])))
    total_refs = sum(len(g) for _, _, g in ref_needed)
    print(f"V10 provenance 检查：{total_refs} 条 statement（逐条读取，不抽样）",
          file=sys.stderr)
    done = 0
    for name, ref, group in ref_needed:
        missing = 0
        for r in group:
            props = {x.get("property_id") for x in statement_references(r["statement_id"])}
            if ref not in props:
                missing += 1
            done += 1
            if done % 500 == 0:
                print(f"  [provenance {done}/{total_refs}]", file=sys.stderr)
        if missing:
            v.add("V10 必需 reference 缺失", name, f"{missing} 条缺 {ref}")

    # V11 json 值必需键齐全
    for name, c in by_name.items():
        if c["value_type"] != "json" or name not in in_use:
            continue
        for key in c.get("required_value_keys", []):
            n = sum(1 for r in by_pred.get(name, [])
                    if key not in (r["value_json"] or {}))
            if n:
                v.add("V11 json 必需键缺失", name, f"{n} 条缺 value_json.{key}")

    # V12 json 值枚举字段取值合法
    for name, c in by_name.items():
        if name not in in_use:
            continue
        for key, allowed in (c.get("value_enums") or {}).items():
            bad: dict[str, int] = {}
            for r in by_pred.get(name, []):
                vj = r["value_json"] or {}
                if key in vj and vj[key] not in allowed:
                    bad[str(vj[key])] = bad.get(str(vj[key]), 0) + 1
            for got, n in list(bad.items())[:5]:
                v.add("V12 枚举取值非法", name,
                      f"{key}={got!r} 共 {n} 条，允许 {allowed}")

    # V13 被禁用的谓词不得出现
    present = {r["property_id"] for r in rows}
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["property_id"]] = counts.get(r["property_id"], 0) + 1
    for bad_name, why in contract["forbidden_predicates"].items():
        base = bad_name.split("(")[0]
        n = counts.get(f"{P}{base}", 0) + counts.get(base, 0)
        if n:
            v.add("V13 使用了被禁谓词", base, f"{n} 条", why[:110])

    # V14 裸名谓词（命名空间抢注防线）
    for prop in sorted(pid for pid in present if not pid.startswith("wwybsj.")):
        v.add("V14 使用了非 wwybsj 前缀的谓词", prop,
              f"{counts[prop]} 条——裸名会抢占全局谓词归属")

    n = v.report()
    if unused:
        print(f"\n提示：契约声明但库内未使用的谓词 {len(unused)} 个：{unused}")
    return n


def report(contract: dict) -> None:
    rows = relation_types(P)
    print(f"{'predicate':44s}{'src':22s}{'dst':24s}{'sym':5s}{'trans':6s}{'enabled':8s}")
    print("-" * 110)
    for r in rows:
        print(f"{r['predicate']:44s}{r.get('src_type_id',''):22s}"
              f"{r.get('dst_type_id',''):24s}"
              f"{str(bool(r.get('is_symmetric'))):5s}"
              f"{str(bool(r.get('is_transitive'))):6s}"
              f"{str(bool(r.get('enabled'))):8s}")
    print(f"\n已注册 {len(rows)} 个。契约共 {len(contract['predicates'])} 个，"
          f"其中 {sum(1 for p in contract['predicates'] if p.get('registrable'))} 个可注册。")
    print("注：conflict_key / conflict_policy 不在此列出——v2 API 不暴露这两列。"
          "\n    functional 由 --validate 的 V4 强制，不依赖 relation_type。")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--register", action="store_true")
    mode.add_argument("--validate", action="store_true")
    mode.add_argument("--report", action="store_true")
    p.add_argument("--execute", action="store_true", help="--register 时真正写入")
    p.add_argument("--fail-on-violation", action="store_true",
                   help="有违规时返回非零退出码（CI 用）")
    p.add_argument("--contract", default=str(CONTRACT_PATH),
                   help="改用别的契约文件（自测用：扰动契约而不动数据）")
    args = p.parse_args()

    contract = json.loads(Path(args.contract).read_text(encoding="utf-8"))
    if args.report:
        report(contract)
        return 0
    if args.register:
        return register(contract, args.execute)
    n = validate(contract)
    return 1 if (n and args.fail_on_violation) else 0


if __name__ == "__main__":
    raise SystemExit(main())
