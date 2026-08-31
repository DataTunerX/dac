#!/usr/bin/env python3
"""
wwybsj_l1.py — L1 builder: anchor local registry terms to remote concepts.

L1 is the hyperlink layer. It does not copy any archaeology knowledge into
`wwybsj`; it records, for each local controlled term, WHICH remote concept it
denotes. Reasoning then travels:

    wwybsj.artifact.0008
      --instantiates-->  wwybsj.term.category.陶器      (L0, observed)
      --aligned_to-->    archeology:concept:<uuid>       (L1, this script)
      --> the remote graph, resolved on demand

Alignment is attached to the TERM, not to each artifact: 36 terms cover all 465
artifacts, so one alignment is one source of truth and one thing to re-resolve
when the remote corpus changes.

NAME EQUALITY IS NOT ENOUGH, IN BOTH DIRECTIONS
1. Do not trust a wiki-page fallback. Junk observed live: 完整 -> "较完整的国体
   （the Shan state）"; 一般 -> "艺术的和知识的活动" flags=[invalid_supporting_signal_id].
   Ontology concepts pass promotion thresholds; ad-hoc wiki pages do not.
2. Do not conclude "no remote concept" from a top-N lookup. concept/search is a
   SUBSTRING search: 铁器 has 27 exactly-named concepts, but they rank below
   unrelated partial matches, so a limit=10 probe saw none of them and fell
   through to the junk wiki page. That single off-by-limit bug made 铁器/石刻/
   瓷器/铜器/雕塑/铜/铁/金/石 all look concept-less. Resolve the CLUSTER at the
   server cap (limit=200; higher returns HTTP 400) before concluding anything.
3. Same name is not same sense. 金's four same-name concepts are all 金朝
   (-produced_by_culture-> 女真族, -occurred_at-> 1234 年) or 文/武; 石's two are
   the volume unit 石 = 十斗. Unioning those would hang Jurchen-dynasty facts off
   a gold artifact. A homograph is rejected by review verdict (`reject_exact`),
   and a single junk cluster member by `exclude_concept_ids`.

Administrative facets (级别/来源/完残程度) are collection-management vocabulary,
not archaeology concepts, and are not looked up at all. `一般` above is exactly
what happens when you try.

Compound registry categories ('玉石器、宝石', '石器、石刻、砖瓦') are union
buckets, not concepts. They get one anchor per component, each labelled with the
surface it matched, because that is what the registry actually means.

Prerequisite: L0 must be written (the term entities come from it).
    python3 wwybsj_l0.py --all --execute

Usage:
    python3 wwybsj_l1.py                 # resolve + preview
    python3 wwybsj_l1.py --execute
    python3 wwybsj_l1.py --refresh       # re-resolve, ignoring the xref cache
    python3 wwybsj_l1.py --report        # coverage of the alignment as written
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wwybsj_common import (  # noqa: E402
    OUT_DIR, SOURCE_BASE, SOURCE_DOMAIN, TARGET_DOMAIN,
    call_summary, get, list_statements, load_term_usage,
    lookup_source_concept, post, sget,
)

EXTRACTOR = "wwybsj_l1_v2"
L1_OUT_DIR = OUT_DIR / "l1"
REVIEW_PATH = Path(__file__).resolve().parent.parent / "alignment_review.json"

# The remote corpus has unresolved duplicate concepts: 漆器 has 13 rows with the
# same canonical_name, 金银器 11, 陶瓷器 10, 青铜器 9, 砖瓦 8, 陶器 7, 玉石器 7.
# Their fact sets DIFFER (玉石器/5266abe7 carries 龙虬庄遗址, /3bb894fc does not;
# 宝石/ca5cb86a carries 丝绸之路, /7c16890f only art-history noise), so picking
# "the first exact match" silently discards most of the reachable knowledge —
# and /ontology/concept/search is not stable, so the pick was not even
# reproducible. An anchor therefore names the whole same-name CLUSTER and lets
# reasoning union over it. Entity resolution is the remote corpus's debt to pay;
# this domain must not guess on its behalf.
CLUSTER_LIMIT = 200   # server cap: limit>200 -> HTTP 400

P = "wwybsj.predicate."
Q = "wwybsj.qualifier."
REF_REMOTE = "wwybsj.ref.remote_concept"

# Facets that denote archaeology concepts. Everything else is registry
# administration and is deliberately never aligned.
ALIGNABLE_FACETS = {"category", "material", "period"}
ADMIN_FACET_REASON = {
    "grade": "文物级别是藏品管理词汇（一级/二级/三级/一般/未定级），不是考古概念",
    "acquisition": "文物来源是藏品管理词汇（发掘/征集购买/旧藏…），入藏途径不是器物属性",
    "completeness": "完残程度是藏品管理词汇，远端同名页面为通用词噪声（'完整' → 较完整的国体）",
}

_SPLIT = re.compile(r"[、,，/]")


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Local terms
# ---------------------------------------------------------------------------

def load_terms() -> list[dict[str, Any]]:
    """
    The term entities L0 created, plus how many statements point at each.

    The gateway exposes no `semantic_entity` listing, so the terms are recovered
    from the statements that reference them (`load_term_usage`). That is not a
    workaround: a term entity exists in this domain only because some artifact
    statement points at it, so the two sets are the same set. `facet` and `label`
    come from the id, which L0 builds as `wwybsj.term.<facet>.<label>` — the
    entity metadata carried no information the id does not.
    """
    uses = load_term_usage()
    if not uses:
        raise SystemExit("no wwybsj.term.* references found — "
                         "run wwybsj_l0.py --all --execute first")
    terms = []
    for entity_id, n in uses.items():
        rest = entity_id[len("wwybsj.term."):]
        facet, _, label = rest.partition(".")
        terms.append({"entity_id": entity_id, "facet": facet, "label": label,
                      "artifact_uses": n})
    terms.sort(key=lambda t: (t["facet"], t["label"]))
    return terms


def surfaces_for(label: str) -> list[str]:
    """The whole label first, then its components if it is a union bucket."""
    parts = [p.strip() for p in _SPLIT.split(label) if p.strip()]
    return [label] if len(parts) <= 1 else [label] + parts


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

_cluster_cache: dict[str, dict[str, Any]] = {}


def concept_cluster(name: str, extra_ids: list[str] | None = None) -> dict[str, Any]:
    """
    Every remote concept whose canonical_name is exactly `name`.

    `extra_ids` folds in ids known from elsewhere (the xref cache) that the
    current search does not return — observed for 陶器/陶/造像, whose cached ids
    resolve fine through concept/get but are absent from concept/search results.
    That discrepancy is recorded, not smoothed over.
    """
    if name in _cluster_cache and not extra_ids:
        return _cluster_cache[name]

    found: dict[str, str | None] = {}
    hit_limit = False
    for limit in (CLUSTER_LIMIT,):
        concepts = sget("/ontology/concept/search", {"q": name, "limit": limit}).get("concepts", [])
        hit_limit = hit_limit or len(concepts) >= limit
        for c in concepts:
            if c.get("canonical_name") == name:
                found[c["concept_id"]] = c.get("concept_type")

    search_missed = []
    for cid in extra_ids or []:
        if cid in found:
            continue
        got = sget("/ontology/concept/get", {"concept_id": cid})
        payload = got.get("concept", got) or {}
        if payload.get("canonical_name") == name:
            found[cid] = payload.get("concept_type")
            search_missed.append(cid)

    cluster = {
        "concept_ids": sorted(found),
        # Deterministic and search-order independent. Reasoning should union the
        # whole cluster; `primary` exists only for display and stable keys.
        "primary_concept_id": min(found) if found else None,
        "primary_selection_rule": "lexicographic_min",
        "cluster_size": len(found),
        "concept_types": sorted({t for t in found.values() if t}),
        "search_result_truncated": hit_limit,
        "ids_search_did_not_return": search_missed,
        "cluster_completeness": "unknown_search_is_not_stable",
        "search_limit_used": CLUSTER_LIMIT,
    }
    if not extra_ids:
        _cluster_cache[name] = cluster
    return cluster


def anchor_record(surface: str, label: str, cluster: dict, *, relation: str,
                  basis: str, review: dict | None = None) -> dict[str, Any]:
    return {
        "matched_surface": surface,
        "is_whole_label": surface == label,
        "match_relation": relation,
        "match_kind": "concept_cluster",
        "remote_domain": SOURCE_DOMAIN,
        "remote_gateway": SOURCE_BASE,
        "remote_canonical_name": surface,
        "basis": basis,
        "resolved_at": now_iso(),
        **cluster,
        **({"review": review} if review else {}),
    }


def resolve_term(term: dict, refresh: bool, review: dict) -> dict[str, Any]:
    """Attempt remote resolution for one term. Never writes anywhere."""
    label, facet = term["label"], term["facet"]
    decisions = review.get((facet, label), [])
    rejected_surfaces = {d["surface"] for d in decisions
                         if d["decision"] == "reject_wiki" and d.get("surface")}
    kept_candidates = {d["surface"] for d in decisions
                       if d["decision"] in {"keep_wiki_candidate", "promote_wiki"}
                       and d.get("surface")}
    promoted_wiki = {d["surface"] for d in decisions
                     if d["decision"] == "promote_wiki" and d.get("surface")}
    hard_stop = next((d for d in decisions
                      if d["decision"] in {"not_applicable", "leave_unaligned"}), None)
    # Homograph vetoes: same canonical_name, different sense.
    vetoed = {d["surface"]: d for d in decisions
              if d["decision"] == "reject_exact" and d.get("surface")}
    # Per-member exclusions inside an otherwise usable cluster (prefix match on id).
    excluded = {d["surface"]: d for d in decisions
                if d.get("exclude_concept_ids") and d.get("surface")}

    if facet not in ALIGNABLE_FACETS:
        return {**term, "status": "not_applicable",
                "reason": ADMIN_FACET_REASON.get(facet, "非考古概念词面"),
                "anchors": [], "candidates": [], "attempted": [],
                "rejected_exact": [], "decisions": decisions}

    anchors, candidates, attempted, rejected_exact = [], [], [], []

    # --- automatic exact-name resolution -----------------------------------
    for surface in surfaces_for(label):
        attempted.append(surface)
        # Cluster first. Asking the memoized top-N resolver whether a concept
        # exists is what produced the false "no remote concept" verdicts.
        hit = lookup_source_concept(surface, refresh=refresh)
        cached_id = [hit["concept_id"]] if hit and hit["xref_kind"] == "concept" else []
        cluster = concept_cluster(surface, extra_ids=cached_id)
        if cluster["concept_ids"] and surface in vetoed:
            v = vetoed[surface]
            rejected_exact.append({
                "matched_surface": surface, "cluster_size": cluster["cluster_size"],
                "veto": "homograph", "reason": v.get("reason", ""),
                "evidence": v.get("evidence", ""), "reviewer": review["_reviewer"]})
            continue
        if cluster["concept_ids"]:
            drop = [p for p in (excluded.get(surface, {}).get("exclude_concept_ids") or [])]
            if drop:
                prefixes = tuple(d.split("-")[0] for d in drop)
                kept = [c for c in cluster["concept_ids"] if not c.startswith(prefixes)]
                cluster = {**cluster, "concept_ids": kept,
                           "primary_concept_id": min(kept) if kept else None,
                           "cluster_size": len(kept),
                           "excluded_concept_ids": [c for c in cluster["concept_ids"]
                                                    if c.startswith(prefixes)],
                           "exclusion_note": excluded[surface].get("exclude_note", "")}
                if not kept:
                    continue
            anchors.append(anchor_record(surface, label, cluster, relation="exact",
                                         basis="remote_exact_concept_name_match"))
            continue
        if not hit:
            continue
        if surface in rejected_surfaces:
            continue                      # curator/reviewer killed this wiki hit
        record = {
            "matched_surface": surface,
            "is_whole_label": surface == label,
            "match_relation": "exact",
            "match_kind": "wiki_page",
            "remote_domain": SOURCE_DOMAIN,
            "remote_gateway": SOURCE_BASE,
            "remote_canonical_name": hit.get("canonical_name"),
            "remote_wiki_slug": hit.get("slug"),
            "resolved_at": now_iso(),
            "promoted_by_review": surface in promoted_wiki,
            "review_reason": (
                "已复核：内容可信，作为文档锚点保留（wiki 页无类型化边，不参与图 join）"
                if surface in promoted_wiki else
                "wiki-only 命中：远端无同名 ontology 概念，该层页面已证实包含噪声，"
                "未经复核不得作为锚点参与推理"),
        }
        if surface in kept_candidates or surface not in rejected_surfaces:
            candidates.append(record)

    # --- reviewed alignments to a DIFFERENT remote concept ------------------
    for d in decisions:
        if d["decision"] != "align" or d.get("target_kind") != "concept":
            continue
        target = d["target_name"]
        cluster = concept_cluster(target)
        if not cluster["concept_ids"]:
            continue
        anchors.append(anchor_record(target, label, cluster,
                                     relation=d.get("relation", "close"),
                                     basis="reviewed_mapping",
                                     review={"reason": d.get("reason", ""),
                                             "evidence": d.get("evidence", ""),
                                             "reviewer": review["_reviewer"],
                                             "review_status": review["_status"],
                                             "reviewed_at": review["_reviewed_at"]}))

    if hard_stop and not anchors:
        return {**term, "status": hard_stop["decision"],
                "reason": hard_stop.get("reason", ""), "anchors": [],
                "candidates": candidates, "attempted": attempted,
                "rejected_exact": rejected_exact, "decisions": decisions}

    exact = [a for a in anchors if a["match_relation"] == "exact" and a["is_whole_label"]]
    if exact:
        status = "aligned"
    elif anchors and any(a["is_whole_label"] for a in anchors):
        status = "aligned_by_mapping"
    elif anchors:
        status = "aligned_by_components"
    elif candidates:
        status = "candidate_only"
    else:
        status = "unaligned"
    return {**term, "status": status, "reason": "", "anchors": anchors,
            "candidates": candidates, "attempted": attempted,
            "rejected_exact": rejected_exact, "decisions": decisions}


def load_review(path: Path) -> dict:
    """Reviewer verdicts, keyed by (facet, label). Absent file = no review yet."""
    if not path.exists():
        return {"_reviewer": "", "_status": "unreviewed", "_reviewed_at": ""}
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: dict = {
        "_reviewer": payload.get("reviewer", ""),
        "_status": payload.get("review_status", "unreviewed"),
        "_reviewed_at": payload.get("reviewed_at", ""),
    }
    for d in payload.get("decisions", []):
        out.setdefault((d["facet"], d["label"]), []).append(d)
    return out


# ---------------------------------------------------------------------------
# Batch construction
# ---------------------------------------------------------------------------

def build_batch(resolutions: list[dict]) -> dict[str, Any]:
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

    add_entity(REF_REMOTE, "property", "annotation_property", "json",
               meta={"label": "远端概念出处"})

    def emit(subject: str, name: str, value_json: dict, *, disc: str,
             confidence: float, quals: dict, remote_ref: dict | None) -> None:
        key = f"wwybsj/L1/{subject}/{name}" + (f"/{disc}" if disc else "")
        prop = f"{P}{name}"
        add_entity(prop, "property", "datatype_property", "json", meta={"label": name})
        statements.append({
            "statement_key": key,
            "subject_id": subject,
            "property_id": prop,
            "value_type": "json",
            "value_json": value_json,
            "status": "accepted",
            "confidence": confidence,
            "created_by": EXTRACTOR,
            "metadata_json": {"domain": TARGET_DOMAIN, "layer": "L1",
                              "statement_key": key, "subject_label": subject},
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
        if remote_ref:
            references.append({
                "statement_key": key,
                "property_id": REF_REMOTE,
                "value_type": "json",
                "value_json": remote_ref,
                # This resolves on the REMOTE gateway, never in this database.
                "source_span": f"{SOURCE_DOMAIN}:{remote_ref.get('concept_id') or remote_ref.get('wiki_slug')}"
                               f" = {remote_ref.get('canonical_name')}",
                "ordinal": 0,
            })

    for r in resolutions:
        subject = r["entity_id"]

        for anchor in r["anchors"]:
            reviewed = "review" in anchor
            # An exact whole-label match asserts most; a component or a
            # broader/narrower mapping asserts less, and says so in the number.
            if anchor["match_relation"] == "exact":
                conf = 0.95 if anchor["is_whole_label"] else 0.8
            else:
                conf = 0.7
            emit(subject, "aligned_to", anchor,
                 disc=f"{anchor['match_relation']}:{anchor['matched_surface']}",
                 confidence=conf,
                 quals={"epistemic_mode": "inferred",
                        "basis": anchor["basis"],
                        "match_kind": anchor["match_kind"],
                        "match_relation": anchor["match_relation"],
                        "remote_cluster_size": {"size": anchor["cluster_size"]},
                        "review_status": (anchor["review"]["review_status"] if reviewed
                                          else "auto_unreviewed"),
                        "resolved_at": anchor["resolved_at"]},
                 remote_ref={"gateway": SOURCE_BASE, "domain": SOURCE_DOMAIN,
                             "concept_ids": anchor["concept_ids"],
                             "primary_concept_id": anchor["primary_concept_id"],
                             "canonical_name": anchor["remote_canonical_name"],
                             "note": "resolves on the remote gateway, not in this "
                                     "database; union the whole cluster"})

        for cand in r["candidates"]:
            promoted = cand.get("promoted_by_review")
            emit(subject, "alignment_candidate", cand,
                 disc=cand["matched_surface"], confidence=0.6 if promoted else 0.3,
                 quals={"epistemic_mode": "hypothesized",
                        "basis": "reviewed_wiki_document_anchor" if promoted
                                 else "remote_wiki_title_match",
                        "match_kind": cand["match_kind"],
                        "review_status": "reviewed_document_only" if promoted
                                         else "blocked_pending_review",
                        "resolved_at": cand["resolved_at"]},
                 remote_ref={"gateway": SOURCE_BASE, "domain": SOURCE_DOMAIN,
                             "wiki_slug": cand["remote_wiki_slug"],
                             "canonical_name": cand["remote_canonical_name"],
                             "note": "candidate only — must not be used as an anchor"})

        for rej in r.get("rejected_exact", []):
            emit(subject, "alignment_rejected", rej, disc=rej["matched_surface"],
                 confidence=1.0,
                 quals={"epistemic_mode": "inferred", "basis": "reviewed_homograph_veto",
                        "review_status": rej.get("reviewer") or "unreviewed",
                        "resolved_at": now_iso()},
                 remote_ref=None)

        emit(subject, "alignment_status",
             {"status": r["status"], "reason": r["reason"],
              "attempted_surfaces": r["attempted"],
              "anchor_count": len(r["anchors"]),
              "rejected_exact_count": len(r.get("rejected_exact", [])),
              "candidate_count": len(r["candidates"]),
              "artifact_uses": r["artifact_uses"],
              "facet": r["facet"], "label": r["label"]},
             disc="", confidence=1.0,
             quals={"epistemic_mode": "inferred", "basis": "alignment_pass",
                    "resolved_at": now_iso()},
             remote_ref=None)

        # Convenience mirror on the entity; statements remain the queryable truth.
        add_entity(subject, "item", "concept", meta={
            "facet": r["facet"], "label": r["label"], "alignment": r["status"],
            "aligned_remote_concept_ids": sorted(
                {cid for a in r["anchors"] for cid in a.get("concept_ids", [])}),
        })

    return {"entities": list(entities.values()), "statements": statements,
            "qualifiers": qualifiers, "references": references}


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_resolution_table(resolutions: list[dict]) -> None:
    print(f"\n{'facet':13s}{'term':20s}{'uses':>5s}  {'status':22s}anchors / candidates")
    print("-" * 104)
    for r in sorted(resolutions, key=lambda x: (x["facet"], -x["artifact_uses"])):
        detail = ", ".join(
            f"{a['matched_surface']}[{a['match_relation']}]→{a['primary_concept_id'][:8]}"
            f"×{a['cluster_size']}" for a in r["anchors"])
        if r["candidates"]:
            detail += ("  |  " if detail else "") + "候选(不用于推理): " + ", ".join(
                c["matched_surface"] for c in r["candidates"])
        print(f"{r['facet']:13s}{r['label']:20s}{r['artifact_uses']:5d}  {r['status']:22s}{detail or '—'}")


def coverage(resolutions: list[dict]) -> None:
    facet_totals: dict[str, dict[str, int]] = {}
    for r in resolutions:
        f = facet_totals.setdefault(r["facet"], {"terms": 0, "aligned_terms": 0,
                                                "uses": 0, "aligned_uses": 0})
        f["terms"] += 1
        f["uses"] += r["artifact_uses"]
        if r["anchors"]:
            f["aligned_terms"] += 1
            f["aligned_uses"] += r["artifact_uses"]
    print(f"\n{'facet':14s}{'terms':>7s}{'aligned':>9s}{'statements covered':>20s}{'aligned':>9s}")
    print("-" * 60)
    for facet, f in sorted(facet_totals.items()):
        print(f"{facet:14s}{f['terms']:7d}{f['aligned_terms']:9d}"
              f"{f['uses']:20d}{f['aligned_uses']:9d}")


def report_written() -> None:
    """Read back what is actually in the domain, through the gateway."""
    status_rows = list_statements(property_id=f"{P}alignment_status")
    by_status: dict[str, dict[str, int]] = {}
    for r in status_rows:
        v = r["value_json"] or {}
        b = by_status.setdefault(str(v.get("status")), {"terms": 0, "artifact_uses": 0})
        b["terms"] += 1
        b["artifact_uses"] += int(v.get("artifact_uses") or 0)
    print(f"\n{'alignment_status':34s}{'terms':>7s}{'artifact_uses':>15s}")
    print("-" * 56)
    for st, b in sorted(by_status.items(), key=lambda kv: -kv[1]["terms"]):
        print(f"{st:34s}{b['terms']:7d}{b['artifact_uses']:15d}")

    anchor_rows = list_statements(property_id=f"{P}aligned_to")
    by_rel: dict[str, dict[str, Any]] = {}
    for r in anchor_rows:
        v = r["value_json"] or {}
        b = by_rel.setdefault(str(v.get("match_relation")),
                              {"anchors": 0, "targets": set(), "ids": 0})
        b["anchors"] += 1
        b["targets"].add(v.get("primary_concept_id"))
        b["ids"] += len(v.get("concept_ids") or [])
    print(f"\n{'match_relation':18s}{'anchors':>9s}{'distinct_targets':>18s}"
          f"{'remote_ids_reachable':>22s}")
    print("-" * 68)
    for rel, b in sorted(by_rel.items(), key=lambda kv: -kv[1]["anchors"]):
        print(f"{rel:18s}{b['anchors']:9d}{len(b['targets']):18d}{b['ids']:22d}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--execute", action="store_true", help="Write (default: preview only)")
    p.add_argument("--refresh", action="store_true", help="Ignore the xref cache and re-resolve")
    p.add_argument("--report", action="store_true", help="Report alignment already in the DB")
    p.add_argument("--review", default=str(REVIEW_PATH),
                   help="Reviewer verdicts on the candidate queue (JSON).")
    p.add_argument("--out-dir", default=str(L1_OUT_DIR))
    args = p.parse_args()

    if args.report:
        report_written()
        return 0

    terms = load_terms()
    print(f"local terms: {len(terms)}  (alignable facets: {sorted(ALIGNABLE_FACETS)})")
    review = load_review(Path(args.review))
    print(f"review file: {args.review}  ({review['_status']}, {review['_reviewed_at']})")
    resolutions = [resolve_term(t, args.refresh, review) for t in terms]

    print_resolution_table(resolutions)
    coverage(resolutions)

    batch = build_batch(resolutions)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    plan_path = out_dir / "l1_alignment.json"
    plan_path.write_text(json.dumps(resolutions, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nstatements : {len(batch['statements'])}"
          f"  (anchors {sum(1 for s in batch['statements'] if s['property_id'].endswith('aligned_to'))},"
          f" candidates {sum(1 for s in batch['statements'] if s['property_id'].endswith('alignment_candidate'))},"
          f" status {len(resolutions)})")
    print(f"remote refs: {len(batch['references'])}")
    print(f"plan       : {plan_path}")
    print(call_summary())

    if not args.execute:
        print("\nPREVIEW ONLY — pass --execute to write to the local TDB.")
        return 0

    result = post("/ontology/semantic/upsert-batch", batch)
    if "error" in result:
        print(f"✗ {result['error']}", file=sys.stderr)
        return 1
    print(f"\n✓ wrote {len(batch['statements'])} L1 statements")
    counts: dict[str, int] = {}
    for pid in (f"{P}aligned_to", f"{P}alignment_candidate",
                f"{P}alignment_rejected", f"{P}alignment_status"):
        for r in list_statements(property_id=pid):
            if r["layer"] == "L1" and r["created_by"] != EXTRACTOR:
                counts[r["created_by"]] = counts.get(r["created_by"], 0) + 1
    stale = "; ".join(f"{k}: {n}" for k, n in sorted(counts.items()))
    if stale:
        # statement_key changes between extractor versions orphan the old rows:
        # they are not overwritten, they simply stop being regenerated.
        print(f"\n!! stale L1 rows from an earlier extractor version:\n   {stale}\n"
              f"   they are orphans (statement_key shape changed) — delete them.")
    report_written()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
