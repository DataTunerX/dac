#!/usr/bin/env python3
"""
wwybsj_l2.py — L2 builder: research assertions grounded in remote source text.

L2 answers what L0 and L1 cannot: research claims ABOUT THIS MUSEUM'S ARTIFACTS.
Every such claim is `attributed` (or `hypothesized`) and every one of them cites a
remote passage by stream_id + event_id + source_span.

SCOPE: ARTIFACT SUBJECTS ONLY
An earlier draft of the design also proposed term-subject slots
(technique_tradition / deterioration_mechanism / typical_provenance). That was
wrong and is dropped: if an assertion's subject is a general concept, it belongs
to the `archeology` domain, and extracting it from remote text into this database
is just copying by another route. The line is —

    subject is a local artifact  -> L2 stores it here
    subject is a remote concept  -> reach it through the L1 anchor, do not extract

SLOT FILLING, NOT FREE EXTRACTION
Never ask an LLM to "extract triples from this text": free extraction cannot
constrain the subject, which is how `该藏品 --has_condition--> 残缺` (an
unresolved anaphora) got written by the old pipeline. Instead each slot is a
question with a closed candidate list, and `insufficient_evidence` is a
first-class answer.

RETRIEVAL IS KEYED, AND THE STATEMENTS SAY SO
465 artifacts collapse into 71 distinct (category | material | era) retrieval
keys, so retrieval runs 71 times instead of 465. The consequence is that the
evidence is CLASS-LEVEL, not about the individual object — every statement
records `evidence_scope: class_level` so nobody can mistake it for direct
evidence. This is also why `probable_original_context` is `hypothesized`: the
passage speaks about the class, and applying it to one object is an extra step.

HARD GATES (all enforced before writing; see docs/layered-ontology.md §4.4)
  G1  every cited candidate id must exist in the candidate list for that slot
  G2  the object surface must literally occur in the cited passage
  G3  attributed/hypothesized rows must carry stream_id + event_id + source_span
  G4  candidates are deduplicated by event_id (two hits on one passage are NOT
      two independent sources — the old pipeline produced "[search:004,
      search:007]" for one event and called it corroboration)
  G5  noise is not citable: TOC pages, footnote blocks, and anything the corpus
      itself marks `extraction_text=false`
  G6  no LLM, no writing. There is no mechanical fallback, ever
  G7  zero on-topic candidates -> record a research gap, never guess
  G8  the slot's declared epistemic_mode is forced, not suggested

Prerequisite: L0 and L1 must be written.

Usage:
    python3 wwybsj_l2.py --registry-no 8                 # one artifact, preview
    python3 wwybsj_l2.py --registry-no 8 --execute
    python3 wwybsj_l2.py --all --execute                 # 71 retrievals, 465 fills
    python3 wwybsj_l2.py --all --execute --resume        # skip artifacts already done
    python3 wwybsj_l2.py --retrieval-only                # warm the candidate cache
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
import time
import urllib.error
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wwybsj_common import (  # noqa: E402
    OUT_DIR, SOURCE_BASE, SOURCE_DOMAIN, TARGET_DOMAIN, list_statements,
    call_summary, llm_chat, post, spost,
)
from wwybsj_research import MIN_RAG_SCORE, is_noise, relevance  # noqa: E402

SKILL_DIR = Path(__file__).resolve().parent.parent
PIPELINE_DIR = SKILL_DIR / "vendor" / "tdb_pipeline"
DAC_JSON = PIPELINE_DIR / "dac.json"

EXTRACTOR = "wwybsj_l2_v1"
L2_OUT_DIR = OUT_DIR / "l2"
CANDIDATE_CACHE = L2_OUT_DIR / "candidate_cache.json"
PROGRESS_PATH = L2_OUT_DIR / "progress.json"

P = "wwybsj.predicate."
Q = "wwybsj.qualifier."
REF_PASSAGE = "wwybsj.ref.remote_passage"

# Slots. Every one takes a local artifact as subject.
SLOTS: dict[str, dict[str, Any]] = {
    "typological_parallel": {
        "epistemic_mode": "attributed",
        "requires_scope": "form_level",
        "question": "远端原文中，有哪个器物、遗址或工艺语境可以与本件文物相比较？",
        "guidance": "只有当原文明确谈及与本件同类别、同材质或同时代的器物/语境时才填。"
                    "不要因为原文提到了这个时代就填。",
    },
    "dating_corroboration": {
        # dating is a property of the class, so class-level evidence is legitimate here
        "epistemic_mode": "attributed",
        "requires_scope": "class_level",
        "question": "远端原文中是否有支持或质疑登记断代的证据？",
        "guidance": "必须能指出原文里的具体年代表述或分期依据。若原文与登记年代冲突，"
                    "stance 填 questions 并说明冲突。",
        "extra_keys": {"stance": ["supports", "questions"]},
    },
    "probable_original_context": {
        "epistemic_mode": "hypothesized",
        "requires_scope": "form_head_level",
        "question": "根据原文对该类器物的描述，本件文物可能的原始功能或使用语境是什么？",
        "guidance": "原文谈的是类别层面，套到这一个体上是推断，因此这一槽位永远是"
                    "hypothesized。不要写成事实。",
    },
}

# The corpus wraps its own non-extractable blocks in HTML comments, e.g.
#   <!-- tdb:block_type=footnote citation_context=true extraction_text=false -->
# A chunk can be mostly real prose with a footnote appended, so the marked
# segments are STRIPPED and the remainder is judged. Dropping the whole chunk on
# a marker anywhere in it threw away the best evidence in the corpus (the
# 《太平御览》引《周书》「神农耕而作陶」 passage was rejected that way).
_TDB_COMMENT = re.compile(r"<!--\s*tdb:.*?-->", re.S)
_FOOTNOTE_SUP = re.compile(r"<sup>[^<]{0,12}</sup>")
_CITATION_RE = re.compile(r"《[^》]{2,60}》")
_PIPE_LINE = re.compile(r"^\s*\|.*\|\s*$", re.M)

# Text left after stripping marked blocks must still be a real paragraph.
MIN_CITABLE_CHARS = 200
# Share of characters sitting INSIDE 《》. A bibliography is mostly titles; prose
# that cites heavily is still prose. Measured on real chunks: the substantive
# 《太平御览》引《周书》「神农耕而作陶」 passage has 8 citations but only 4.1% of its
# characters inside them, and a citations-per-char rule rejected it. The
# char-share separates the two cleanly.
MAX_CITATION_CHAR_SHARE = 0.25
# A whole query term appearing exactly once in 2500 characters is a passing
# mention, not a topic.
MIN_WHOLE_TERM_HITS = 2


def strip_non_extractable(text: str) -> str:
    """Remove what the corpus marks as non-extractable, keep the prose."""
    out = _TDB_COMMENT.sub(" ", text or "")
    out = _FOOTNOTE_SUP.sub(" ", out)
    return out


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Read L0/L1 back out — L2 never re-reads the registry JSON
# ---------------------------------------------------------------------------

def load_artifacts() -> list[dict[str, Any]]:
    """
    One row per artifact, assembled from five L0 predicates read via the gateway.

    The predicates are fetched whole rather than per artifact: five paged calls
    beat 465 subject lookups, and the join that used to be a lateral subquery is
    just a dict lookup here.
    """
    anchors = {r["subject_id"]: r for r in
               list_statements(property_id=f"{P}has_registry_no")}

    def by_subject(pred: str) -> dict[str, dict]:
        return {r["subject_id"]: r for r in list_statements(property_id=f"{P}{pred}")}

    names = by_subject("has_name")
    cats = by_subject("instantiates")
    dated = by_subject("dated_to")
    origs = by_subject("has_original_name")

    materials: dict[str, set[str]] = {}
    for r in list_statements(property_id=f"{P}made_of"):
        materials.setdefault(r["subject_id"], set()).add(
            r["value_entity_id"].replace("wwybsj.term.material.", ""))

    out = []
    for subject, a in anchors.items():
        d = (dated.get(subject) or {}).get("value_json") or {}
        cat = (cats.get(subject) or {}).get("value_entity_id", "")
        mat = "+".join(sorted(materials.get(subject, ())))
        era = d.get("era_label") or ""
        out.append({
            "subject_id": subject,
            "registry_no": a["registry_no"],
            "name": ((names.get(subject) or {}).get("value_json") or {}).get("text", ""),
            "category": cat.replace("wwybsj.term.category.", ""),
            "material": mat,
            "era": era,
            "era_literal": d.get("registry_literal") or "",
            "original_name": ((origs.get(subject) or {}).get("value_json") or {}).get("text", ""),
            "retrieval_key": f"{cat.replace('wwybsj.term.category.', '')}|{mat}|{era or '∅'}",
        })
    out.sort(key=lambda a: a["registry_no"])
    return out


# ---------------------------------------------------------------------------
# Retrieval — keyed, deduplicated, noise-filtered
# ---------------------------------------------------------------------------

def is_citable(text: str) -> tuple[bool, str, str]:
    """
    G5. Returns (ok, reason, prose) where `prose` is the citable remainder.

    A passage that fails this must never be cited as evidence.
    """
    prose = strip_non_extractable(text)

    # Markdown tables: the corpus's OCR turns 器物登记表/陶色统计表 into pipe grids
    # that score highly on any query and carry no claims.
    pipe_lines = _PIPE_LINE.findall(prose)
    if pipe_lines and sum(len(l) for l in pipe_lines) > 0.4 * max(len(prose), 1):
        return False, "markdown_table", prose

    if is_noise(prose):
        return False, "toc_or_short_block", prose
    if len(prose.strip()) < MIN_CITABLE_CHARS:
        return False, "too_little_prose_after_stripping", prose

    cited_chars = sum(len(c) for c in _CITATION_RE.findall(prose))
    if cited_chars / max(len(prose), 1) > MAX_CITATION_CHAR_SHARE:
        return False, "bibliography_like", prose

    return True, "", prose


# Registry descriptors that are not form signals. 残/片 describe completeness,
# not shape, and they generate junk grams like 唐残 / 残三 / 座残.
_NON_FORM_CHARS = "残片件个组套约计段块半部余存"


def topic_terms(artifact: dict) -> tuple[list[str], list[str], list[str]]:
    """
    (form_head_terms, form_terms, class_terms) — three tiers of topical signal.

    form_head  the object's SHAPE, from the tail of its name (柱座 / 瓦当 / 带钩).
               A claim about what the object was FOR needs this tier: 三彩 is a
               glaze technique, and a passage saying 三彩 finds are mostly burial
               goods says nothing about a column base.
    form       any other distinctive name term (三彩 / 莲纹) — good enough for a
               typological comparison, which is about technique and decor.
    class      category / material / era only.

    The full artifact name must NEVER be used as a search term: 渤海绿釉柱础护圈
    never appears verbatim in a textbook, so testing for it always fails
    (wwybsj_research.relevance documents the same trap). It is decomposed into
    CJK 2-grams instead, minus the class terms, leaving the FORM signal
    (三彩 / 莲纹 / 柱座) that distinguishes an architectural component from a
    cooking vessel of the same material.

    Single-character terms are dropped: 陶 / 石 / 金 match inside unrelated words.
    """
    def grams(text: str) -> set[str]:
        out: set[str] = set()
        for run in re.findall(r"[一-鿿]{2,}", text or ""):
            for i in range(len(run) - 1):
                out.add(run[i:i + 2])
        return out

    class_terms = sorted({t for t in
                          re.split(r"[、,，/\s]+", artifact["category"] or "")
                          if len(t) >= 2} |
                         {t for t in (artifact["material"] or "").split("+")
                          if len(t) >= 2} |
                         ({artifact["era"]} if len(artifact["era"] or "") >= 2 else set()))
    def cleaned(text: str) -> str:
        out = re.sub(r"[^一-鿿]", "", text or "")
        for ch in _NON_FORM_CHARS:
            out = out.replace(ch, "")
        for t in class_terms:
            out = out.replace(t, "")
        if artifact["era"]:
            out = out.replace(artifact["era"], "")
        return out

    excluded = set()
    for t in class_terms:
        excluded |= grams(t)

    name_clean = cleaned(artifact["name"])
    orig_clean = cleaned(artifact["original_name"])
    form_terms = sorted((grams(name_clean) | grams(orig_clean)) - excluded)

    # The shape word is the FINAL character of a Chinese artifact name, and the
    # characters before it are material modifiers: 铜镜 = 铜 + 镜, 玉璧 = 玉 + 璧,
    # 瓷碗 = 瓷 + 碗. Measured over all 465 names, the final character alone has
    # 107 distinct values and 36 of them cover 80% of the collection.
    # So a head term must CONTAIN THE FINAL CHARACTER: 碧玉斧 yields 玉斧 and not
    # 碧玉, which is a jade variety (material) and was letting a passage about
    # 昆山之玉 count as evidence for what a jade AXE was for.
    # Single characters are still excluded — 器 / 当 match inside 陶器 / 当时.
    def head(text: str) -> set[str]:
        out = set()
        for n in (2, 3):
            if len(text) >= n:
                out.add(text[-n:])
        return {t for t in out if len(t) >= 2}

    head_terms = sorted((head(name_clean) | head(orig_clean)) - excluded)
    return head_terms, form_terms, class_terms


SCOPE_RANK = {"form_head_level": 3, "form_level": 2, "class_level": 1}


def on_topic(prose: str, head_terms: list[str], form_terms: list[str],
             class_terms: list[str]) -> tuple[bool, str, list[str]]:
    """Returns (ok, evidence_scope, matched). Highest tier that matches wins."""
    head_hits = [t for t in head_terms if t in prose]
    if head_hits:
        return True, "form_head_level", head_hits
    form_hits = [t for t in form_terms if t in prose]
    if form_hits:
        return True, "form_level", form_hits
    # a single mention in 2500 characters is a passing reference, not a topic
    class_hits = [t for t in class_terms if prose.count(t) >= MIN_WHOLE_TERM_HITS]
    if class_hits:
        return True, "class_level", class_hits
    return False, "", []


def build_query(artifact: dict) -> str:
    """
    What a researcher would actually type: the object's name plus its class.

    The name carries the form, and the form carries the function. A key built
    only from (category | material | era) sent 唐残三彩莲纹柱座 — an architectural
    component — into pottery-vessel background, and the LLM duly proposed
    「存储、炊煮、饮食等日常生活器皿」 as its original context.
    """
    parts = [artifact["name"], artifact["era_literal"] or artifact["era"],
             artifact["category"].replace("、", " "), artifact["material"].replace("+", " ")]
    seen: dict[str, None] = {}
    for token in " ".join(p for p in parts if p).split():
        seen.setdefault(token, None)
    return " ".join(seen)


def retrieve_for_artifact(artifact: dict, top: int) -> dict[str, Any]:
    query = build_query(artifact)
    head_terms, form_terms, class_terms = topic_terms(artifact)
    key = query

    result = spost("/search/query", {"domain": SOURCE_DOMAIN, "query": query, "limit": top})
    if "error" in result:
        return {"key": key, "query": query, "error": result["error"],
                "head_terms": head_terms, "form_terms": form_terms,
                "class_terms": class_terms, "candidates": [], "dropped": {}}

    dropped: dict[str, int] = {}
    seen_events: dict[str, dict] = {}
    for hit in result.get("hits", []):
        if (hit.get("hybrid_score") or 0) < MIN_RAG_SCORE:
            dropped["below_score"] = dropped.get("below_score", 0) + 1
            continue
        text = hit.get("content") or ""
        ok, why, prose = is_citable(text)
        if not ok:
            dropped[why] = dropped.get(why, 0) + 1
            continue
        topical, scope, whole_terms = on_topic(prose, head_terms, form_terms, class_terms)
        if not topical:
            dropped["off_topic"] = dropped.get("off_topic", 0) + 1
            continue
        ratio, matched = relevance(prose, query)
        event_id = hit.get("event_id", "")
        # G4: one passage is one source. Keep the best-scoring hit per event.
        prev = seen_events.get(event_id)
        if prev and prev["score"] >= (hit.get("hybrid_score") or 0):
            dropped["duplicate_event"] = dropped.get("duplicate_event", 0) + 1
            continue
        if prev:
            dropped["duplicate_event"] = dropped.get("duplicate_event", 0) + 1
        seen_events[event_id] = {
            "score": round(hit.get("hybrid_score") or 0, 3),
            "stream_id": hit.get("stream_id", ""),
            "event_id": event_id,
            "source": (hit.get("metadata") or {}).get("source_name", "unknown"),
            "matched_terms": matched[:12],
            "matched_whole_terms": whole_terms,
            "evidence_scope": scope,
            "match_ratio": round(ratio, 2),
            # the stripped prose is what gets cited, so it is what we store
            "text": " ".join(prose.split())[:1600],
        }

    # form_level evidence first: it is the only kind a functional slot may use.
    candidates = sorted(seen_events.values(),
                        key=lambda c: (-SCOPE_RANK[c["evidence_scope"]], -c["score"]))
    for i, c in enumerate(candidates, 1):
        c["candidate_id"] = f"c{i:02d}"
    return {"key": key, "query": query, "head_terms": head_terms,
            "form_terms": form_terms, "class_terms": class_terms,
            "candidates": candidates,
            "dropped": dropped, "retrieved_at": now_iso()}


def rescope(artifact: dict, candidates: list[dict]) -> list[dict]:
    """
    Recompute each cached candidate's evidence tier for THIS artifact.

    The tier depends on the artifact's own terms, not on the retrieval, so it is
    derived here rather than frozen into the cache. That way tightening the rule
    costs an LLM pass, not 420 remote searches.
    """
    head_terms, form_terms, class_terms = topic_terms(artifact)
    out = []
    for c in candidates:
        ok, scope, matched = on_topic(c["text"], head_terms, form_terms, class_terms)
        if not ok:
            continue
        out.append({**c, "evidence_scope": scope, "matched_whole_terms": matched})
    out.sort(key=lambda c: (-SCOPE_RANK[c["evidence_scope"]], -c["score"]))
    for i, c in enumerate(out, 1):
        c["candidate_id"] = f"c{i:02d}"
    return out


def load_cache() -> dict:
    if CANDIDATE_CACHE.exists():
        return json.loads(CANDIDATE_CACHE.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict) -> None:
    L2_OUT_DIR.mkdir(parents=True, exist_ok=True)
    CANDIDATE_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1),
                              encoding="utf-8")


def retrieval_run_id(cache_entry: dict) -> str:
    """Stable id for the retrieval that produced a slot's candidates."""
    payload = cache_entry["key"] + "|" + "|".join(
        c["event_id"] for c in cache_entry["candidates"])
    return "r" + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Slot filling
