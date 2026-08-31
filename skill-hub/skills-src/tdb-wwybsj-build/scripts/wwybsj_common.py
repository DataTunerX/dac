#!/usr/bin/env python3
"""
wwybsj_common.py — Shared helpers for building the `wwybsj` TDB domain
from the museum artifact registry (a2a/agents/wwybsj/wwybsj.json).

Nothing here talks to the LLM. It only:
  - loads / normalizes artifact records
  - derives stable slugs and concept ids
  - wraps the TDB v2 gateway HTTP API
"""

from __future__ import annotations

import json
import os
import re
import socket
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Two gateways, deliberately separate.
#
#   SOURCE = remote, READ-ONLY. The full Chinese archaeology corpus
#            (中国博物馆学基础 / 文物学 / 陶瓷工艺学 / 中国古代金属技术 /
#             考古测量学 / 中国古代建筑史). We research against it, never write.
#   TARGET = local, READ-WRITE. Where the wwybsj domain is built.
#
# Physically separate databases; logically joinable, because every reused
# concept records the SOURCE canonical_name AND the SOURCE concept UUID as an
# xref, recorded by wwybsj_l1.py as a same-name concept CLUSTER, so it can be
# resolved back on demand without either database sharing storage.
SOURCE_BASE = os.environ.get("WWYBSJ_SOURCE_GATEWAY", "http://10.124.48.91:8989")
TARGET_BASE = os.environ.get("WWYBSJ_TARGET_GATEWAY", "http://10.124.48.91:8997")

SOURCE_DOMAIN = "archeology"             # the domain we research AGAINST (remote)
TARGET_DOMAIN = "wwybsj"                 # the domain we BUILD (local)
STREAM_ID = "wwybsj.artifacts"           # provenance stream for registry records

# There is NO database handle here, deliberately.
#
# Every read of the built domain goes through TARGET_BASE, exactly like every
# write. This skill must never open a Postgres connection: the gateway is the
# only contract we are entitled to depend on, and the previous split — writes
# through the gateway, reads through psql — silently tore the domain in two the
# moment the gateway was repointed at a different database. Read helpers live in
# the "Gateway reads" section below; if something cannot be expressed against
# the v2 API, it does not belong in this skill.

DATA_JSON = Path("/Users/ningwu/eis/a2a/agents/wwybsj/wwybsj.json")
OUT_DIR = Path("/Users/ningwu/eis/a2a/agents/wwybsj/out")

# Incremental intake overlay.
#
# The 465-record base registry is a frozen dump — a demo that wants to show the
# build pipeline on a NEW artifact must not edit it. New records are written to
# this overlay instead, and load_records() merges base + overlay (overlay wins
# on a colliding `id`). Everything downstream — ingest, L0, L1, research, wiki —
# therefore sees new items with no further change.
NEW_ITEMS_JSON = Path(os.environ.get(
    "WWYBSJ_NEW_ITEMS", str(OUT_DIR / "wwybsj_new_items.json")))

EXTRACTOR = "wwybsj_builder_v1"


# ---------------------------------------------------------------------------
# Field dictionary — SQL column -> human meaning (from the original DDL COMMENTs)
# ---------------------------------------------------------------------------

FIELDS: dict[str, str] = {
    "id":              "记录ID",
    "ww_bh_leixing":   "编号名称",
    "ww_bianhao":      "编号",
    "ww_mingchen":     "文物名称",
    "ww_yuanming":     "文物原名",
    "ww_niandai_a":    "年代a",
    "ww_niandai_b":    "年代b",
    "ww_niandai_c":    "年代c",
    "ww_niandai_d":    "年代d",
    "ww_niandai_jt":   "具体年代",
    "ww_leibie":       "文物类别",
    "ww_zhidi_a":      "质地a",
    "ww_zhidi_b":      "质地b",
    "ww_zhidi_c":      "质地c",
    "ww_shuliang":     "数量",
    "ww_chang":        "长",
    "ww_kuan":         "宽",
    "ww_gao":          "高",
    "ww_chicun":       "尺寸",
    "ww_zhiliang_fw":  "质量范围",
    "ww_zhiliang_jt":  "具体质量",
    "ww_zhiliang_dw":  "质量单位",
    "ww_jibie":        "文物级别",
    "ww_laiyuan":      "文物来源",
    "ww_wancan_cd":    "完残程度",
    "ww_wancan_zk":    "完残状况",
    "ww_baocun_zt":    "保存状态",
    "ww_baocun_sj":    "保存时间",
    "ww_baocun_nd":    "保存年代",
    "ww_zuoze":        "作者",
    "ww_banben":       "版本",
    "ww_cunjuan":      "存卷",
    "ww_mingchen_en":  "英文名",
    "ww_ctime":        "入库时间",
    "ww_mtime":        "修改时间",
}

