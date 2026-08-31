#!/usr/bin/env python3
"""
wwybsj_research.py — Step 2: research ONE artifact record against the REMOTE
`archeology` corpus, across all four evidence layers.

READ-ONLY, and it only ever talks to SOURCE_BASE (the remote gateway). Nothing
in this file writes anywhere. The synthesis is the model's job (see SKILL.md),
and it must work from what this prints.

Every structured hit keeps its remote `concept_id`, and every source-text hit
keeps its remote `stream_id`/`event_id`, so the wwybsj domain built later can
cite them as xrefs without sharing storage with the remote database.

Layers, in the order the tdb-archeology-answering discipline requires:
  1. wiki      — GET  /v2/wiki/search, /v2/wiki/page      (domain-scoped)
  2. ontology  — GET  /v2/ontology/concept/search, /relation-candidate/list
  3. facts     — GET  /v2/ontology/fact/list  (+ statement_id when present)
  4. search    — POST /v2/search/query        (hybrid RAG source text)

Usage:
  python3 wwybsj_research.py --id 8
  python3 wwybsj_research.py --id 8 --probe "roof tile" --probe "Balhae"   # round 2
  python3 wwybsj_research.py --id 8 --top 8 --save
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wwybsj_common import (  # noqa: E402
    OUT_DIR, SOURCE_BASE, SOURCE_DOMAIN,
    bianhao, call_summary, clean, get_record, niandai, probes_for, sget, spost,
    title, to_simplified, zhidi,
)


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)

MIN_RAG_SCORE = 0.05
STRONG_RAG_SCORE = 0.15

# ---------------------------------------------------------------------------
# Noise filtering
#
# The corpus is OCR'd textbook PDFs. Their tables of contents
# and index pages score highly on almost any query while carrying zero claims.
# A hit that survives `is_noise` is not necessarily relevant — but a hit that
# does not survive it must never be quoted as evidence.
# ---------------------------------------------------------------------------

_TOC_MARKERS = ("CONTENTS", "目　录", "目录", "Index", "索引", "参考文献")


def is_noise(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 80:
        return True
    head = t[:120]
    if any(m in head for m in _TOC_MARKERS):
        return True
    # TOC lines are dominated by dot leaders, digits and page numbers
    filler = sum(1 for ch in t if ch in ".·… \t\n0123456789")
    if filler / len(t) > 0.35:
        return True
    # A real paragraph has sentence punctuation
    if not any(p in t for p in "。．.；;！!？?"):
        return True
    return False


def _grams(s: str) -> set:
    """CJK 2-grams plus ASCII words — a segmentation-free term signature.

    Text is folded to simplified first so that traditional passages in the
    corpus (柱礎, 綠琉璃) match simplified registry terms (柱础, 绿釉).
    """
    s = to_simplified(s)
    out: set = set()
    for run in re.findall(r"[一-鿿]{2,}", s or ""):
        for i in range(len(run) - 1):
            out.add(run[i:i + 2])
    for w in re.findall(r"[a-zA-Z][a-zA-Z0-9\-]{2,}", (s or "").lower()):
        out.add(w)
    return out


def relevance(text: str, query: str) -> tuple[float, list]:
    """
    Overlap between a query and a passage, as (ratio, matched_terms).

    Substring matching cannot work here: an artifact name like 渤海绿釉柱础护圈
    never appears verbatim in a textbook, and requiring every whitespace token
    to be present (the obvious first attempt) marks every multi-term Chinese
    query as off-topic — which silently threw away real evidence and graded
    well-covered artifacts as `thin`.

    KNOWN LIMITATION: the corpus mixes simplified and traditional Chinese
    (中国古代建筑史 is traditional OCR), so 柱础/柱礎 and 绿釉/綠琉璃 do not match
    each other. No converter is installed and a partial hand-built table would
    be worse than none. Consequence: overlap is UNDER-counted on traditional
    passages, never over-counted. Hence the deliberately low threshold below —
    unrelated text scores a clean 0, so a single matched term is real signal.
    """
    q = _grams(query)
    if not q:
        return 0.0, []
    matched = sorted(q & _grams(text))
    return len(matched) / len(q), matched


def is_relevant(text: str, probe: str) -> bool:
    ratio, matched = relevance(text, probe)
    return bool(matched)


# ---------------------------------------------------------------------------
# Layer 1 — wiki
# ---------------------------------------------------------------------------

def wiki_layer(probes: list[str], domain: str, top: int) -> dict:
    out: dict = {}
    for i, probe in enumerate(probes, 1):
        log(f"  [wiki {i}/{len(probes)}] {probe}")
        hits = sget("/wiki/search", {"domain": domain, "q": probe, "limit": top})
        results = hits.get("results", hits.get("pages", []))
        if not results:
            continue
        pages = []
        for h in results[:top]:
            slug_ = h.get("slug", "")
            page = sget("/wiki/page", {"domain": domain, "slug": slug_})
            content = ((page.get("page") or {}).get("content") or "")
            # wiki/search is substring-based: '陶' pulls in '立陶宛'. Keep a page
            # only when the probe is the page's own subject or is discussed in it.
            title_match = probe.lower() in (slug_ + " " + (h.get("title") or "")).lower()
            exact = (h.get("title") or "").lower() == probe.lower()
            pages.append({
                "slug": slug_,
                "title": h.get("title"),
                "page_type": h.get("page_type"),
                "confidence": round(h.get("effective_confidence") or 0, 3),
                "match": "exact" if exact else ("title_substring" if title_match else "body"),
                "on_topic": exact or is_relevant(content, probe),
                "content": content[:1200],
            })
        out[probe] = pages
    return out


# ---------------------------------------------------------------------------
# Layer 2 — ontology concepts + relation candidates
# ---------------------------------------------------------------------------

def ontology_layer(probes: list[str], domain: str, top: int) -> dict:
    out: dict = {}
    for i, probe in enumerate(probes, 1):
        log(f"  [ontology {i}/{len(probes)}] {probe}")
        concepts = sget("/ontology/concept/search", {"q": probe, "limit": 5}).get("concepts", [])
        edges: list[dict] = []
        for role, key, other in (("outbound", "subject_label", "object_label"),
                                 ("inbound", "object_label", "subject_label")):
            rc = sget("/ontology/relation-candidate/list",
                     {"domain": domain, key: probe, "limit": top})
            for e in rc.get("relation_candidates", []):
                edges.append({
                    "direction": role,
                    "predicate": e.get("relation_type"),
                    "other": e.get(other),
                    "confidence": round(e.get("confidence") or 0, 3),
                })
        if concepts or edges:
            out[probe] = {
                "concepts": [
                    {"concept_id": c["concept_id"],
                     "canonical_name": c["canonical_name"],
                     "concept_type": c.get("concept_type"),
                     "aliases": c.get("aliases", [])}
                    for c in concepts
                ],
                "relation_candidates": edges[:top * 2],
            }
    return out


# ---------------------------------------------------------------------------
# Layer 3 — committed facts (with statement_id when the row exposes one)
# ---------------------------------------------------------------------------

_facts_cache: list[dict] | None = None
_name_cache: dict[str, str] = {}


def domain_streams(domain: str) -> list[str]:
    r = sget("/search/domain-stream/list", {"domain": domain})
    rows = r.get("bindings", r.get("domain_streams", []))
    return [b["stream_id"] for b in rows
            if b.get("status", "active") == "active" and b.get("stream_id")]


def facts_for_concept(concept_id: str, top: int) -> list[dict]:
    """
    Facts touching one concept, via the concept-scoped filters fact/list
    actually supports.

    Why not enumerate the domain's facts and filter locally: GET
    /v2/ontology/fact/list has NO `domain` parameter (Fastify silently drops
    it), so domain scoping would mean walking all ~100 stream bindings and
    paging each. That is ~100+ sequential remote calls per probe, and the
    remote backend intermittently stalls for its full 30s gRPC timeout — one
    stall and the run looks hung. Asking by concept_id is 2 calls instead.

    Trade-off, stated plainly: facts are global, so a row returned here is not
    guaranteed to come from the `archeology` domain. Anything actually cited
    must have its provenance checked (see provenance_for).
    """
    rows: list[dict] = []
    for role, param in (("outbound", "src_concept_id"), ("inbound", "dst_concept_id")):
        r = sget("/ontology/fact/list", {param: concept_id, "limit": top * 3})
        for f in r.get("facts", []):
            other_id = f["dst_concept_id"] if role == "outbound" else f["src_concept_id"]
            rows.append({
                "direction": role,
                "predicate": f["predicate"],
                "other": _label(other_id),
                "source_concept_id": concept_id,
                "source_other_concept_id": other_id,
                "qualifier": f.get("qualifier") or {},
                "confidence": round(f.get("confidence") or 0, 3),
                "status": f.get("status"),
                "extractor": f.get("extractor", ""),
                "statement_id": f.get("statement_id") or "",
                "fact_id": f.get("fact_id"),
            })
    return rows


def _label(concept_id: str) -> str:
    if concept_id in _name_cache:
        return _name_cache[concept_id]
    r = sget("/ontology/concept/get", {"concept_id": concept_id})
    name = (r.get("canonical_name") or r.get("concept", {}).get("canonical_name")
            or concept_id[:8] + "…")
    _name_cache[concept_id] = name
    return name


def facts_layer(probes: list[str], domain: str, top: int) -> dict:
    """Committed facts for concepts whose canonical name exactly matches a probe."""
    out: dict = {}
    for i, probe in enumerate(probes, 1):
        log(f"  [facts {i}/{len(probes)}] {probe}")
        concepts = sget("/ontology/concept/search", {"q": probe, "limit": 5}).get("concepts", [])
        ids = [c["concept_id"] for c in concepts
               if c.get("canonical_name", "").lower() == probe.lower()]
        rows: list[dict] = []
        for cid in ids[:2]:
            rows.extend(facts_for_concept(cid, top))
        if rows:
            out[probe] = rows[:top * 4]
    return out


def _trim(value, max_chars: int = 900):
    """
    Structurally shorten a provenance payload.

    Do NOT do this by json.dumps -> slice -> json.loads: truncating the
    serialized form lands mid-string and the reparse raises. Walk the structure
    and shorten the leaves instead.
    """
    if isinstance(value, str):
        return value if len(value) <= max_chars else value[:max_chars] + "…"
    if isinstance(value, list):
        return [_trim(v, max_chars) for v in value[:5]]
    if isinstance(value, dict):
        return {k: _trim(v, max_chars) for k, v in value.items()}
    return value


def provenance_for(fact_rows: dict, limit: int = 4) -> list[dict]:
    """Walk statement/fact provenance back to source text for the best rows."""
    out: list[dict] = []
    seen = 0
    for probe, rows in fact_rows.items():
        for row in rows:
            if seen >= limit:
                return out
            sid = row.get("statement_id")
            if sid:
                log(f"  [provenance {seen + 1}/{limit}] statement {sid[:8]}… ({probe})")
                r = sget("/ontology/statement/provenance", {"statement_id": sid})
                path = "statement/provenance"
            elif row.get("fact_id"):
                log(f"  [provenance {seen + 1}/{limit}] fact {row['fact_id']} ({probe})")
                r = sget("/ontology/fact/provenance", {"fact_id": row["fact_id"]})
                path = "fact/provenance"
            else:
                continue
            out.append({
                "probe": probe,
                "fact": f"{probe} -{row['predicate']}-> {row['other']}",
                "path": path,
                "result": r if "error" in r else _trim(r),
            })
            seen += 1
    return out


# ---------------------------------------------------------------------------
# Layer 4 — hybrid RAG source text
# ---------------------------------------------------------------------------

def search_layer(queries: list[str], domain: str, top: int) -> dict:
    out: dict = {}
    for i, q in enumerate(queries, 1):
        log(f"  [search {i}/{len(queries)}] {q[:50]}")
        r = spost("/search/query", {"domain": domain, "query": q, "limit": top})
        if "error" in r:
            out[q] = {"error": r["error"]}
            continue
        hits, dropped = [], 0
        for h in r.get("hits", []):
            if (h.get("hybrid_score") or 0) < MIN_RAG_SCORE:
                continue
            content = h.get("content") or ""
            if is_noise(content):
                dropped += 1
                continue
            ratio, matched = relevance(content, q)
            hits.append({
                "score": round(h.get("hybrid_score") or 0, 3),
                "stream_id": h.get("stream_id", ""),
                "event_id": h.get("event_id", ""),
                "source": (h.get("metadata") or {}).get("source_name", "unknown"),
                "on_topic": bool(matched),
                "match_ratio": round(ratio, 2),
                "matched_terms": matched[:12],
                "text": content[:1200],
            })
        out[q] = {
            "resolved_stream_ids": r.get("resolved_stream_ids", []),
            "dropped_as_toc_noise": dropped,
            "hits": hits,
        }
    return out


# ---------------------------------------------------------------------------
# Coverage assessment — so the model cannot silently overstate support
# ---------------------------------------------------------------------------

def assess(evidence: dict) -> dict:
    """
    Grade coverage on ON-TOPIC evidence only.

    Raw hit counts are meaningless here: hybrid search returns something for
    every query, so counting hits grades every artifact as well-covered. Only
    hits that survive noise filtering AND actually mention the probe count.
    """
    wiki_pages = [p for v in evidence["wiki"].values() for p in v]
    wiki_on = [p for p in wiki_pages if p["on_topic"]]
    onto_n = sum(len(v.get("relation_candidates", [])) for v in evidence["ontology"].values())
    fact_n = sum(len(v) for v in evidence["facts"].values())

    rag = [h for v in evidence["search"].values() if isinstance(v, dict)
           for h in v.get("hits", [])]
    rag_on = [h for h in rag if h["on_topic"]]
    strong_on = [h for h in rag_on if h["score"] >= STRONG_RAG_SCORE]
    dropped = sum(v.get("dropped_as_toc_noise", 0)
                  for v in evidence["search"].values() if isinstance(v, dict))

    if fact_n and strong_on:
        grade = "good"
    elif (wiki_on or onto_n) and rag_on:
        grade = "partial"
    elif wiki_on or onto_n or rag_on:
        grade = "thin"
    else:
        grade = "none"

    return {
        "wiki_pages_returned": len(wiki_pages),
        "wiki_pages_on_topic": len(wiki_on),
        "relation_candidates": onto_n,
        "committed_facts": fact_n,
        "rag_hits_after_noise_filter": len(rag),
        "rag_hits_on_topic": len(rag_on),
        "rag_hits_on_topic_strong": len(strong_on),
        "rag_hits_dropped_as_toc_noise": dropped,
        "best_on_topic_rag_score": max((h["score"] for h in rag_on), default=0),
        "coverage_grade": grade,
        "note": {
            "good":    "结构化层与原文层都有切题支撑：可以写研究性事实（related_to / "
                       "distinguished_from），并在 wiki 页引用原文。",
            "partial": "部分层切题：研究性结论必须标注为弱支撑，只写最有把握的一两条研究性事实。",
            "thin":    "仅有零星切题命中：不要写研究性事实，wiki 页必须写明 TDB 覆盖不足。",
            "none":    "archeology_expert 对该器物没有切题覆盖：只写登记事实（is_a / made_of / "
                       "dated_to 等），研究章节如实写“本域无支撑”。",
        }[grade],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--id", type=int, required=True)
    p.add_argument("--domain", default=SOURCE_DOMAIN, help="Domain to research against")
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--probe", action="append", default=[],
                   help="Extra round-2 probe (repeatable). Anchors harvested from round-1 text.")
    p.add_argument("--only-probes", action="store_true",
                   help="Use ONLY --probe values, skip the record-derived probes")
    p.add_argument("--rag-queries", type=int, default=4,
                   help="Max /search/query calls (each ~24s on the remote). Default: %(default)s")
    p.add_argument("--save", action="store_true", help="Write evidence JSON to out/")
    args = p.parse_args()

    rec = get_record(args.id)
    auto = probes_for(rec)
    probes = list(args.probe) if args.only_probes else auto + [
        x for x in args.probe if x not in auto
    ]

    # RAG is by far the most expensive layer: the remote /search/query runs
    # ~24s per call (vector retrieval over 331 streams), while every other
    # endpoint answers in well under a second. Sending all ~10 probes costs
    # four minutes of wall-clock for heavily redundant results, so send one
    # composed natural-language query plus the few most specific probes.
    composed = " ".join(filter(None, [
        clean(rec.get("ww_mingchen")), niandai(rec),
        clean(rec.get("ww_leibie")), zhidi(rec),
    ]))
    ranked = sorted(probes, key=len, reverse=True)          # specific before generic
    rag_queries = ([composed] if composed else []) + ranked
    seen_q: set = set()
    rag_queries = [q for q in rag_queries
                   if not (q in seen_q or seen_q.add(q))][:args.rag_queries]

    log(f"record {rec['id']} · {title(rec)}")
    log(f"probes ({len(probes)}): {probes}")
    log(f"rag queries ({len(rag_queries)}): {rag_queries}")

    started = time.monotonic()
    try:
        evidence = {
            "record_id": rec["id"],
            "bianhao": bianhao(rec),
            "title": title(rec),
            "researched_against_domain": args.domain,
            "researched_against_gateway": SOURCE_BASE,
            "registry": {k: clean(v) for k, v in rec.items() if clean(v)},
            "probes": probes,
            "rag_queries": rag_queries,
            "wiki": wiki_layer(probes, args.domain, args.top),
            "ontology": ontology_layer(probes, args.domain, args.top),
            "facts": facts_layer(probes, args.domain, args.top),
            "search": search_layer(rag_queries, args.domain, args.top),
        }
        evidence["provenance"] = provenance_for(evidence["facts"])
        evidence["coverage"] = assess(evidence)
    finally:
        # Always report what the network actually did, even on a crash — this
        # is the difference between "it hung" and a diagnosable run.
        log(f"elapsed {time.monotonic() - started:.1f}s")
        log(call_summary())

    text = json.dumps(evidence, ensure_ascii=False, indent=2)
    if args.save:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUT_DIR / f"evidence_{rec['id']:04d}.json"
        path.write_text(text, encoding="utf-8")
        print(f"saved: {path}")
        print(json.dumps(evidence["coverage"], ensure_ascii=False, indent=2))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