# ---------------------------------------------------------------------------

def import_llm():
    sys.path.insert(0, str(PIPELINE_DIR))
    from llm_config_common import (  # type: ignore
        apply_chat_completion_token_limit, load_llm_config, redacted_llm_config)
    return load_llm_config, apply_chat_completion_token_limit, redacted_llm_config


def _parse_json(content: str) -> dict | None:
    text = str(content or "").strip()
    if text.startswith("```"):
        nl = text.find("\n")
        text = text[nl + 1:] if nl != -1 else text
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(text[i:])
        except json.JSONDecodeError:
            continue
        return parsed if isinstance(parsed, dict) else None
    return None


def fill_slots(artifact: dict, candidates: list[dict], cfg: dict,
               max_tokens: int) -> dict[str, Any]:
    """Ask the LLM to fill every slot from a CLOSED candidate list."""
    _, apply_token_limit, _ = import_llm()

    prompt = {
        "任务": "为一件馆藏文物填写研究槽位。只能从给定候选段落中选择依据。",
        "硬性规则": [
            "只能引用候选列表里的 candidate_id，不得引用列表外的任何东西。",
            "object_surface 必须是所引段落中【原样出现】的字串，不得改写、不得概括。",
            "证据不足就填 insufficient_evidence，这是正当答案，不要勉强填。",
            "候选段落谈的是器物类别层面，不是这一件具体文物；不要写成关于该个体的既定事实。",
            "只输出 JSON。",
        ],
        "文物登记信息": {
            "藏品总登记号": artifact["registry_no"],
            "名称": artifact["name"],
            "原名": artifact["original_name"] or None,
            "类别": artifact["category"],
            "质地": artifact["material"],
            "登记年代": artifact["era_literal"] or artifact["era"] or None,
        },
        "候选段落": [
            {"candidate_id": c["candidate_id"], "来源": c["source"],
             "命中词": c["matched_terms"], "原文": c["text"]}
            for c in candidates
        ],
        "槽位": [
            {"slot": name,
             "问题": spec["question"],
             "填写要求": spec["guidance"],
             **({"stance 取值": list(spec["extra_keys"]["stance"])}
                if "extra_keys" in spec else {})}
            for name, spec in SLOTS.items()
        ],
        "输出格式": {
            "fills": [
                {"slot": "<槽位名>",
                 "decision": "filled | insufficient_evidence",
                 "object_surface": "<所引段落中原样出现的字串；insufficient 时为空>",
                 "cited_candidate_ids": ["c01"],
                 "stance": "supports | questions（仅 dating_corroboration 需要）",
                 "reason": "<一句话说明>"}
            ]
        },
    }
    payload = {
        "model": cfg.get("model"),
        "temperature": float(cfg.get("temperature", 0.0)),
        "messages": [
            {"role": "system",
             "content": "你是严谨的博物馆研究员。你只依据给定原文作答，从不编造证据，"
                        "证据不足时明确说证据不足。"},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
    }
    payload = apply_token_limit(payload, cfg, max_tokens)
    content = llm_chat(cfg, payload)
    parsed = _parse_json(content)
    if parsed is None:
        raise ValueError(f"LLM 未返回可解析 JSON: {content[:200]}")
    return parsed


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------

def gate_fills(artifact: dict, fills: list[dict], candidates: list[dict]
               ) -> tuple[list[dict], list[dict]]:
    """Return (accepted, rejected). Rejections are recorded, never silent."""
    by_id = {c["candidate_id"]: c for c in candidates}
    accepted, rejected = [], []

    for fill in fills if isinstance(fills, list) else []:
        slot = str(fill.get("slot") or "")
        if slot not in SLOTS:
            rejected.append({**fill, "gate": "unknown_slot"})
            continue
        if str(fill.get("decision")) != "filled":
            continue                      # insufficient_evidence -> research gap

        cited = [str(c) for c in (fill.get("cited_candidate_ids") or [])]
        # G1 — cited ids must exist
        unknown = [c for c in cited if c not in by_id]
        if not cited or unknown:
            rejected.append({**fill, "gate": "G1_unknown_candidate",
                             "detail": f"未知候选 {unknown or '(未引用任何候选)'}"})
            continue

        surface = str(fill.get("object_surface") or "").strip()
        if not surface:
            rejected.append({**fill, "gate": "G2_empty_object"})
            continue
        # G2 — the object must literally occur in one of the cited passages
        hosts = [c for c in cited if surface in by_id[c]["text"]]
        if not hosts:
            rejected.append({**fill, "gate": "G2_object_not_in_passage",
                             "detail": f"{surface!r} 不在所引段落中出现"})
            continue

        # G3 — the passage must be citable back to the remote gateway
        host = by_id[hosts[0]]
        if not (host["stream_id"] and host["event_id"]):
            rejected.append({**fill, "gate": "G3_unresolvable_passage"})
            continue

        # G9 — a claim about what this OBJECT was for may only rest on a passage
        # that discusses this kind of object. Otherwise 三彩莲纹柱座 (an
        # architectural component) gets 「存储、炊煮、饮食等日常生活器皿」 from a
        # passage about pottery vessels: the string really is in the text, so G2
        # passes, but the category is wrong.
        need = SLOTS[slot].get("requires_scope")
        if need and SCOPE_RANK.get(host.get("evidence_scope"), 0) < SCOPE_RANK[need]:
            rejected.append({**fill, "gate": "G9_scope_too_coarse",
                             "detail": f"该槽位需要 {need} 证据，所引段落是 "
                                       f"{host.get('evidence_scope')}"})
            continue

        extra = SLOTS[slot].get("extra_keys") or {}
        if "stance" in extra:
            stance = str(fill.get("stance") or "")
            if stance not in extra["stance"]:
                rejected.append({**fill, "gate": "G8_bad_stance",
                                 "detail": f"stance={stance!r}"})
                continue

        accepted.append({**fill, "host_candidate": host, "cited": cited,
                         "object_surface": surface})
    return accepted, rejected


# ---------------------------------------------------------------------------
# Batch construction
# ---------------------------------------------------------------------------

def build_batch(plans: list[dict]) -> dict[str, Any]:
    entities: dict[str, dict] = {}
    statements: list[dict] = []
    qualifiers: list[dict] = []
    references: list[dict] = []

    def add_entity(entity_id: str, kind: str, role: str,
                   datatype: str | None = None, meta: dict | None = None) -> None:
        if entity_id in entities:
            return
        e = {"entity_id": entity_id, "entity_kind": kind, "semantic_role": role,
             "namespace": TARGET_DOMAIN, "status": "active",
             "metadata_json": {"domain": TARGET_DOMAIN, **(meta or {})}}
        if datatype:
            e["property_datatype"] = datatype
        entities[entity_id] = e

    add_entity(REF_PASSAGE, "property", "annotation_property", "json",
               meta={"label": "远端原文出处"})

    def emit(subject: str, name: str, value_json: dict, *, disc: str,
             confidence: float, quals: dict, passage: dict | None) -> None:
        key = f"wwybsj/L2/{subject.rsplit('.', 1)[-1]}/{name}/{disc}"
        prop = f"{P}{name}"
        add_entity(prop, "property", "datatype_property", "json", meta={"label": name})
        statements.append({
            "statement_key": key, "subject_id": subject, "property_id": prop,
            "value_type": "json", "value_json": value_json,
            "status": "extracted",              # 研究性断言可复核，不是 accepted
            "confidence": confidence, "created_by": EXTRACTOR,
            "metadata_json": {"domain": TARGET_DOMAIN, "layer": "L2",
                              "statement_key": key, "slot": value_json.get("slot")},
        })
        for ordinal, (qkey, qval) in enumerate(quals.items()):
            qprop = f"{Q}{qkey}"
            is_text = isinstance(qval, str)
            add_entity(qprop, "property", "annotation_property",
                       "string" if is_text else "json", meta={"label": qkey})
            qualifiers.append({"statement_key": key, "property_id": qprop,
                               "value_type": "string" if is_text else "json",
                               "value_json": {"text": qval} if is_text else qval,
                               "ordinal": ordinal})
        if passage:
            references.append({
                "statement_key": key, "property_id": REF_PASSAGE,
                "value_type": "json",
                "value_json": {"gateway": SOURCE_BASE, "domain": SOURCE_DOMAIN,
                               "stream_id": passage["stream_id"],
                               "event_id": passage["event_id"],
                               "source": passage["source"],
                               "note": "resolves on the remote gateway, not in this database"},
                "source_span": passage["text"][:1200],
                "ordinal": 0,
            })

    for plan in plans:
        subject = plan["subject_id"]
        run = plan["retrieval_run"]

        for fill in plan["accepted"]:
            slot = fill["slot"]
            spec = SLOTS[slot]
            host = fill["host_candidate"]
            value: dict[str, Any] = {
                "slot": slot,
                "object_surface": fill["object_surface"],
                "evidence_scope": host.get("evidence_scope", "class_level"),
                "cited_event_ids": sorted({plan["by_id"][c]["event_id"] for c in fill["cited"]}),
                "reason": str(fill.get("reason") or "")[:400],
                "retrieval_key": plan["retrieval_key"],
            }
            if "stance" in (spec.get("extra_keys") or {}):
                value["stance"] = fill["stance"]
            emit(subject, slot, value,
                 disc=hashlib.sha1(fill["object_surface"].encode()).hexdigest()[:8],
                 confidence=0.5 if spec["epistemic_mode"] == "hypothesized" else 0.6,
                 quals={"epistemic_mode": spec["epistemic_mode"],
                        "basis": "remote_source_text",
                        "defeasible": {"value": True},
                        "slot": slot,
                        "review_status": "unreviewed",
                        "retrieval_run": run},
                 passage=host)

        for gap in plan["gaps"]:
            emit(subject, "has_research_gap",
                 {"slot": gap["slot"], "reason": gap["reason"],
                  "candidates_offered": gap["candidates_offered"],
                  "retrieval_key": plan["retrieval_key"],
                  "detail": gap.get("detail", "")},
                 disc=gap["slot"], confidence=1.0,
                 quals={"epistemic_mode": "inferred",
                        "basis": "l2_slot_fill_pass",
                        "slot": gap["slot"],
                        "retrieval_run": run},
                 passage=None)

    return {"entities": list(entities.values()), "statements": statements,
            "qualifiers": qualifiers, "references": references}


def write_in_chunks(plans: list[dict], chunk_size: int) -> int:
    """
    Post the batch in chunks. Returns the number of failed chunks.

    One request for everything does not survive: 464 artifacts produced 1392
    statements and 500 references each carrying a 1200-character source_span,
    and the gateway closed the connection mid-body (`Broken pipe`) — an hour of
    LLM work with nothing written. Chunking also means a partial failure loses
    one chunk, not the run.
    """
    failures = 0
    written = 0
    for start in range(0, len(plans), chunk_size):
        chunk = plans[start:start + chunk_size]
        batch = build_batch(chunk)
        if not batch["statements"]:
            continue
        span = f"{chunk[0]['registry_no']}..{chunk[-1]['registry_no']}"
        result = post("/ontology/semantic/upsert-batch", batch)
        if "error" in result:
            print(f"  ✗ [{span}] {result['error'][:110]}", file=sys.stderr)
            failures += 1
            continue
        written += len(batch["statements"])
        print(f"  ✓ [{span}] {len(batch['statements'])} 条 statement, "
              f"{len(batch['references'])} 条 reference")
    print(f"\n共写入 {written} 条 statement，失败批次 {failures}")
    return failures


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sel = p.add_mutually_exclusive_group(required=True)
    sel.add_argument("--registry-no")
    sel.add_argument("--all", action="store_true")
    sel.add_argument("--write-from-plan", metavar="PATH",
                     help="从已有 plan JSON 直接分批写库，不重跑检索与 LLM")
    p.add_argument("--retrieval-only", action="store_true",
                   help="只做检索并写候选缓存，不调 LLM、不写库（可与 --registry-no/--all 同用）")
    p.add_argument("--execute", action="store_true")
    p.add_argument("--resume", action="store_true", help="跳过已写入 L2 的文物")
    p.add_argument("--top", type=int, default=8, help="每个检索键取多少候选")
    p.add_argument("--llm-max-tokens", type=int, default=1600)
    p.add_argument("--limit", type=int, default=0, help="只处理前 N 件（调试用）")
    p.add_argument("--write-chunk", type=int, default=40,
                   help="每批写入多少件文物（整批一次 POST 会被网关掐断）")
    p.add_argument("--pace", type=float, default=1.5,
                   help="每次检索之间的间隔秒数，避免把远端检索后端压出 503")
    args = p.parse_args()

    if args.write_from_plan:
        plans = json.loads(Path(args.write_from_plan).read_text(encoding="utf-8"))
        n_fill = sum(len(pl["accepted"]) for pl in plans)
        n_gap = sum(len(pl["gaps"]) for pl in plans)
        print(f"从 plan 恢复写库：{len(plans)} 件 · 断言 {n_fill} · 缺口 {n_gap}")
        if not args.execute:
            print("PREVIEW ONLY — 加 --execute 才写入。")
            return 0
        failures = write_in_chunks(plans, args.write_chunk)
        print(call_summary())
        return 1 if failures else 0

    artifacts = load_artifacts()
    if args.registry_no:
        want = re.sub(r"\D", "", args.registry_no).zfill(4)
        artifacts = [a for a in artifacts if a["registry_no"] == want]
        if not artifacts:
            raise SystemExit(f"registry_no={args.registry_no!r} 在 L0 里找不到")

    if args.resume:
        # Every predicate L2 can write; a gap counts as done, exactly as the
        # old `layer='L2'` scan did.
        done = {r["subject_id"]
                for pred in (*SLOTS, "has_research_gap")
                for r in list_statements(property_id=f"{P}{pred}")}
        before = len(artifacts)
        artifacts = [a for a in artifacts if a["subject_id"] not in done]
        print(f"resume: 跳过已完成 {before - len(artifacts)} 件")
    if args.limit:
        artifacts = artifacts[:args.limit]

    # The cache is keyed by the QUERY STRING, so artifacts with identical names
    # and classes share one retrieval automatically.
    for a in artifacts:
        a["retrieval_key"] = build_query(a)
    keys = sorted({a["retrieval_key"] for a in artifacts})
    print(f"文物 {len(artifacts)} 件 · 去重检索查询 {len(keys)} 个")

    cache = load_cache()
    todo = [a for a in {a["retrieval_key"]: a for a in artifacts}.values()
            if a["retrieval_key"] not in cache]
    print(f"候选缓存命中 {len(keys) - len(todo)} / {len(keys)}，需检索 {len(todo)} 个")
    # A failed retrieval is NEVER cached. Caching it would turn a momentary 503
    # into a permanent "no evidence" verdict, and G7 would then write research
    # gaps that are artefacts of a network hiccup — the same false-negative trap
    # as caching a lookup miss.
    retrieval_failures: list[tuple[str, str]] = []
    for i, art in enumerate(todo, 1):
        print(f"  [检索 {i}/{len(todo)}] {art['retrieval_key'][:60]}",
              file=sys.stderr, flush=True)
        entry = retrieve_for_artifact(art, args.top)
        if entry.get("error"):
            retrieval_failures.append((art["retrieval_key"], entry["error"][:100]))
            print(f"      ✗ 检索失败，不写缓存（下次 --resume 会重试）",
                  file=sys.stderr, flush=True)
            time.sleep(args.pace * 3)
            continue
        cache[art["retrieval_key"]] = entry
        save_cache(cache)
        # The backend answers 503 BACKEND_UNAVAILABLE under back-to-back heavy
        # queries; a short pause between them keeps it alive.
        time.sleep(args.pace)
    if retrieval_failures:
        print(f"\n检索失败 {len(retrieval_failures)} 个查询（未缓存，可 --resume 重试）:")
        for k, e in retrieval_failures[:5]:
            print(f"    {k[:50]} → {e[:70]}")

    L2_OUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.retrieval_only:
        total = sum(len(cache[k]["candidates"]) for k in keys)
        empty = [k for k in keys if not cache[k]["candidates"]]
        print(f"\n候选总数 {total}，平均 {total / max(len(keys),1):.1f}/键")
        print(f"零候选的键 {len(empty)} 个：{empty[:8]}")
        scopes: dict[str, int] = {}
        for k in keys:
            for c in cache[k]["candidates"]:
                scopes[c["evidence_scope"]] = scopes.get(c["evidence_scope"], 0) + 1
        print(f"证据层级：{scopes}")
        drops: dict[str, int] = {}
        for k in keys:
            for why, n in (cache[k].get("dropped") or {}).items():
                drops[why] = drops.get(why, 0) + n
        print(f"被过滤：{drops}")
        print(f"缓存：{CANDIDATE_CACHE}")
        return 0

    # G6 — no LLM, no writing. Resolve the config before doing anything else.
    load_llm_config, _, redacted = import_llm()
    cfg = load_llm_config(DAC_JSON)
    print(f"LLM: {json.dumps(redacted(cfg), ensure_ascii=False)[:120]}")

    plans: list[dict] = []
    llm_errors = 0
    skipped_no_retrieval = 0
    for i, art in enumerate(artifacts, 1):
        entry = cache.get(art["retrieval_key"])
        if entry is None:
            # retrieval failed this run — say nothing about this artifact rather
            # than record a gap we cannot stand behind
            skipped_no_retrieval += 1
            continue
        cands = rescope(art, entry["candidates"])
        run = retrieval_run_id(entry)
        by_id = {c["candidate_id"]: c for c in cands}

        # G7 — nothing on topic: record gaps, never guess.
        if not cands:
            plans.append({**art, "retrieval_run": run, "by_id": by_id, "accepted": [],
                          "gaps": [{"slot": s, "reason": "no_on_topic_candidates",
                                    "candidates_offered": 0} for s in SLOTS]})
            print(f"  [{i}/{len(artifacts)}] {art['registry_no']} {art['name'][:18]} "
                  f"→ 无候选，记 3 条缺口")
            continue

        try:
            out = fill_slots(art, cands, cfg, args.llm_max_tokens)
        except (urllib.error.URLError, TimeoutError, RuntimeError, KeyError,
                ValueError, json.JSONDecodeError) as exc:
            # G6: no fallback. Skip the artifact and say so.
            llm_errors += 1
            print(f"  [{i}/{len(artifacts)}] {art['registry_no']} ✗ LLM 失败，跳过"
                  f"（不降级写入）: {type(exc).__name__} {str(exc)[:80]}", file=sys.stderr)
            continue

        accepted, rejected = gate_fills(art, out.get("fills") or [], cands)
        filled_slots = {f["slot"] for f in accepted}
        gaps = []
        for slot in SLOTS:
            if slot in filled_slots:
                continue
            rej = next((r for r in rejected if r.get("slot") == slot), None)
            # Keep these two apart: "a gate threw the answer out because the
            # evidence was about the wrong thing" is a different finding from
            # "there was nothing to say". Conflating them hides the G9 count.
            gaps.append({"slot": slot,
                         "reason": ("insufficient_evidence" if not rej
                                    else "rejected_by_gate"),
                         "gate": (rej["gate"] if rej else ""),
                         "candidates_offered": len(cands),
                         "detail": (f"{rej['gate']}: {rej.get('detail','')}"[:200]
                                    if rej else "")})
        plans.append({**art, "retrieval_run": run, "by_id": by_id,
                      "accepted": accepted, "gaps": gaps, "rejected": rejected})
        print(f"  [{i}/{len(artifacts)}] {art['registry_no']} {art['name'][:18]} "
              f"→ 填 {len(accepted)} / 拒 {len(rejected)} / 缺口 {len(gaps)}"
              f" (候选 {len(cands)})")

    batch = build_batch(plans)
    plan_path = L2_OUT_DIR / ("l2_plan.json" if not args.registry_no
                              else f"l2_plan_{artifacts[0]['registry_no']}.json")
    plan_path.write_text(json.dumps(plans, ensure_ascii=False, indent=1), encoding="utf-8")

    n_fill = sum(len(p["accepted"]) for p in plans)
    n_rej = sum(len(p.get("rejected", [])) for p in plans)
    n_gap = sum(len(p["gaps"]) for p in plans)
    print(f"\n断言 {n_fill} · 被闸门拒绝 {n_rej} · 缺口 {n_gap} · LLM 失败 {llm_errors}"
          f" · 因检索失败跳过 {skipped_no_retrieval}")
    print(f"statements {len(batch['statements'])} · references {len(batch['references'])}")
    print(f"plan: {plan_path}")

    gate_counts: dict[str, int] = {}
    for pl in plans:
        for r in pl.get("rejected", []):
            gate_counts[r["gate"]] = gate_counts.get(r["gate"], 0) + 1
    if gate_counts:
        print(f"闸门拦截明细: {gate_counts}")

    if not args.execute:
        print("\nPREVIEW ONLY — 加 --execute 才写入。")
        return 0

    failures = write_in_chunks(plans, args.write_chunk)
    print(call_summary())
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