# Chinese -> English probes, used to reach the (largely English) wiki/ontology
# layers of archeology_expert. Only high-signal terms; unknown terms are simply
# probed in Chinese.
ZH_EN_PROBES: dict[str, list[str]] = {
    "陶器":             ["pottery", "ceramics"],
    "瓷器":             ["porcelain", "glazed ceramics"],
    "石器、石刻、砖瓦":  ["stone tool", "stone carving", "brick and tile"],
    "铁器、其他金属器":  ["iron artifact", "metal artifact"],
    "铜器":             ["bronze", "bronze vessel"],
    "金银器":           ["gold and silver artifact"],
    "玉石器":           ["jade artifact"],
    "骨角牙器":         ["bone tool", "antler artifact"],
    "钱币":             ["coin", "currency"],
    "陶":               ["pottery", "fired clay"],
    "砖瓦":             ["brick and tile", "roof tile"],
    "瓷":               ["porcelain"],
    "石":               ["stone"],
    "铁":               ["iron"],
    "铜":               ["bronze", "copper"],
    "其他金属":         ["metal"],
    "骨":               ["bone"],
    "玉":               ["jade"],
    "无机质":           ["inorganic material"],
    "有机质":           ["organic material"],
    "发掘":             ["excavation", "archaeological excavation"],
    "旧藏":             ["museum collection", "old collection"],
    "征集":             ["acquisition", "collecting"],
    "渤海":             ["Balhae", "Bohai kingdom"],
    "辽":               ["Liao dynasty"],
    "金":               ["Jin dynasty"],
    "汉":               ["Han dynasty"],
    "唐":               ["Tang dynasty"],
    "宋":               ["Song dynasty"],
    "明":               ["Ming dynasty"],
    "清":               ["Qing dynasty"],
    "新石器时代":       ["Neolithic"],
    "青铜时代":         ["Bronze Age"],
    "铁器时代":         ["Iron Age"],
}


# ---------------------------------------------------------------------------
# Traditional -> Simplified normalization
#
# The remote corpus is mixed-script: 中国古代建筑史（第二版）reproduces plate
# captions from its older edition in traditional characters, while everything
# else is simplified. The registry is entirely simplified. Without folding, 柱础
# never matches 柱礎 and 绿釉 never matches 綠琉璃 — evidence gets silently
# dropped and a well-covered artifact grades as `thin`.
#
# The table is OpenCC's official TSCharacters mapping, vendored to t2s_chars.json
# so there is no runtime dependency. Direction matters: traditional -> simplified
# is many-to-one and safe to apply blindly. The reverse (简 -> 繁) is ambiguous
# (发 -> 發/髮) and is deliberately NOT done anywhere in this skill.
#
# This is a CHARACTER table, not a phrase table, which is all 2-gram matching
# needs. It will not fix phrase-level differences in vocabulary.
# ---------------------------------------------------------------------------

_T2S_PATH = Path(__file__).resolve().parent / "t2s_chars.json"
try:
    with open(_T2S_PATH, encoding="utf-8") as _f:
        _T2S: dict = json.load(_f)
    _T2S_TABLE = str.maketrans(_T2S)
except FileNotFoundError:                      # degrade loudly, never silently
    _T2S, _T2S_TABLE = {}, {}
    print(f"WARNING: {_T2S_PATH.name} missing — traditional text will not match "
          f"simplified probes, so coverage will be UNDER-reported.",
          file=sys.stderr, flush=True)


def to_simplified(text: str) -> str:
    """Fold traditional characters to simplified. Idempotent on simplified input."""
    return (text or "").translate(_T2S_TABLE) if _T2S_TABLE else (text or "")


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Call instrumentation
#
# The remote gateway occasionally stalls for a full 30s (its backend gRPC
# timeout) and then answers with an empty result set rather than an error. With
# a few hundred sequential calls per record, one such stall makes the whole run
# look hung with nothing on screen to explain it. So: every call is timed, slow
# calls are announced as they happen, and timeouts get one retry.
# ---------------------------------------------------------------------------

DEBUG = os.environ.get("WWYBSJ_DEBUG", "") not in ("", "0", "false")
SLOW_CALL_SECS = float(os.environ.get("WWYBSJ_SLOW_SECS", "3"))
DEFAULT_TIMEOUT = int(os.environ.get("WWYBSJ_HTTP_TIMEOUT", "25"))
# LLM generations routinely run tens of seconds, so the 3s gateway threshold
# would flag every single one. Report them against their own bar.
LLM_SLOW_SECS = float(os.environ.get("WWYBSJ_LLM_SLOW_SECS", "60"))

STATS: dict = {"calls": 0, "seconds": 0.0, "slow": [], "errors": [],
               "retries": 0, "suspect_timeouts": []}

_LIST_KEYS = ("facts", "concepts", "results", "pages", "hits",
              "relation_candidates", "bindings", "evidence")


