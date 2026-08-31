#!/usr/bin/env python3
"""
wwybsj_new_item.py — Step 0: take in ONE OR MORE NEW artifact records and run
them through the same build pipeline the 465 base records went through.

The base dump (a2a/agents/wwybsj/wwybsj.json) is frozen — it is the registry
export, not a working file. New records go into the intake overlay
(out/wwybsj_new_items.json); wwybsj_common.load_records() merges base + overlay,
so ingest / L0 / L1 / research / wiki pick them up with no further change.

What this script adds on top of "just edit the JSON":
  - accepts friendly Chinese keys (名称/类别/质地/年代/…) as well as raw columns
  - fills every one of the 34 registry columns so record_text() stays complete
  - allocates a free `id` and 藏品总登记号 (`ww_bianhao`), or validates the
    caller-supplied one against BOTH the base dump and the overlay
  - refuses silently-lossy input (unknown keys, duplicate 登记号) instead of
    writing a half-record that L0 would happily turn into statements
  - --build chains ingest -> L0 -> L1 for exactly the new 登记号

Usage:
  # one item, inline fields (demo-friendliest)
  python3 wwybsj_new_item.py --set 名称=辽白釉刻花碗 --set 类别=瓷器 \
      --set 质地=瓷 --set 年代="辽(907~1125)" --set 级别=三级 --set 来源=征集
  python3 wwybsj_new_item.py --set ... --execute --build

  # a pasted wwybsj-format JSON payload — the shortest path from "here is a
  # new artifact" to a built knowledge entry
  python3 wwybsj_new_item.py --json '{"ww_mingchen":"辽白釉刻花碗","ww_leibie":"瓷器"}'
  python3 wwybsj_new_item.py --json "$PAYLOAD" --execute --build

  # one or many, from a file (object, array, or {"records":[...]})
  python3 wwybsj_new_item.py --file new_items.json --execute --build
  cat new_items.json | python3 wwybsj_new_item.py --file - --execute --build

  python3 wwybsj_new_item.py --list          # what's in the overlay
  python3 wwybsj_new_item.py --remove 466    # drop one from the overlay
                                             # (does NOT unwrite TDB statements)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wwybsj_common import (  # noqa: E402
    FIELDS, NEW_ITEMS_JSON, bianhao, clean, load_new_items, load_records,
    record_text, title,
)

HERE = Path(__file__).resolve().parent

# Friendly aliases -> registry columns. Anything not here must be a raw column
# name; unknown keys are an error, never a silent drop.
ALIASES: dict[str, str] = {
    "名称": "ww_mingchen",      "文物名称": "ww_mingchen",   "name": "ww_mingchen",
    "原名": "ww_yuanming",      "文物原名": "ww_yuanming",
    "编号": "ww_bianhao",       "登记号": "ww_bianhao",      "藏品总登记号": "ww_bianhao",
    "编号名称": "ww_bh_leixing",
    "年代": "ww_niandai_b",     "断代": "ww_niandai_b",      "period": "ww_niandai_b",
    "年代体系": "ww_niandai_a", "具体年代": "ww_niandai_jt",
    "类别": "ww_leibie",        "文物类别": "ww_leibie",     "category": "ww_leibie",
    "质地": "ww_zhidi_c",       "材质": "ww_zhidi_c",        "material": "ww_zhidi_c",
    "质地大类": "ww_zhidi_b",   "质地构成": "ww_zhidi_a",
    "数量": "ww_shuliang",      "长": "ww_chang", "宽": "ww_kuan", "高": "ww_gao",
    "尺寸": "ww_chicun",        "质量": "ww_zhiliang_jt",    "质量单位": "ww_zhiliang_dw",
    "质量范围": "ww_zhiliang_fw",
    "级别": "ww_jibie",         "文物级别": "ww_jibie",
    "来源": "ww_laiyuan",       "文物来源": "ww_laiyuan",
    "完残程度": "ww_wancan_cd", "完残": "ww_wancan_cd",      "完残状况": "ww_wancan_zk",
    "保存状态": "ww_baocun_zt", "保存时间": "ww_baocun_sj",  "保存年代": "ww_baocun_nd",
    "作者": "ww_zuoze",  "版本": "ww_banben",  "存卷": "ww_cunjuan",
    "英文名": "ww_mingchen_en",
}

# Columns whose empty value is 0 / numeric in the base dump, so record_text and
# the L0 typed parsers see exactly the shapes they already handle.
NUMERIC_EMPTY = {"ww_shuliang": 1, "ww_baocun_nd": 0}
DECIMAL_EMPTY = {"ww_chang": "0.00", "ww_kuan": "0.00", "ww_gao": "0.00"}

DEFAULTS = {
    "ww_bh_leixing": "藏品总登记号",
    "ww_niandai_a": "中国历史学年代",
}

# L0 can only emit the facets it is given. Missing 类别/质地 does not fail the
# write, it just produces an artifact with no `instantiates` / `made_of` edge —
# and therefore no L1 path to the remote corpus. Say so loudly.
RECOMMENDED = {
    "ww_leibie": "文物类别 — 没有它就没有 instantiates 边，L1 到远端无通路",
    "ww_zhidi_c": "质地 — 没有它就没有 made_of 边",
    "ww_niandai_b": "年代 — 没有它 dated_to 缺失，年代区间查询查不到这件",
}


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

def parse_sets(pairs: list[str]) -> dict:
    rec: dict = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"--set expects k=v, got {pair!r}")
        k, v = pair.split("=", 1)
        rec[k.strip()] = v.strip()
    return rec


def parse_json(raw: str, origin: str) -> list[dict]:
    """
    A pasted wwybsj-format payload -> a list of records.

    Accepted shapes, all of them things a caller actually pastes:
      {...}                  one record
      [{...}, {...}]         several
      {"records": [...]}     several, wrapped
      {"data": [...]}        several, wrapped (the shape sql_to_json.py emits)

    Failing loudly on anything else matters more than being clever here: a
    payload this function mis-reads becomes statements downstream, and a
    half-understood record is indistinguishable from a real one once it is in
    the domain.
    """
    raw = raw.strip()
    if not raw:
        raise SystemExit(f"{origin}: empty input")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SystemExit(f"{origin}: 不是合法 JSON — {e}")
    if isinstance(data, dict):
        for key in ("records", "data", "rows"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = [data]
    if not isinstance(data, list) or not all(isinstance(d, dict) for d in data):
        raise SystemExit(f"{origin}: 需要对象、对象数组，或 "
                         '{"records": [...]}／{"data": [...]}')
    if not data:
        raise SystemExit(f"{origin}: JSON 里没有记录")
    return data


def read_file(path: str) -> list[dict]:
    raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    return parse_json(raw, "stdin" if path == "-" else path)


# ---------------------------------------------------------------------------
# Normalization / validation
# ---------------------------------------------------------------------------

def normalize(raw: dict) -> tuple[dict, list[str]]:
    """Map aliases onto registry columns and fill every column. Raises on unknown keys."""
    out: dict = {}
    unknown = []
    for k, v in raw.items():
        col = ALIASES.get(k, k)
        if col not in FIELDS:
            unknown.append(k)
            continue
        out[col] = v
    if unknown:
        raise SystemExit(
            f"unknown field(s): {', '.join(unknown)}\n"
            f"use a registry column ({', '.join(list(FIELDS)[:6])}, …) or an alias "
            f"({', '.join(list(ALIASES)[:8])}, …)")

    warnings = []
    if not clean(out.get("ww_mingchen")):
        raise SystemExit("文物名称 (ww_mingchen) is required — it is the slug and title")

    for col, why in RECOMMENDED.items():
        if not clean(out.get(col)):
            warnings.append(f"missing {why}")

    # 质地 hierarchy: if only the specific term is given, fill the coarse ones the
    # way the registry does, so the L0 material facets line up with existing terms.
    if clean(out.get("ww_zhidi_c")) and not clean(out.get("ww_zhidi_a")):
        out["ww_zhidi_a"] = "单一质地"
    if clean(out.get("ww_zhidi_c")) and not clean(out.get("ww_zhidi_b")):
        warnings.append("质地大类 (ww_zhidi_b, 无机质/有机质) not given — left blank")

    if clean(out.get("ww_zhiliang_jt")) and not clean(out.get("ww_zhiliang_dw")):
        warnings.append("质量 given without 质量单位 — L0 will mark unit_source=unspecified")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rec: dict = {}
    for col in FIELDS:
        if col in out:
            rec[col] = out[col]
        elif col in DEFAULTS:
            rec[col] = DEFAULTS[col]
        elif col in NUMERIC_EMPTY:
            rec[col] = NUMERIC_EMPTY[col]
        elif col in DECIMAL_EMPTY:
            rec[col] = DECIMAL_EMPTY[col]
        elif col == "ww_ctime":
            rec[col] = now
        elif col == "ww_mtime":
            rec[col] = "0000-00-00 00:00:00"
        else:
            rec[col] = ""
    return rec, warnings


def allocate(recs: list[dict], existing: list[dict]) -> list[str]:
    """Assign / validate `id` and `ww_bianhao` against base + overlay. Returns notes."""
    used_ids = {r["id"] for r in existing}
    used_no = {bianhao(r) for r in existing}
    next_id = max(used_ids) + 1 if used_ids else 1
    next_no = max((int(n) for n in used_no if n.isdigit()), default=0) + 1
    notes = []
    for rec in recs:
        given_no = re.sub(r"\D", "", str(rec.get("ww_bianhao") or ""))
        if given_no:
            padded = given_no.zfill(4)
            if padded in used_no:
                raise SystemExit(
                    f"藏品总登记号 {padded} already exists — refusing to write a "
                    f"second record under the same 登记号 (it is the artifact's "
                    f"identity: wwybsj.artifact.{padded})")
            rec["ww_bianhao"] = str(int(given_no))
        else:
            rec["ww_bianhao"] = str(next_no)
            notes.append(f"登记号 auto-allocated: {str(next_no).zfill(4)}")
            next_no += 1
        used_no.add(bianhao(rec))

        if rec.get("id") in (None, "", 0):
            rec["id"] = next_id
            next_id += 1
        else:
            rec["id"] = int(rec["id"])
            if rec["id"] in used_ids:
                raise SystemExit(f"record id={rec['id']} already exists")
        used_ids.add(rec["id"])
    return notes


# ---------------------------------------------------------------------------
# Overlay
# ---------------------------------------------------------------------------

def save_overlay(records: list[dict]) -> None:
    NEW_ITEMS_JSON.parent.mkdir(parents=True, exist_ok=True)
    NEW_ITEMS_JSON.write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Build chain
# ---------------------------------------------------------------------------

def run(argv: list[str]) -> int:
    print(f"\n$ {' '.join(argv)}", flush=True)
    return subprocess.run([sys.executable, *argv]).returncode


def build(regnos: list[str], skip_l1: bool) -> int:
    """ingest -> L0 for each new 登记号, then L1 once (terms are shared)."""
    for rec_id, regno in regnos:
        rc = run([str(HERE / "wwybsj_ingest.py"), "--id", str(rec_id), "--execute"])
        if rc:
            return rc
        rc = run([str(HERE / "wwybsj_l0.py"), "--registry-no", regno, "--execute"])
        if rc:
            return rc
    if skip_l1:
        print("\n(skipping L1 — pass without --no-l1 to re-anchor terms)")
        return 0
    # L1 re-resolves the whole term set, not just the new ones: a new item can
    # introduce a term (a category/material never seen in the base 465) that has
    # no anchor yet, and resolved terms come from the cache, so this is cheap.
    return run([str(HERE / "wwybsj_l1.py"), "--execute"])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--json", metavar="JSON",
                   help="wwybsj 格式的 JSON 原文（一条、数组，或 {records:[…]}）——"
                        "直接粘贴，不用先落盘")
    p.add_argument("--file", help="JSON file with one record, an array, or {records:[…]}; - for stdin")
    p.add_argument("--set", action="append", default=[], metavar="K=V",
                   help="One field of a single new record; repeatable. Chinese aliases ok.")
    p.add_argument("--list", action="store_true", help="Show the intake overlay")
    p.add_argument("--remove", type=int, metavar="ID", help="Drop a record from the overlay")
    p.add_argument("--execute", action="store_true", help="Write the overlay (default: preview)")
    p.add_argument("--build", action="store_true", help="Then run ingest -> L0 -> L1 for the new items")
    p.add_argument("--no-l1", action="store_true", help="With --build, stop after L0")
    args = p.parse_args()

    overlay = load_new_items()

    if args.list:
        print(f"overlay: {NEW_ITEMS_JSON}")
        if not overlay:
            print("(empty — base registry only, 465 records)")
            return 0
        for rec in overlay:
            print(f"  id={rec['id']:<5} {bianhao(rec)}  {title(rec)}")
        print(f"\n{len(overlay)} new record(s); merged total "
              f"{len(load_records())}")
        return 0

    if args.remove is not None:
        keep = [r for r in overlay if r["id"] != args.remove]
        if len(keep) == len(overlay):
            raise SystemExit(f"id={args.remove} is not in the overlay")
        if not args.execute:
            print(f"DRY-RUN: would drop id={args.remove} from {NEW_ITEMS_JSON}")
            return 0
        save_overlay(keep)
        print(f"✓ dropped id={args.remove}. NOTE: statements already written to TDB "
              f"are NOT removed — delete them by subject_id if you need to.")
        return 0

    given = [name for name, val in (("--json", args.json), ("--file", args.file),
                                    ("--set", args.set)) if val]
    if not given:
        raise SystemExit("nothing to add — pass --json, --file, --set, --list or --remove")
    if len(given) > 1:
        raise SystemExit(f"{' 和 '.join(given)} 互斥，一次只用一种输入")

    if args.json:
        raw_items = parse_json(args.json, "--json")
    elif args.file:
        raw_items = read_file(args.file)
    else:
        raw_items = [parse_sets(args.set)]
    if not raw_items:
        raise SystemExit("input contained no records")

    normalized, all_warnings = [], []
    for i, raw in enumerate(raw_items):
        rec, warns = normalize(raw)
        if raw.get("id"):
            rec["id"] = raw["id"]
        normalized.append(rec)
        all_warnings.append(warns)

    notes = allocate(normalized, load_records())

    print(f"new records : {len(normalized)}")
    for note in notes:
        print(f"  · {note}")
    for rec, warns in zip(normalized, all_warnings):
        print(f"\n{'='*66}")
        print(f"id={rec['id']}  登记号={bianhao(rec)}  {title(rec)}")
        for w in warns:
            print(f"  ⚠ {w}")
        print("-" * 66)
        print(record_text(rec))
    print("=" * 66)

    if not args.execute:
        print(f"\nPREVIEW ONLY — pass --execute to write {NEW_ITEMS_JSON}")
        return 0

    save_overlay(overlay + normalized)
    print(f"\n✓ overlay: {NEW_ITEMS_JSON}  ({len(overlay) + len(normalized)} new record(s), "
          f"merged total {len(load_records())})")

    if not args.build:
        print("\nnext:  python3 wwybsj_ingest.py --id <id> --execute"
              "  →  wwybsj_l0.py --registry-no <no> --execute  →  wwybsj_l1.py --execute"
              "\n(or re-run this with --build)")
        return 0

    return build([(r["id"], bianhao(r)) for r in normalized], args.no_l1)


if __name__ == "__main__":
    raise SystemExit(main())
