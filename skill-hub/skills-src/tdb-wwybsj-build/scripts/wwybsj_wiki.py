#!/usr/bin/env python3
"""
wwybsj_wiki.py — the projection layer: one exhibit page per artifact.

A wiki page here is a PURE FUNCTION of (local statements, remote background
snapshot). It is not a source of knowledge. Delete every page, re-render, and the
output must be byte-identical — `--verify-determinism` checks exactly that.

WHY THIS DISCIPLINE
The previous pipeline wrote 2385 wiki pages into this domain, of which 2375 were
junk: it promoted registry field VALUES into standalone pages with slugs like
`8-600-kg`, `二级`, `残缺，状态稳定，不需修复`, `正面为凸起的兽头` — and stamped
them `authority_kind=accepted_ontology`, i.e. dressed compiled output up as
ontological authority. Only 2 real artifact pages existed. So:

  * one page per ARTIFACT, never per field value
  * authority_kind = compiled_summary — this is a projection, not authority
  * no prose that cannot be traced to a statement (LLM prose is L3 data, and it
    is rendered from a statement, never invented at render time)

BACKGROUND IS LINKED, NOT COPIED
The polity/dynasty background comes from the remote corpus through the L1 anchor
and is rendered as `[[archeology:concept:<uuid>|渤海]]` plus a whitelisted set of
facts. It is never written into this database.

The whitelist is not cosmetic. L1 anchors control WHICH remote concepts we point
at; they cannot control what the remote graph says about them. Observed live:
`渤海海面封冻 -associated_with-> 渤海` hangs off the very concept we keep
(3f88ffe8, the polity) — a bad edge in the remote graph. Filtering by predicate
and direction at render time is the only place to stop it.

WHAT IT REFUSES TO HIDE
An exhibit label's worst failure is writing "is" where the truth is "unknown".
335 artifacts have no dating corroboration and 332 no functional inference, so
every page ends with a data section stating its own gaps and quality flags.

Usage:
    python3 wwybsj_wiki.py --registry-no 4                  # render to stdout
    python3 wwybsj_wiki.py --registry-no 4 --execute
    python3 wwybsj_wiki.py --all --execute
    python3 wwybsj_wiki.py --refresh-background             # re-snapshot remote
    python3 wwybsj_wiki.py --verify-determinism
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wwybsj_common import (  # noqa: E402
    OUT_DIR, SOURCE_BASE, SOURCE_DOMAIN, TARGET_DOMAIN, call_summary,
    all_registry_nos, list_statements, post, sget, statement_references,
    subject_statements, wiki_page, wiki_page_slugs,
)

WIKI_OUT_DIR = OUT_DIR / "wiki"
BACKGROUND_CACHE = WIKI_OUT_DIR / "background_snapshot.json"
RENDERER = "wwybsj_wiki_v1"

# Outbound predicates that say something about what a polity/class IS. Anything
# else the remote graph attaches is not background — see the module docstring.
BG_OUT_WHITELIST = {
    "instance_of": "属于", "is_a": "属于", "defined_as": "定义为",
    "influenced_by": "受影响于", "characterized_by": "特征", "has_feature": "特征",
    "consists_of": "包含", "precedes": "早于", "located_in": "地域",
    "located_at": "地域", "produced_by_culture": "由…创造",
    "attributed_to_culture": "文化归属", "uses_method": "采用",
    "introduced_to": "传播至", "distinguished_from": "区别于",
}
# Inbound edges are mostly noise; only these carry real membership meaning.
BG_IN_WHITELIST = {"consists_of": "隶属于", "precedes": "晚于", "instance_of": "实例包含"}
BG_FACTS_PER_CONCEPT = 8


# ---------------------------------------------------------------------------
# Read the three layers back out
# ---------------------------------------------------------------------------

def load_artifact(registry_no: str) -> dict[str, Any]:
    rows = subject_statements(f"wwybsj.artifact.{registry_no}")
    art: dict[str, Any] = {"registry_no": registry_no, "single": {}, "multi": {},
                           "l2": [], "gaps": [], "flags": [], "prose": None}
    for row in rows:
        name = row["name"]
        value = (row["value_entity_id"] if row["value_type"] == "entity"
                 else row["value_json"])
        item = {"value": value,
                "registry_field": row["qualifiers"].get("registry_field", "") or "",
                "statement_id": row["statement_id"]}
        if name == "has_data_quality_flag":
            art["flags"].append(value)
        elif name == "has_research_gap":
            art["gaps"].append(value)
        elif name in {"typological_parallel", "dating_corroboration",
                      "probable_original_context"}:
            art["l2"].append({"slot": name, **item})
        elif name == "has_exhibit_prose":
            art["prose"] = value
        elif name in {"made_of", "has_dimension"}:
            art["multi"].setdefault(name, []).append(item)
        else:
            art["single"][name] = item
    return art


def load_passages(statement_ids: list[str]) -> dict[str, dict]:
    """
    The remote passage behind each L2 statement, one /statement/provenance call
    apiece. There is no bulk reference endpoint, so this is per statement — cheap
    here because an artifact has at most three L2 slots.
    """
    out: dict[str, dict] = {}
    for sid in statement_ids:
        for ref in statement_references(sid):
            if ref.get("property_id") != "wwybsj.ref.remote_passage":
                continue
            v = ref.get("value") or {}
            out[sid] = {"stream_id": v.get("stream_id", ""),
                        "event_id": v.get("event_id", ""),
                        "source": v.get("source", "") or "",
                        "span": (ref.get("source_span") or "")[:400]}
            break
    return out


def load_anchors(term_ids: list[str]) -> dict[str, list[dict]]:
    """L1 anchors for the given terms. 49 anchors domain-wide, so fetch all once."""
    if not term_ids:
        return {}
    want = set(term_ids)
    out: dict[str, list[dict]] = {}
    for r in list_statements(property_id="wwybsj.predicate.aligned_to"):
        if r["subject_id"] in want:
            out.setdefault(r["subject_id"], []).append(r["value_json"])
    return out


# ---------------------------------------------------------------------------
# Remote background — snapshotted, whitelisted, never copied into statements
# ---------------------------------------------------------------------------

def load_background_cache() -> dict:
    if BACKGROUND_CACHE.exists():
        return json.loads(BACKGROUND_CACHE.read_text(encoding="utf-8"))
    return {}


def save_background_cache(cache: dict) -> None:
    WIKI_OUT_DIR.mkdir(parents=True, exist_ok=True)
    BACKGROUND_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1),
                                encoding="utf-8")


def _label(concept_id: str, memo: dict) -> str:
    if concept_id in memo:
        return memo[concept_id]
    got = sget("/ontology/concept/get", {"concept_id": concept_id})
    payload = got.get("concept", got) or {}
    memo[concept_id] = payload.get("canonical_name") or concept_id[:8]
    return memo[concept_id]


def snapshot_background(concept_ids: list[str], memo: dict) -> list[dict]:
    """Whitelisted facts for one anchor cluster, deduplicated and ordered."""
    seen: set[tuple] = set()
    facts: list[dict] = []
    for cid in concept_ids:
        for direction, param, table in (("out", "src_concept_id", BG_OUT_WHITELIST),
                                        ("in", "dst_concept_id", BG_IN_WHITELIST)):
            r = sget("/ontology/fact/list", {param: cid, "limit": BG_FACTS_PER_CONCEPT})
            if "error" in r:
                continue
            for f in r.get("facts", []):
                pred = f.get("predicate", "")
                if pred not in table:
                    continue
                other_id = f["dst_concept_id"] if direction == "out" else f["src_concept_id"]
                other = _label(other_id, memo)
                key = (direction, pred, other)
                if key in seen:
                    continue
                seen.add(key)
                facts.append({"direction": direction, "predicate": pred,
                              "label_zh": table[pred], "other": other,
                              "other_concept_id": other_id, "source_concept_id": cid})
    facts.sort(key=lambda f: (f["direction"] != "out", f["predicate"], f["other"]))
    return facts


def ensure_background(term_labels: dict[str, list[str]], refresh: bool) -> dict:
    """term_id -> {concept_ids, facts}. Snapshotted so rendering is reproducible."""
    cache = {} if refresh else load_background_cache()
    memo: dict[str, str] = cache.get("_labels", {})
    for term_id, concept_ids in term_labels.items():
        if term_id in cache and not refresh:
            continue
        print(f"  [背景快照] {term_id}（{len(concept_ids)} 个远端概念）",
              file=sys.stderr, flush=True)
        cache[term_id] = {"concept_ids": concept_ids,
                          "facts": snapshot_background(concept_ids, memo)}
        cache["_labels"] = memo
        save_background_cache(cache)
    return cache


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_BIB_TAIL = re.compile(r"(?:[\u4e00-\u9fff]{2,4}[：:]\s*《[^》]+》\s*[，,])")


def trim_span(span: str) -> str:
    """
    Cut a cited passage before its bibliography tail.

    The corpus appends reference lists to prose chunks (『…珍贵实物依据。 王健群：
    《好太王碑研究》，吉林人民出版社，1984。…』). Keeping them is harmless for
    machine use but makes an exhibit page look like a footnote dump.
    """
    m = _BIB_TAIL.search(span or "")
    out = (span[:m.start()] if m else span).rstrip()
    return out + ("…" if m or len(span) >= 400 else "")


def _text(item: dict | None) -> str:
    if not item:
        return ""
    v = item["value"]
    return v.get("text", "") if isinstance(v, dict) else str(v)


def slug_for(registry_no: str, name: str) -> str:
    return "ww-" + registry_no + "-" + re.sub(r"[\s/\\|#\[\]]+", "-", name or "unnamed")


def render(art: dict, anchors: dict, background: dict,
           passages: dict) -> tuple[str, dict[str, Any]]:
    s, m = art["single"], art["multi"]
    name = _text(s.get("has_name")) or f"文物 {art['registry_no']}"
    rn = art["registry_no"]
    L: list[str] = [f"# {name}（藏品总登记号 {rn}）", ""]

    # ---- 描述：L3 prose, rendered FROM A STATEMENT so the page stays a pure
    # function. Marked non-extractable so it can never feed back into extraction.
    if art.get("prose"):
        pr = art["prose"]
        L += ["## 描述", "", "<!-- tdb:extraction_text=false -->",
              pr.get("text", ""), "",
              f"*本段为依据本域断言生成的派生文字（{len(pr.get('derived_from') or [])} 条断言），"
              f"未经策展人复核；机器可读的事实见下列各节。*", ""]

    # ---- 登记信息：L0 only, every row naming the registry field it came from ----
    L += ["## 登记信息", "",
          "本节全部来自藏品登记簿，逐条标注来源字段；未记载的项如实留空。", "",
          "| 项目 | 内容 | 登记字段 |", "|---|---|---|"]
    def row(label: str, key: str) -> None:
        it = s.get(key)
        if it and _text(it):
            L.append(f"| {label} | {_text(it)} | `{it['registry_field']}` |")
    row("名称", "has_name"); row("原名", "has_original_name")
    cat = s.get("instantiates")
    if cat:
        L.append(f"| 类别 | {cat['value'].rsplit('.',1)[-1]} | `{cat['registry_field']}` |")
    mats = [x["value"].rsplit(".", 1)[-1] for x in m.get("made_of", [])]
    if mats:
        L.append(f"| 质地 | {'、'.join(mats)} | `{m['made_of'][0]['registry_field']}` |")
    d = s.get("dated_to")
    if d:
        v = d["value"]
        lit = v.get("registry_literal", "")
        if v.get("start_year") is None:
            yrs = "（登记簿未给出年份区间）"
        elif all(str(abs(v[k])) in lit for k in ("start_year", "end_year")):
            yrs = ""          # the literal already shows the years; do not repeat them
        else:
            yrs = f" · 可比区间 {v['start_year']}—{v['end_year']}"
        L.append(f"| 年代 | {lit}{yrs} | `{d['registry_field']}` |")
    qty = s.get("has_quantity")
    if qty:
        L.append(f"| 数量 | {qty['value'].get('count')} | `{qty['registry_field']}` |")
    mass = s.get("has_mass")
    if mass:
        v = mass["value"]
        L.append(f"| 质量 | {v['value']} {v.get('unit') or '（单位缺失）'} | `{mass['registry_field']}` |")
    dims = m.get("has_dimension", [])
    if dims:
        parts = [f"{x['value']['label_zh']} {x['value']['value']}" for x in dims]
        L.append(f"| 尺寸（结构化） | {'、'.join(parts)}（**登记簿未声明单位**） | `ww_chang/ww_kuan/ww_gao` |")
    row("尺寸（登记原文）", "has_dimension_note")
    row("完残状况", "has_completeness_note"); row("保存状态", "has_conservation_state")
    for lbl, k in (("完残程度", "has_completeness"), ("级别", "has_grade"),
                   ("入藏途径", "acquired_by")):
        it = s.get(k)
        if it:
            L.append(f"| {lbl} | {it['value'].rsplit('.',1)[-1]} | `{it['registry_field']}` |")
    L.append("")

    # ---- 时代与文化背景：links + whitelisted remote facts, nothing copied ----
    L += ["## 时代与文化背景", ""]
    per = s.get("in_period")
    used_concepts = 0
    if not per:
        L += ["登记簿未记载年代，本节无内容。", ""]
    else:
        term_id = per["value"]
        polity = term_id.rsplit(".", 1)[-1]
        bg = background.get(term_id) or {}
        cids = bg.get("concept_ids", [])
        used_concepts = len(cids)
        anchor_links = " · ".join(
            f"[[{SOURCE_DOMAIN}:concept:{c}|{polity}]]" for c in cids) or "（无锚点）"
        L += [f"本件属 **{polity}**。以下背景不存于本域，经锚点解引用自 `{SOURCE_DOMAIN}` "
              f"语料，随该语料更新而变：", "", f"- 锚点：{anchor_links}", ""]
        facts = bg.get("facts", [])
        if facts:
            L += ["| 关系 | 对象 |", "|---|---|"]
            for f in facts:
                other = f"[[{SOURCE_DOMAIN}:concept:{f['other_concept_id']}|{f['other']}]]"
                # inbound edges must still name the subject, or the row reads
                # backwards: 肃慎系 -consists_of-> 渤海 means 渤海 隶属于 肃慎系
                arrow = f"{polity} {f['label_zh']}"
                L.append(f"| {arrow} | {other} |")
            L.append("")
        else:
            L += ["远端语料对该时期没有通过白名单的背景事实。", ""]

    # ---- 研究线索：L2, each with its remote passage ----
    L += ["## 同类器与研究线索", ""]
    if not art["l2"]:
        L += ["本件没有通过证据闸门的研究性断言。参见下节「数据说明」。", ""]
    else:
        SLOT_ZH = {"typological_parallel": "可比同类器",
                   "dating_corroboration": "断代旁证",
                   "probable_original_context": "可能的原始语境"}
        MODE_ZH = {"attributed": "据远端原文", "hypothesized": "推测"}
        for a in sorted(art["l2"], key=lambda x: x["slot"]):
            v = a["value"]
            p = passages.get(a["statement_id"], {})
            mode = "hypothesized" if a["slot"] == "probable_original_context" else "attributed"
            # stance is a COMPUTED interval comparison, not an LLM opinion, and
            # `undetermined` is a legitimate outcome for the 104 citations that
            # state no years at all. Rendering it as 支持/质疑 would fake certainty.
            STANCE_ZH = {"supports": "支持登记断代", "questions": "质疑登记断代",
                         "partial_overlap": "与登记断代部分重叠",
                         "undetermined": "无法判定与登记断代的关系"}
            stance = f"（{STANCE_ZH.get(v.get('stance'), v.get('stance',''))}）" if v.get("stance") else ""
            L += [f"### {SLOT_ZH[a['slot']]}{stance}", "",
                  f"> {v.get('object_surface','')}", "",
                  f"- 性质：{MODE_ZH[mode]}（{mode}）；证据层级：`{v.get('evidence_scope','')}`"]
            if v.get("stance_explanation"):
                L.append(f"- 断代比对：{v['stance_explanation']}"
                         f"（依据：{v.get('stance_basis','')}）")
            L += [
                  f"- 出处：{p.get('source','?')} "
                  f"[[{SOURCE_DOMAIN}:event:{p.get('stream_id','')}#{p.get('event_id','')}|远端原文]]"]
            if p.get("span"):
                L += ["", "  <!-- tdb:extraction_text=false -->",
                      f"  原文片段：{trim_span(p['span'])}"]
            L.append("")

    # ---- 数据说明：the gaps, stated plainly ----
    L += ["## 数据说明", "",
          "本页为 L0/L1/L2 的确定性投影，不含任何无法追溯到断言的表述。", ""]
    if art["flags"]:
        L += ["**数据质量标记**", ""]
        for f in sorted(art["flags"], key=lambda x: x.get("code", "")):
            L.append(f"- `{f.get('code')}`：{f.get('note','')}")
        L.append("")
    if art["gaps"]:
        GAP_ZH = {"insufficient_evidence": "远端证据不足",
                  "rejected_by_gate": "候选证据被闸门拒绝",
                  "no_on_topic_candidates": "检索无切题候选"}
        L += ["**研究缺口**（查过但没有结论，与「尚未查」不同）", ""]
        for g in sorted(art["gaps"], key=lambda x: x.get("slot", "")):
            gate = f"（{g.get('gate')}）" if g.get("gate") else ""
            L.append(f"- `{g.get('slot')}`：{GAP_ZH.get(g.get('reason'), g.get('reason'))}{gate}")
        L.append("")
    L += [f"<!-- rendered_by={RENDERER} remote={SOURCE_BASE} "
          f"remote_domain={SOURCE_DOMAIN} background_concepts={used_concepts} -->"]

    content = "\n".join(L).rstrip() + "\n"
    tags = [t for t in [
        (s.get("in_period") or {}).get("value", "").rsplit(".", 1)[-1] or None,
        (s.get("instantiates") or {}).get("value", "").rsplit(".", 1)[-1] or None,
        (s.get("has_grade") or {}).get("value", "").rsplit(".", 1)[-1] or None,
    ] if t]
    # Confidence reflects how much of the page rests on evidence, not a guess.
    filled = len(art["l2"])
    meta = {"slug": slug_for(rn, name), "title": f"{name}（藏品总登记号 {rn}）",
            "tags": tags + mats,
            "confidence": round(min(0.95, 0.5 + 0.1 * filled), 2),
            "content": content}
    return content, meta


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build(registry_nos: list[str], refresh_bg: bool) -> list[dict]:
    arts = [load_artifact(rn) for rn in registry_nos]
    term_ids = sorted({a["single"]["in_period"]["value"]
                       for a in arts if a["single"].get("in_period")})
    anchors = load_anchors(term_ids)
    needed = {t: sorted({c for anc in anchors.get(t, []) for c in anc.get("concept_ids", [])})
              for t in term_ids}
    background = ensure_background(needed, refresh_bg)
    pages = []
    for art in arts:
        passages = load_passages([a["statement_id"] for a in art["l2"]])
        _, meta = render(art, anchors, background, passages)
        pages.append(meta)
    return pages


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sel = p.add_mutually_exclusive_group(required=True)
    sel.add_argument("--registry-no")
    sel.add_argument("--all", action="store_true")
    sel.add_argument("--verify-determinism", action="store_true",
                     help="重渲染并与库中内容逐字节比对")
    p.add_argument("--execute", action="store_true")
    p.add_argument("--refresh-background", action="store_true")
    args = p.parse_args()

    if args.verify_determinism:
        # /wiki/pages lists summaries only, so the content of each page has to
        # be fetched to hash it — one GET per page, no bulk content endpoint.
        slugs = wiki_page_slugs()
        if not slugs:
            print("库中没有 wwybsj wiki 页，先写入再验证。")
            return 1
        stored = {}
        for i, sl in enumerate(slugs, 1):
            pg = wiki_page(sl)
            if pg is None:
                continue
            stored[sl] = hashlib.md5(pg["content"].encode()).hexdigest()
            if i % 50 == 0:
                print(f"  读取 {i}/{len(slugs)} 页…", file=sys.stderr)
        pages = build(all_registry_nos(), refresh_bg=False)
        fresh = {m["slug"]: hashlib.md5(m["content"].encode()).hexdigest() for m in pages}
        same = [s for s in stored if s in fresh and stored[s] == fresh[s]]
        diff = [s for s in stored if s in fresh and stored[s] != fresh[s]]
        only_db = sorted(set(stored) - set(fresh))
        only_new = sorted(set(fresh) - set(stored))
        print(f"库中 {len(stored)} 页 · 重渲染 {len(fresh)} 页")
        print(f"逐字节一致 {len(same)} · 内容不同 {len(diff)} · 仅库中有 {len(only_db)} · 仅新渲染有 {len(only_new)}")
        for s in diff[:5]:
            print(f"  ✗ {s}")
        ok = not diff and not only_db and not only_new
        print("\n✓ 确定性验证通过：页面是断言的纯函数。" if ok
              else "\n✗ 确定性验证失败——页面含无法从断言复现的内容。")
        return 0 if ok else 1

    nos = all_registry_nos() if args.all else [
        re.sub(r"\D", "", args.registry_no).zfill(4)]
    pages = build(nos, args.refresh_background)

    if not args.execute:
        print(pages[0]["content"] if len(pages) == 1
              else f"渲染 {len(pages)} 页（预览模式不写入）")
        return 0

    errors = 0
    for i, meta in enumerate(pages, 1):
        r = post("/wiki/page", {
            "domain": TARGET_DOMAIN, "slug": meta["slug"], "title": meta["title"],
            "content": meta["content"], "page_type": "entity",
            "knowledge_level": "fact_like",
            # compiled_summary, NOT accepted_ontology: this is a projection.
            "authority_kind": "compiled_summary",
            "tags": meta["tags"], "confidence": meta["confidence"],
            "source_ref": f"{RENDERER}:wwybsj.artifact.{meta['slug'].split('-')[1]}",
        })
        if "error" in r:
            print(f"  ✗ {meta['slug']}: {r['error'][:100]}", file=sys.stderr)
            errors += 1
        elif i % 50 == 0 or i == len(pages):
            print(f"  ✓ {i}/{len(pages)} 页")
    print(call_summary())
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