def _looks_empty(payload) -> bool:
    """True when a 200 response carries no rows in any of its list fields."""
    if not isinstance(payload, dict):
        return False
    present = [k for k in _LIST_KEYS if k in payload]
    return bool(present) and all(not payload.get(k) for k in present)


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _short(base: str) -> str:
    if base == SOURCE_BASE:
        return "remote"
    if base == TARGET_BASE:
        return "local"
    return "llm"   # the only other base that reaches _request


# Transient backend states. The remote search backend answers 503
# BACKEND_UNAVAILABLE under back-to-back heavy queries and recovers within
# seconds (observed: two 503s, then a 0.8s success). Returning that as an error
# to the caller makes a momentary overload look exactly like "no data" — the same
# false-negative trap as caching a miss.
_RETRYABLE_HTTP = {429, 500, 502, 503, 504}
_BACKOFF_SECS = (1.0, 3.0, 7.0)


def _request(req_or_url, path: str, base: str, timeout: int, retries: int = 1,
             slow_secs: float = SLOW_CALL_SECS) -> dict:
    """Execute with timing, slow-call reporting, and retries on timeout/5xx."""
    attempt = 0
    while True:
        started = time.monotonic()
        try:
            with urllib.request.urlopen(req_or_url, timeout=timeout) as r:
                payload = json.loads(r.read())
            elapsed = time.monotonic() - started
            STATS["calls"] += 1
            STATS["seconds"] += elapsed

            # The backend's gRPC deadline is 30s. When it trips, the gateway
            # answers 200 with an EMPTY result set instead of an error — which
            # is indistinguishable from "this concept genuinely has no data".
            # Left undetected, a stalled call silently becomes a false
            # "no coverage" finding. Flag the shape rather than trust it.
            if elapsed >= 28 and _looks_empty(payload):
                STATS["suspect_timeouts"].append((round(elapsed, 1), _short(base), path))
                _log(f"    [SUSPECT TIMEOUT {elapsed:.1f}s] {_short(base)} {path} — "
                     f"empty result after ~30s backend deadline; treat as UNKNOWN, not as empty")
                payload = dict(payload) if isinstance(payload, dict) else {}
                payload["_suspect_timeout"] = True
            elif elapsed >= slow_secs:
                STATS["slow"].append((round(elapsed, 1), _short(base), path))
                _log(f"    [slow {elapsed:.1f}s] {_short(base)} {path}")
            elif DEBUG:
                _log(f"    [{elapsed:.2f}s] {_short(base)} {path}")
            return payload
        except HTTPError as e:
            elapsed = time.monotonic() - started
            STATS["calls"] += 1
            STATS["seconds"] += elapsed
            detail = f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}"
            if e.code in _RETRYABLE_HTTP and attempt < retries:
                pause = _BACKOFF_SECS[min(attempt, len(_BACKOFF_SECS) - 1)]
                attempt += 1
                STATS["retries"] += 1
                _log(f"    [HTTP {e.code} {elapsed:.1f}s] {_short(base)} {path} — "
                     f"retry {attempt}/{retries} after {pause:.0f}s")
                time.sleep(pause)
                continue
            STATS["errors"].append((_short(base), path, detail[:120]))
            _log(f"    [ERR {elapsed:.1f}s] {_short(base)} {path} → {detail[:160]}")
            return {"error": detail}
        except Exception as e:
            elapsed = time.monotonic() - started
            STATS["calls"] += 1
            STATS["seconds"] += elapsed
            is_timeout = isinstance(e, socket.timeout) or "timed out" in str(e).lower()
            if is_timeout and attempt < retries:
                attempt += 1
                STATS["retries"] += 1
                _log(f"    [timeout {elapsed:.1f}s] {_short(base)} {path} — retry {attempt}/{retries}")
                continue
            STATS["errors"].append((_short(base), path, str(e)[:120]))
            _log(f"    [ERR {elapsed:.1f}s] {_short(base)} {path} → {e}")
            return {"error": str(e)}


def llm_chat(cfg: dict, payload: dict, retries: int = 2) -> str:
    """POST an OpenAI-style chat completion and return the message content.

    Shares _request's timing, retry and reporting policy with the gateway
    calls, so a 429/5xx or a read timeout from the LLM endpoint is retried
    with backoff instead of killing the run. Chat completions have no side
    effects, so replaying one is safe.

    Raises RuntimeError when the call fails or the response carries no
    choices — callers here rely on exceptions, not on an {"error": ...} dict.
    The suspect-timeout heuristic in _request is inert for this payload
    shape: it only fires on responses carrying one of the gateway's list
    keys, and "choices" is not one of them.
    """
    base = str(cfg.get("baseUrl") or "").rstrip("/")
    if not base:
        raise RuntimeError("LLM config missing baseUrl")
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {cfg.get('apiKey') or 'EMPTY'}"},
        method="POST")
    timeout = int(cfg.get("timeoutSeconds") or 300)
    data = _request(req, "/chat/completions", base, timeout, retries,
                    slow_secs=LLM_SLOW_SECS)
    if not isinstance(data, dict) or "choices" not in data:
        detail = data.get("error") if isinstance(data, dict) else repr(data)[:300]
        if detail is None:
            detail = json.dumps(data, ensure_ascii=False)[:300]
        raise RuntimeError(f"LLM 调用失败: {detail}")
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(
            f"LLM 响应结构异常: {json.dumps(data, ensure_ascii=False)[:300]}") from e


