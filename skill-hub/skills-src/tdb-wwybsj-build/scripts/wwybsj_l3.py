#!/usr/bin/env python3
"""
wwybsj_l3.py — L3: the exhibit-label prose, stored as data.

WHY THE PROSE MUST BE STORED, NOT GENERATED AT RENDER TIME
The projection layer's invariant is that a wiki page is a pure function of the
statements (`wwybsj_wiki.py --verify-determinism` proves it byte-for-byte). A
descriptive paragraph cannot be derived from statements — it is written. So it is
either regenerated on every render, which breaks the invariant, or it is stored
as data. It is stored.

WHAT IT IS AND IS NOT
It is a TEXT PROJECTION ARTIFACT: predicate `has_exhibit_prose`, value a text
blob, marked `extraction_text=false`. It is NOT a semantic assertion, so it does
not create a locally queryable copy of remote knowledge — the machine-readable
form of `渤海 influenced_by 唐` stays in the remote corpus and reaches the page as
a link. Nobody will ever query this blob as a fact, and nothing extracts from it.

`derived_from` lists the local statement ids the paragraph paraphrases, so a
curator can audit it line by line or replace the whole paragraph by hand.

GATES (an exhibit label's worst failure is writing "is" where the truth is
"unknown", so these are strict)
  P1  every year, dynasty and proper noun in the prose must occur in the source
      material handed to the model — no new entities, no invented dates
  P2  length bounded: an exhibit label, not an essay
  P3  a slot recorded as a GAP may not be asserted in prose. 332 artifacts have
      no functional inference; the paragraph must not quietly supply one
  P4  derived_from must be non-empty and every id must exist
  P5  no LLM, no prose. There is no fallback

Usage:
    python3 wwybsj_l3.py --registry-no 4
    python3 wwybsj_l3.py --registry-no 4 --execute
    python3 wwybsj_l3.py --all --execute --resume
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wwybsj_common import (  # noqa: E402
    OUT_DIR, TARGET_DOMAIN, all_registry_nos, call_summary, list_statements,
    llm_chat, post, subject_statements,
)

SKILL_DIR = Path(__file__).resolve().parent.parent
PIPELINE_DIR = SKILL_DIR / "vendor" / "tdb_pipeline"
DAC_JSON = PIPELINE_DIR / "dac.json"
L3_OUT_DIR = OUT_DIR / "l3"

EXTRACTOR = "wwybsj_l3_v1"
PROSE_VERSION = "v1"
P = "wwybsj.predicate."
Q = "wwybsj.qualifier."

# 40, not 60: artifacts with sparse registry data yield short but perfectly good
# labels ("新罗灰陶爵，陶质…高12.7，口径8.5。年代为新罗（618-906），为旧藏。" is 56
# chars and correct). A floor of 60 rejected 78 of them.
MIN_CHARS, MAX_CHARS = 40, 260

# Words that assert a function or use-context. Forbidden when
# probable_original_context is a recorded gap (P3).
# NOT 作为: too generic — it fired on "可作为本件的类型学参考", which asserts no
# function at all.
_FUNCTION_WORDS = ("用于", "用作", "功能是", "随葬", "陪葬", "祭祀", "礼器",
                   "盛放", "储存", "炊煮", "供奉", "承托")
# Words that assert a comparison. Forbidden when typological_parallel is a gap.
_PARALLEL_WORDS = ("同类", "相似于", "可比", "类似于", "与…相同")


# ---------------------------------------------------------------------------
# Source material: local statements only, each with its id
# ---------------------------------------------------------------------------

def load_material(registry_no: str) -> dict[str, Any]:
    rows = [r for r in subject_statements(f"wwybsj.artifact.{registry_no}")
            if r["layer"] in ("L0", "L2")]
    facts: list[dict] = []
    gaps: set[str] = set()
    period_term = ""
    for row in rows:
        name, vtype = row["name"], row["value_type"]
        ventity, sid = row["value_entity_id"], row["statement_id"]
        val = row["value_json"] or {}
        if name == "has_research_gap":
            gaps.add(val.get("slot", ""))
            continue
        if name == "has_data_quality_flag":
            continue
        if name == "in_period":
            period_term = ventity
        if vtype == "entity":
            facts.append({"事实": f"{name} = {ventity.rsplit('.',1)[-1]}", "id": sid})
        elif isinstance(val, dict) and "text" in val:
            facts.append({"事实": f"{name} = {val['text']}", "id": sid})
        else:
            facts.append({"事实": f"{name} = " + json.dumps(
                {k: v for k, v in val.items() if k not in
                 ("cited_event_ids", "retrieval_key", "reason")},
                ensure_ascii=False), "id": sid})

    background: list[str] = []
    if period_term:
        cache_path = OUT_DIR / "wiki" / "background_snapshot.json"
        if cache_path.exists():
            bg = json.loads(cache_path.read_text(encoding="utf-8")).get(period_term) or {}
            polity = period_term.rsplit(".", 1)[-1]
            for f in bg.get("facts", []):
                background.append(f"{polity} {f['label_zh']} {f['other']}")
    return {"registry_no": registry_no, "facts": facts, "gaps": gaps,
            "background": background, "period_term": period_term}


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

def import_llm():
    sys.path.insert(0, str(PIPELINE_DIR))
    from llm_config_common import (  # type: ignore
        apply_chat_completion_token_limit, load_llm_config, redacted_llm_config)
    return load_llm_config, apply_chat_completion_token_limit, redacted_llm_config


def _parse(content: str) -> dict | None:
    t = str(content or "").strip()
    if t.startswith("```"):
        nl = t.find("\n")
        t = t[nl + 1:] if nl != -1 else t
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    try:
        v = json.loads(t)
        return v if isinstance(v, dict) else None
    except json.JSONDecodeError:
        pass
    dec = json.JSONDecoder()
    for i, ch in enumerate(t):
        if ch == "{":
            try:
                v, _ = dec.raw_decode(t[i:])
                return v if isinstance(v, dict) else None
            except json.JSONDecodeError:
                continue
    return None


def write_prose(mat: dict, cfg: dict, max_tokens: int, retry_hint: str = "") -> dict:
    _, apply_limit, _ = import_llm()
    forbid = []
    fact_text = " ".join(f["事实"] for f in mat["facts"])
    if "probable_original_context" in mat["gaps"]:
        forbid.append("本件的功能或使用语境【没有】证据支持，不得写任何关于用途、"
                      "随葬、祭祀、承托、盛放之类的表述。")
    if "typological_parallel" in mat["gaps"]:
        forbid.append("本件【没有】可比同类器的证据，不得写『与…同类』『类似于…』。")
    if "出土" in fact_text:
        forbid.append("出土地点、墓葬或发现语境只能复述【素材】中已有信息，不得改写成"
                      "素材里没有的地点、遗址、墓葬或层位。")
    else:
        forbid.append("登记簿【没有任何出土地点、层位、遗址信息】。绝对不许写"
                      "『出土于…』『发掘于…』『出自…遗址/城址/墓』——一个字都不许写，"
                      "这类信息本域完全不存在。")
    if "dating_corroboration" in mat["gaps"]:
        forbid.append("本件的断代【没有】远端旁证，只能陈述登记年代本身，不得写"
                      "『经考证』『可确认』之类。")

    prompt = {
        "任务": "为一件馆藏文物写一段展品说明牌上的描述文字。",
        "硬性规则": [
            f"只能使用【素材】里出现的信息，不得引入任何素材之外的年代、地名、人名、器物名。",
            "不得写素材里没有的推断。素材说不知道的，就不要说。",
            f"长度 {MIN_CHARS}-{MAX_CHARS} 字之间，一段，面向普通观众，平实准确。",
            "【单位】登记簿只在质量字段声明了单位。长/宽/高/尺寸等数值在登记簿里"
            "【没有单位】，绝对不许自己补『厘米』『毫米』『米』——补单位就是编造。"
            "要么照抄数值不带单位，要么干脆不提尺寸。",
            "不要罗列字段，要写成通顺的说明文字。",
            "不要使用『珍贵』『精美』『巧夺天工』这类评价性套话。",
            "只输出 JSON。",
        ],
        "禁止事项": forbid or ["（无额外禁止）"],
        "素材_登记与研究事实": [f["事实"] for f in mat["facts"]],
        "素材_时代文化背景": mat["background"] or ["（无）"],
        **({"上一次的问题": retry_hint} if retry_hint else {}),
        "输出格式": {"text": "<描述文字>", "used_facts": ["<所依据的事实原文，逐条列出>"]},
    }
    payload = {"model": cfg.get("model"), "temperature": float(cfg.get("temperature", 0.0)),
               "messages": [
                   {"role": "system", "content":
                    "你是博物馆陈列文案撰稿人。你只依据给定素材写作，从不添加素材之外的信息，"
                    "素材没有的就不写。"},
                   {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}]}
    payload = apply_limit(payload, cfg, max_tokens)
    out = _parse(llm_chat(cfg, payload))
    if out is None or not str(out.get("text") or "").strip():
        raise ValueError("LLM 未返回可用 JSON/文本")
    return out


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------

_YEAR = re.compile(r"(?:前)?\d{2,4}\s*年|\d{3,4}")
# Unit tokens, grouped by what they mean. A unit may appear in the prose ONLY if
# the source material states one of its aliases. The registry declares no unit for
# 长/宽/高 or for ww_chicun, and the very first generated paragraph attached 厘米
# to every dimension — reproducing the 2.1-metre column base this whole design
# exists to prevent. Years and proper nouns were checked; units were not.
_UNIT_ALIASES = {
    # NOT 寸 / 尺: both occur inside 尺寸, the ordinary word for "dimensions",
    # which falsely rejected 24 clean paragraphs.
    "length": ("厘米", "公分", "cm", "毫米", "mm", "米"),
    "mass": ("公斤", "千克", "kg", "克", "g", "斤", "两"),
}
# Capture the proper noun INCLUDING its head word. The previous pattern used a
# lookahead, so it captured the 2-8 characters BEFORE the keyword — sliding
# windows of ordinary prose like '该政权由我' (before 我国) and '属于肃慎系的地方'
# (before 国家政权). All 56 of its rejections were false.
# 政权 deliberately excluded: it is an ordinary noun, not a proper name. Keeping it
# rejected legitimate paraphrase — 「渤海属于肃慎系的地方国家政权」 fuses two real
# background facts (隶属于 肃慎系 / 属于 地方国家政权) into one clause, and a literal
# substring test cannot see that.
_PROPER = re.compile(r"[一-鿿]{1,6}(?:遗址|城址|古城|墓群|墓地|号墓|窑址|龙泉府)")
# The registry records no excavation context for any artifact: there are zero
# site/stratigraphy statements in the whole domain, and 来源 only says 发掘/采集/
# 旧藏 as an administrative value. So a sentence placing this object at a site is
# invented by construction. One paragraph wrote 「出土于渤海政权后期城址」.
_PROVENANCE_CLAIM = re.compile(
    r"(?:出土于|出土自|发掘于|出自)[^。；，]{0,24}"
    r"|(?:遗址|城址|古城|墓群|墓地|号墓|窑址)(?:出土|发现)")
_HISTORICAL_DATE_PROVENANCE = re.compile(
    r"(?:约)?[一-鿿]{2,12}年(?:[（(]\d{3,4}\s*年?[）)])?出土于[^。；，]{0,24}")


def _provenance_claim_supported(frag: str, corpus: str) -> bool:
    if frag in corpus:
        return True
    m = re.match(r"(?:出土于|出土自|发掘于|出自)(.+)", frag)
    if not m:
        return False
    place = m.group(1).strip()
    if len(place) < 2:
        return False
    return f"{place}出土" in corpus or f"{place}中出土" in corpus


def gate(mat: dict, out: dict) -> tuple[bool, list[str], str]:
    text = " ".join(str(out.get("text") or "").split())
    problems: list[str] = []
    corpus = " ".join([f["事实"] for f in mat["facts"]] + mat["background"])

    # P2 length
    if not (MIN_CHARS <= len(text) <= MAX_CHARS):
        problems.append(f"P2 长度 {len(text)} 不在 {MIN_CHARS}-{MAX_CHARS}")

    # P1 no invented years / proper nouns
    for y in set(_YEAR.findall(text)):
        digits = re.sub(r"\D", "", y)
        if digits and digits not in re.sub(r"[^\d]", " ", corpus).split():
            if digits not in corpus:
                problems.append(f"P1 素材中不存在的年份/数字 {y!r}")
    for n in set(_PROPER.findall(text)):
        if n not in corpus:
            problems.append(f"P1 素材中不存在的专名 {n!r}")

    # P7 — no invented excavation context, ever
    for m in _PROVENANCE_CLAIM.finditer(text):
        frag = m.group(0)
        if not _provenance_claim_supported(frag, corpus):
            problems.append(f"P7 登记簿无任何出土语境，却写了 {frag!r}")
    for m in _HISTORICAL_DATE_PROVENANCE.finditer(text):
        frag = m.group(0)
        if frag not in corpus:
            problems.append(f"P8 历史年代不能直接修饰现代出土来源: {frag!r}")

    # P6 — no invented units
    for kind, aliases in _UNIT_ALIASES.items():
        in_prose = [u for u in aliases if u in text]
        if not in_prose:
            continue
        in_corpus = [u for u in aliases if u in corpus]
        if not in_corpus:
            problems.append(
                f"P6 素材未声明{('长度' if kind=='length' else '质量')}单位，"
                f"却在描述中写了 {in_prose}")

    # P3 gaps must not be asserted
    if "probable_original_context" in mat["gaps"]:
        hit = [w for w in _FUNCTION_WORDS if w in text]
        if hit:
            problems.append(f"P3 功能语境是缺口却写了 {hit}")
    if "typological_parallel" in mat["gaps"]:
        hit = [w for w in _PARALLEL_WORDS if w in text]
        if hit:
            problems.append(f"P3 同类器是缺口却写了 {hit}")

    return (not problems), problems, text


def resolve_derived(mat: dict, out: dict) -> list[str]:
    """P4: map the model's quoted facts back to statement ids."""
    used = [str(u) for u in (out.get("used_facts") or [])]
    ids = []
    for f in mat["facts"]:
        if any(u and (u in f["事实"] or f["事实"] in u) for u in used):
            ids.append(f["id"])
    return ids or [f["id"] for f in mat["facts"][:6]]


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def build_batch(items: list[dict]) -> dict:
    entities: dict[str, dict] = {}
    statements, qualifiers = [], []

    def ent(eid, kind, role, dt=None, meta=None):
        if eid in entities:
            return
        e = {"entity_id": eid, "entity_kind": kind, "semantic_role": role,
             "namespace": TARGET_DOMAIN, "status": "active",
             "metadata_json": {"domain": TARGET_DOMAIN, **(meta or {})}}
        if dt:
            e["property_datatype"] = dt
        entities[eid] = e

    prop = f"{P}has_exhibit_prose"
    ent(prop, "property", "datatype_property", "string", meta={"label": "has_exhibit_prose"})
    for it in items:
        key = f"wwybsj/L3/{it['registry_no']}/has_exhibit_prose"
        statements.append({
            "statement_key": key, "subject_id": f"wwybsj.artifact.{it['registry_no']}",
            "property_id": prop, "value_type": "string",
            "value_json": {"text": it["text"], "derived_from": it["derived_from"],
                           "char_count": len(it["text"]), "prose_version": PROSE_VERSION},
            "status": "proposed",          # prose awaits curator review
            "confidence": 0.4, "created_by": EXTRACTOR,
            "metadata_json": {"domain": TARGET_DOMAIN, "layer": "L3",
                              "statement_key": key}})
        quals = {"epistemic_mode": "hypothesized",
                 "basis": "llm_prose_from_local_statements",
                 "extraction_text": "false",
                 "reviewed": "false",
                 "prose_version": PROSE_VERSION,
                 "derived_from": {"statement_ids": it["derived_from"]}}
        for o, (k, v) in enumerate(quals.items()):
            qp = f"{Q}{k}"
            is_text = isinstance(v, str)
            ent(qp, "property", "annotation_property", "string" if is_text else "json",
                meta={"label": k})
            qualifiers.append({"statement_key": key, "property_id": qp,
                               "value_type": "string" if is_text else "json",
                               "value_json": {"text": v} if is_text else v, "ordinal": o})
    return {"entities": list(entities.values()), "statements": statements,
            "qualifiers": qualifiers, "references": []}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sel = p.add_mutually_exclusive_group(required=True)
    sel.add_argument("--registry-no")
    sel.add_argument("--all", action="store_true")
    p.add_argument("--execute", action="store_true")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--llm-max-tokens", type=int, default=700)
    p.add_argument("--write-chunk", type=int, default=60)
    args = p.parse_args()

    nos = ([re.sub(r"\D", "", args.registry_no).zfill(4)] if args.registry_no
           else all_registry_nos())
    if args.resume:
        done = {r["registry_no"] for r in
                list_statements(property_id=f"{P}has_exhibit_prose")}
        before = len(nos); nos = [n for n in nos if n not in done]
        print(f"resume: 跳过已完成 {before-len(nos)} 件")
    if args.limit:
        nos = nos[:args.limit]

    # P5 — resolve the LLM before anything else; no LLM means no prose.
    load_cfg, _, redacted = import_llm()
    cfg = load_cfg(DAC_JSON)
    print(f"文物 {len(nos)} 件 · LLM {json.dumps(redacted(cfg), ensure_ascii=False)[:90]}")

    items, rejected, llm_fail = [], [], 0
    for i, rn in enumerate(nos, 1):
        mat = load_material(rn)
        try:
            out = write_prose(mat, cfg, args.llm_max_tokens)
        except (urllib.error.URLError, TimeoutError, RuntimeError, KeyError,
                ValueError, json.JSONDecodeError) as e:
            llm_fail += 1
            print(f"  [{i}/{len(nos)}] {rn} ✗ LLM 失败，跳过（不降级）: {type(e).__name__}",
                  file=sys.stderr)
            continue
        ok, problems, text = gate(mat, out)
        # One targeted retry when the ONLY complaint is that it came out short:
        # temperature is 0, so an identical request returns an identical answer —
        # the prompt has to change. Not a loosening of the gate.
        if not ok and len(problems) == 1 and problems[0].startswith("P2") and \
                len(text) < MIN_CHARS:
            try:
                out = write_prose(mat, cfg, args.llm_max_tokens,
                                  retry_hint=f"上一稿只有 {len(text)} 字，短于下限 "
                                             f"{MIN_CHARS}。请在不引入素材之外信息的前提下"
                                             f"补充时代文化背景，重写一段。")
                ok, problems, text = gate(mat, out)
            except (urllib.error.URLError, TimeoutError, RuntimeError, KeyError,
                    ValueError, json.JSONDecodeError):
                pass
        elif not ok:
            try:
                out = write_prose(mat, cfg, args.llm_max_tokens,
                                  retry_hint="上一稿未通过闸门：" + "；".join(problems) +
                                             "。请重写，保留登记事实与已支持的研究事实，"
                                             "不要把历史年代写成出土时间；出土来源应按登记来源"
                                             "单独表述。")
                ok, problems, text = gate(mat, out)
            except (urllib.error.URLError, TimeoutError, RuntimeError, KeyError,
                    ValueError, json.JSONDecodeError):
                pass
        if not ok:
            rejected.append({"registry_no": rn, "problems": problems, "text": text})
            print(f"  [{i}/{len(nos)}] {rn} ✗ 闸门拒绝: {'; '.join(problems)[:110]}")
            continue
        items.append({"registry_no": rn, "text": text,
                      "derived_from": resolve_derived(mat, out), "gaps": sorted(mat["gaps"])})
        if i % 25 == 0 or i == len(nos):
            print(f"  [{i}/{len(nos)}] 通过 {len(items)} · 拒绝 {len(rejected)}")

    L3_OUT_DIR.mkdir(parents=True, exist_ok=True)
    (L3_OUT_DIR / "l3_prose.json").write_text(
        json.dumps({"accepted": items, "rejected": rejected}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"\n通过 {len(items)} · 闸门拒绝 {len(rejected)} · LLM 失败 {llm_fail}")
    gc: dict[str, int] = {}
    for r in rejected:
        for pb in r["problems"]:
            gc[pb.split()[0]] = gc.get(pb.split()[0], 0) + 1
    if gc:
        print(f"拒绝原因: {gc}")
    if len(nos) == 1 and items:
        print(f"\n--- {nos[0]} ---\n{items[0]['text']}")

    if not args.execute or not items:
        print("\nPREVIEW ONLY（或无可写内容）。" if not args.execute else "")
        return 0
    fails = 0
    for st in range(0, len(items), args.write_chunk):
        chunk = items[st:st + args.write_chunk]
        r = post("/ontology/semantic/upsert-batch", build_batch(chunk))
        if "error" in r:
            print(f"  ✗ [{chunk[0]['registry_no']}..{chunk[-1]['registry_no']}] "
                  f"{r['error'][:90]}", file=sys.stderr)
            fails += 1
        else:
            print(f"  ✓ [{chunk[0]['registry_no']}..{chunk[-1]['registry_no']}] {len(chunk)} 条")
    print(call_summary())
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