def call_summary() -> str:
    s = (f"HTTP: {STATS['calls']} calls, {STATS['seconds']:.1f}s total, "
         f"{STATS['retries']} retries, {len(STATS['errors'])} errors, "
         f"{len(STATS['suspect_timeouts'])} suspect timeouts")
    if STATS["suspect_timeouts"]:
        s += ("\n  ⚠ SUSPECT TIMEOUTS (empty result after ~30s backend deadline — "
              "these are UNKNOWN, not empty; re-run before concluding no coverage):\n    "
              + "; ".join(f"{t}s {w} {p}" for t, w, p in STATS["suspect_timeouts"][:5]))
    if STATS["slow"]:
        worst = sorted(STATS["slow"], reverse=True)[:5]
        s += "\n  slowest: " + "; ".join(f"{t}s {w} {p}" for t, w, p in worst)
    if STATS["errors"]:
        s += "\n  errors : " + "; ".join(f"{w} {p} → {d}" for w, p, d in STATS["errors"][:5])
    return s


def get(path: str, params: dict | None = None, base: str = TARGET_BASE,
        timeout: int = DEFAULT_TIMEOUT, retries: int = 1) -> dict:
    url = base + "/v2" + path
    if params:
        url += "?" + urlencode(params)
    return _request(url, path, base, timeout, retries)


def post(path: str, body: dict, base: str = TARGET_BASE,
         timeout: int = DEFAULT_TIMEOUT, retries: int = 1) -> dict:
    data = json.dumps(body, ensure_ascii=False).encode()
    req = urllib.request.Request(
        base + "/v2" + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return _request(req, path, base, timeout, retries)


# Convenience wrappers so call sites can never mix up read-source and write-target.
def sget(path: str, params: dict | None = None, timeout: int = 20,
         retries: int = 3) -> dict:
    """GET against the remote research corpus (read-only)."""
    return get(path, params, base=SOURCE_BASE, timeout=timeout, retries=retries)


def spost(path: str, body: dict, timeout: int = 60, retries: int = 3) -> dict:
    """POST against the remote research corpus — search/query only, never writes."""
    return post(path, body, base=SOURCE_BASE, timeout=timeout, retries=retries)


# ---------------------------------------------------------------------------
# Gateway reads — the ONLY way this skill reads the domain back
# ---------------------------------------------------------------------------
#
# There used to be a psql shortcut here. It is gone. Everything below is built
# out of four v2 endpoints:
#
#   GET /ontology/statement/list        subject_id | property_id | value_entity_id
#   GET /ontology/statement/provenance  references (+ source_span) of one statement
#   GET /wiki/pages, /wiki/page         the domain's wiki
#   GET /ontology/object-type|relation-type/list
#
# `statement/list` has no domain filter, so a whole-domain scan is expressed as
# "every predicate the contract declares" — which is why PREDICATE_CONTRACT is
# authoritative rather than decorative. A predicate in the database but not in
# the contract is invisible to a contract-driven scan; wwybsj_predicates.py's V1
# check exists precisely to catch that, and it scans by subject instead.

CONTRACT_PATH = Path(__file__).resolve().parent.parent / "predicate_contract.json"

_contract_cache: dict | None = None

STATEMENT_PAGE = 500          # the endpoint's maximum
_OFFSET_CEILING = 10000       # the endpoint's maximum


def predicate_contract() -> dict:
    global _contract_cache
    if _contract_cache is None:
        _contract_cache = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    return _contract_cache


def contract_predicate_ids() -> list[str]:
    """Fully-qualified property ids for every predicate the contract declares."""
    return [f"wwybsj.predicate.{p['name']}" for p in predicate_contract()["predicates"]]


def _flatten(row: dict) -> dict:
    """
    One `statement/list` item -> the flat shape every caller here wants.

    The wire names are graph-flavoured (`subject_concept_id`, `predicate`,
    `object_concept_id`); the shape below keeps the storage-flavoured names the
    build scripts were written against, so a caller never has to remember which
    of the two vocabularies it is holding.
    """
    st = row.get("statement") or {}
    quals = row.get("qualifiers") or []
    meta = st.get("metadata") or {}
    obj = st.get("object_concept_id") or ""
    prop = st.get("predicate", "")
    q_text: dict[str, Any] = {}
    for q in quals:
        name = q.get("property_id", "").replace("wwybsj.qualifier.", "")
        v = q.get("value")
        q_text[name] = v.get("text") if isinstance(v, dict) and "text" in v else v
    return {
        "statement_id":    st.get("statement_id", ""),
        "subject_id":      st.get("subject_concept_id", ""),
        "property_id":     prop,
        "name":            prop.replace("wwybsj.predicate.", ""),
        "value_type":      st.get("value_type", ""),
        "value_entity_id": obj,
        "value_json":      st.get("value_json") or {},
        "status":          st.get("status", ""),
        "confidence":      st.get("confidence", 0),
        "created_by":      st.get("created_by", ""),
        "metadata":        meta,
        "layer":           meta.get("layer", ""),
        "statement_key":   meta.get("statement_key", ""),
        "registry_no":     meta.get("registry_no", ""),
        "qualifiers":      q_text,
        "qualifier_rows":  quals,
    }


def list_statements(subject_id: str | None = None, property_id: str | None = None,
                    value_entity_id: str | None = None,
                    status: str = "all") -> list[dict]:
    """
    Every matching statement, paged to exhaustion, flattened by `_flatten`.

    `status='all'` is the default on purpose: these helpers replaced direct table
    reads, and the endpoint's default quietly hides rejected/deprecated rows.
    An audit that cannot see a rejected row cannot report it.
    """
    params: dict[str, Any] = {"limit": STATEMENT_PAGE, "status": status}
    if subject_id:
        params["subject_id"] = subject_id
    if property_id:
        params["property_id"] = property_id
    if value_entity_id:
        params["value_entity_id"] = value_entity_id

    out: list[dict] = []
    offset = 0
    while True:
        params["offset"] = offset
        page = get("/ontology/statement/list", dict(params))
        if "error" in page:
            raise SystemExit(f"statement/list failed: {page['error']}")
        rows = page.get("statements") or []
        out.extend(_flatten(r) for r in rows)
        if len(rows) < STATEMENT_PAGE:
            return out
        offset += STATEMENT_PAGE
        if offset > _OFFSET_CEILING:
            # Silently returning a truncated set here would look exactly like a
            # small predicate, and every count downstream would be wrong.
            raise SystemExit(
                f"statement/list offset ceiling hit for {params.get('property_id')!r} "
                f"({_OFFSET_CEILING}); narrow the query")


def get_statement(statement_id: str) -> dict | None:
    """One statement by id, flattened. None if it is gone."""
    r = get("/ontology/statement/get", {"statement_id": statement_id})
    if "error" in r or not r.get("statement"):
        return None
    return _flatten({"statement": r["statement"], "qualifiers": r.get("qualifiers") or []})


def statement_references(statement_id: str) -> list[dict]:
    """References (with source_span) of one statement, via /statement/provenance."""
    r = get("/ontology/statement/provenance",
            {"statement_id": statement_id, "include_locators": "false"})
    if "error" in r:
        return []
    return r.get("references") or []


def load_domain(predicates: list[str] | None = None,
                layers: set[str] | None = None,
                progress: bool = False) -> list[dict]:
    """
    A snapshot of the domain: every statement of every contract predicate.

    This is the gateway-side stand-in for `select * from semantic_statement
    where metadata_json->>'domain'='wwybsj'`. It costs one request per predicate
    per 500 rows — roughly 40 requests for the full ~12k-statement domain.
    """
    ids = predicates if predicates is not None else contract_predicate_ids()
    rows: list[dict] = []
    for i, pid in enumerate(ids, 1):
        got = list_statements(property_id=pid)
        if layers is not None:
            got = [r for r in got if r["layer"] in layers]
        rows.extend(got)
        if progress:
            _log(f"[domain {i}/{len(ids)}] {pid.replace('wwybsj.predicate.', '')}: {len(got)}")
    return rows


def index_by_subject(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["subject_id"], []).append(r)
    return out


def subject_statements(subject_id: str) -> list[dict]:
    """Every statement about one subject, in property order."""
    rows = list_statements(subject_id=subject_id)
    rows.sort(key=lambda r: (r["property_id"], r["statement_id"]))
    return rows


def all_registry_nos() -> list[str]:
    """Registry numbers of every artifact L0 has written, sorted."""
    rows = list_statements(property_id="wwybsj.predicate.has_registry_no")
    return sorted({r["registry_no"] for r in rows if r["registry_no"]})


TERM_PREDICATES = (
    "wwybsj.predicate.instantiates",
    "wwybsj.predicate.made_of",
    "wwybsj.predicate.has_grade",
    "wwybsj.predicate.acquired_by",
    "wwybsj.predicate.has_completeness",
    "wwybsj.predicate.in_period",
)


def load_term_usage() -> dict[str, int]:
    """
    `wwybsj.term.*` id -> how many statements point at it.

    Replaces a scan of `semantic_entity`, which the gateway does not expose.
    Term entities exist only because one of TERM_PREDICATES references them, so
    counting the referring statements finds every term and its reach at once.
    """
    uses: dict[str, int] = {}
    for pid in TERM_PREDICATES:
        for r in list_statements(property_id=pid):
            tid = r["value_entity_id"]
            if tid.startswith("wwybsj.term."):
                uses[tid] = uses.get(tid, 0) + 1
    return uses


def wiki_page_slugs(domain: str = TARGET_DOMAIN) -> list[str]:
    pages = _paged("/wiki/pages", "pages", {"domain": domain}, page=1000)
    return sorted(p["slug"] for p in pages)


def wiki_page(slug: str, domain: str = TARGET_DOMAIN) -> dict | None:
    r = get("/wiki/page", {"domain": domain, "slug": slug})
    if "error" in r:
        return None
    return r.get("page")


def _paged(path: str, key: str, params: dict | None = None,
           page: int = 200) -> list[dict]:
    """Drain a `limit`/`offset` list endpoint. 200 is the v2 maximum for these."""
    out: list[dict] = []
    offset = 0
    while True:
        q = dict(params or {})
        q.update({"limit": page, "offset": offset})
        r = get(path, q)
        if "error" in r:
            raise SystemExit(f"{path} failed: {r['error']}")
        rows = r.get(key) or []
        out.extend(rows)
        if len(rows) < page:
            return out
        offset += page


def object_type_ids() -> set[str]:
    return {t["type_id"] for t in _paged("/ontology/object-type/list", "object_types")}


def relation_types(prefix: str = "wwybsj.predicate.") -> list[dict]:
    rows = _paged("/ontology/relation-type/list", "relation_types")
    return sorted((t for t in rows if t.get("predicate", "").startswith(prefix)),
                  key=lambda t: t["predicate"])


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

def load_new_items(path: Path | None = None) -> list[dict]:
    """Records added after the base dump (see NEW_ITEMS_JSON). [] if none."""
    path = path or NEW_ITEMS_JSON
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("records", data) if isinstance(data, dict) else data


def load_records(path: Path = DATA_JSON, include_new: bool = True) -> list[dict]:
    """Base registry, with the intake overlay merged in (overlay wins by id)."""
    with open(path, encoding="utf-8") as f:
        records = json.load(f)
    if not include_new:
        return records
    extra = load_new_items()
    if not extra:
        return records
    by_id = {r["id"]: i for i, r in enumerate(records)}
    for rec in extra:
        if rec["id"] in by_id:
            records[by_id[rec["id"]]] = rec
        else:
            records.append(rec)
    return records


def clean(v) -> str:
    """Normalize a raw field value into a trimmed display string ('' if empty)."""
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s in {"", "0", "0.00", "0.000"} else s


def get_record(rec_id: int, path: Path = DATA_JSON) -> dict:
    for r in load_records(path):
        if r["id"] == rec_id:
            return r
    raise SystemExit(f"record id={rec_id} not found in {path}")


def bianhao(rec: dict) -> str:
    """Zero-padded registry number, e.g. '4 ' -> '0004'."""
    raw = clean(rec.get("ww_bianhao"))
    digits = re.sub(r"\D", "", raw)
    return digits.zfill(4) if digits else f"id{rec['id']}"


def slug(rec: dict) -> str:
    """Stable, human-readable wiki slug: ww-0004-渤海绿釉柱础护圈"""
    name = clean(rec.get("ww_mingchen")) or f"artifact-{rec['id']}"
    name = re.sub(r"[\s/\\]+", "-", name)
    return f"ww-{bianhao(rec)}-{name}"


def title(rec: dict) -> str:
    name = clean(rec.get("ww_mingchen")) or f"文物 {rec['id']}"
    return f"{name}（{clean(rec.get('ww_bh_leixing')) or '编号'} {bianhao(rec)}）"


# ---------------------------------------------------------------------------
# Semantic statement identity
#
# The backend derives a statement's id from its key:
#
#   statement_id = uuid5(NAMESPACE_URL, "tdb.semantic_statement:" + statement_key)
#   (tdb/src/rpc/ontology.rs, semantic_statement_uuid)
#
# and upserts with ON CONFLICT (statement_id) DO UPDATE. So a deterministic key
# gives us true idempotency for free: re-running a record UPDATES its statements
# in place instead of inserting duplicates.
#
# This is the whole reason the skill writes statements rather than legacy facts.
# fact/upsert-with-evidence keys on (src, predicate, dst, qualifier_json) — the
# qualifier is part of the identity — so merely editing a qualifier forked a
# second fact row, and a record re-run silently doubled its fact set.
# ---------------------------------------------------------------------------

def zhidi(rec: dict) -> str:
    """Most specific material term available (质地c > 质地b > 质地a)."""
    for k in ("ww_zhidi_c", "ww_zhidi_b", "ww_zhidi_a"):
        v = clean(rec.get(k))
        if v and v != "单一质地":
            return v
    return ""


def niandai(rec: dict) -> str:
    """Best era label: 具体年代 preferred, else the a/b/c/d ladder."""
    v = clean(rec.get("ww_niandai_jt"))
    if v:
        return v
    for k in ("ww_niandai_d", "ww_niandai_c", "ww_niandai_b", "ww_niandai_a"):
        v = clean(rec.get(k))
        if v and v not in {"其他", "中国历史学年代"}:
            return v
    return ""


def dimensions(rec: dict) -> str:
    parts = []
    for k, lbl in (("ww_chang", "长"), ("ww_kuan", "宽"), ("ww_gao", "高")):
        v = clean(rec.get(k))
        if v:
            parts.append(f"{lbl}{v}")
    chicun = clean(rec.get("ww_chicun"))
    if chicun:
        parts.append(chicun)
    return " ".join(parts)


def mass(rec: dict) -> str:
    jt = clean(rec.get("ww_zhiliang_jt"))
    dw = clean(rec.get("ww_zhiliang_dw"))
    fw = clean(rec.get("ww_zhiliang_fw"))
    out = f"{jt}{dw}" if jt else ""
    if fw:
        out = f"{out}（范围 {fw}）" if out else f"范围 {fw}"
    return out


def record_text(rec: dict) -> str:
    """
    Render one registry record as a self-contained Chinese paragraph.
    This is what gets appended to the provenance stream, so every fact written
    later can point back at a real sentence.
    """
    lines = [f"# {title(rec)}", ""]
    for key, label in FIELDS.items():
        if key in {"id", "ww_ctime", "ww_mtime"}:
            continue
        v = clean(rec.get(key))
        if v:
            lines.append(f"- {label}：{v}")
    lines += ["", "## 登记摘要", ""]
    seg = [f"{clean(rec.get('ww_mingchen'))}"]
    if niandai(rec):
        seg.append(f"年代为{niandai(rec)}")
    if clean(rec.get("ww_leibie")):
        seg.append(f"属{clean(rec['ww_leibie'])}类")
    if zhidi(rec):
        seg.append(f"质地为{zhidi(rec)}")
    if dimensions(rec):
        seg.append(f"尺寸{dimensions(rec)}")
    if mass(rec):
        seg.append(f"质量{mass(rec)}")
    if clean(rec.get("ww_jibie")):
        seg.append(f"定级为{clean(rec['ww_jibie'])}文物")
    if clean(rec.get("ww_laiyuan")):
        seg.append(f"来源为{clean(rec['ww_laiyuan'])}")
    if clean(rec.get("ww_wancan_cd")):
        seg.append(f"完残程度{clean(rec['ww_wancan_cd'])}")
    if clean(rec.get("ww_wancan_zk")):
        seg.append(f"（{clean(rec['ww_wancan_zk'])}）")
    if clean(rec.get("ww_baocun_zt")):
        seg.append(f"保存状态为{clean(rec['ww_baocun_zt'])}")
    lines.append("，".join(seg) + "。")
    return "\n".join(lines)


def probes_for(rec: dict) -> list[str]:
    """
    Build the round-1 retrieval probes for this record: Chinese registry terms
    plus their English equivalents where we have a mapping.

    Registry-administrative fields (来源/级别/保存状态) are deliberately NOT
    probed: '旧藏' / 'old collection' are collection-management vocabulary, not
    archaeology concepts, and they only ever pull in literal-substring noise
    ('Old Testament', 'Oral Law Collection').
    """
    seeds: list[str] = []
    for k in ("ww_mingchen", "ww_yuanming", "ww_leibie"):
        v = clean(rec.get(k))
        if v:
            seeds.append(v)
    if zhidi(rec):
        seeds.append(zhidi(rec))
    if niandai(rec):
        seeds.append(niandai(rec))

    out: list[str] = []

    def add(x: str) -> None:
        # Single CJK characters ('陶', '石') match as substrings inside unrelated
        # words ('立陶宛', '熏陶') and are worthless as probes.
        if len(x) < 2:
            return
        if x not in out:
            out.append(x)

    for s in seeds:
        add(s)
        for en in ZH_EN_PROBES.get(s, []):
            add(en)
    # era / material words hide inside composite fields like "渤海（698年—926）"
    haystack = (niandai(rec) or "") + (clean(rec.get("ww_zhidi_c")) or "")
    for zh, ens in ZH_EN_PROBES.items():
        if zh and zh in haystack:
            for en in ens:
                add(en)
    return out


# ---------------------------------------------------------------------------
# Concepts
# ---------------------------------------------------------------------------

_XREF_CACHE_PATH = OUT_DIR / "xref_cache.json"
_xref_cache: dict | None = None


def _load_xref_cache() -> dict:
    global _xref_cache
    if _xref_cache is None:
        try:
            with open(_XREF_CACHE_PATH, encoding="utf-8") as f:
                _xref_cache = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            _xref_cache = {}
    return _xref_cache


def _save_xref_cache() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(_XREF_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(_load_xref_cache(), f, ensure_ascii=False, indent=2, sort_keys=True)


def lookup_source_concept(label: str, refresh: bool = False) -> dict | None:
    """
    Exact-name lookup in the REMOTE research corpus. POSITIVE results only are
    memoized to disk.

    Why the cache exists: the resolution used to land in an ontology_fact
    qualifier, and upsert_fact_with_evidence keyed on
    (src, predicate, dst, qualifier_json). A remote hiccup that resolved an xref
    on one run and missed it on the next wrote two DIFFERENT fact rows for the
    same claim — observed live, alternating 9 facts back and forth every run.

    Why negatives are NOT cached any more: a miss is not a fact about the corpus,
    it is a fact about one request. Two failure modes were freezing false
    negatives into the cache permanently:
      - a transient error (HTTP 400/timeout/empty body) is indistinguishable from
        "absent" at this layer, and `sget` reports it as an empty result;
      - the concept probe used limit=10 against a SUBSTRING search, so 铁器 —
        which has 27 exactly-named concepts — resolved to `null`/wiki and stayed
        that way. Nine terms were wrongly declared concept-less because of it.
    A miss now costs one request per run and is never remembered as an answer.
    Idempotency is unaffected in the statement-native path: `statement_key` is
    derived from (registry_no, predicate, object) and never from the xref, so a
    later resolution updates a row in place instead of forking a new one.

    Tries the ontology layer first, then falls back to the wiki layer. The two
    are NOT in one-to-one correspondence: 琉璃 has a wiki page but no concept of
    that exact name (concept/search only returns compounds like 琉璃玺 /
    辉县琉璃阁). Without the wiki fallback such terms lose a link they could have.

    Returns a dict with `xref_kind` = "concept" or "wiki_page", or None.
    We never write to the remote — this only records what it calls the thing.
    """
    cache = _load_xref_cache()
    if not refresh:
        hit = cache.get(label)
        if hit:                      # positive hits only; `null` is not an answer
            return hit

    resolved = _resolve_source_concept(label)
    if resolved is not None:
        cache[label] = resolved
        _save_xref_cache()
    else:
        # Drop any stale negative so the file cannot accumulate false absences.
        if cache.pop(label, "__absent__") != "__absent__":
            _save_xref_cache()
        _MISSES.add(label)
    return resolved


# Terms that failed to resolve in THIS process. Reported, never persisted.
_MISSES: set = set()


def unresolved_labels() -> list[str]:
    return sorted(_MISSES)


def purge_negative_xrefs() -> int:
    """Remove `null` entries left by the old cache-the-miss behaviour."""
    cache = _load_xref_cache()
    dead = [k for k, v in cache.items() if v is None]
    for k in dead:
        cache.pop(k)
    if dead:
        _save_xref_cache()
    return len(dead)


def purge_wiki_xrefs() -> int:
    """
    Drop cached wiki_page resolutions.

    They were produced while the concept probe used limit=10, so a wiki_page
    entry does not mean "no concept exists" — 铁器/瓷器/铜器/石刻/雕塑/铜/铁/金/石
    all have exactly-named concepts that the probe never saw. Re-resolve them.
    """
    cache = _load_xref_cache()
    dead = [k for k, v in cache.items()
            if isinstance(v, dict) and v.get("xref_kind") == "wiki_page"]
    for k in dead:
        cache.pop(k)
    if dead:
        _save_xref_cache()
    return len(dead)


def _resolve_source_concept(label: str) -> dict | None:
    """
    Uncached remote resolution. Only lookup_source_concept should call this.

    limit=200 (the server cap; higher returns HTTP 400) rather than 10:
    concept/search is a SUBSTRING search, so exactly-named concepts can rank far
    below unrelated partial matches. 铁器 has 27 of them and a limit=10 probe saw
    none, which silently declared nine terms concept-less.
    """
    result = sget("/ontology/concept/search", {"q": label, "limit": 200})
    if "error" in result:
        # An error is not an absence. Return None WITHOUT letting the caller
        # persist it, and say so on stderr so a bad run is visible.
        _log(f"  ! concept/search failed for {label!r}: {result['error']}")
        return None
    for c in result.get("concepts", []):
        if c.get("canonical_name", "").lower() == label.lower():
            return {**c, "xref_kind": "concept"}

    page_result = sget("/wiki/page", {"domain": SOURCE_DOMAIN, "slug": label})
    if "error" in page_result:
        _log(f"  ! wiki/page failed for {label!r}: {page_result['error']}")
        return None
    page = (page_result or {}).get("page")
    if page:
        return {
            "xref_kind": "wiki_page",
            "concept_id": page.get("page_id"),
            "canonical_name": page.get("title") or label,
            "slug": page.get("slug", label),
            "concept_type": "entity",
            "aliases": [],
        }
    return None


