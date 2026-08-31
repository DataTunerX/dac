#!/usr/bin/env python3
"""
wwybsj_l0.py — L0 builder: turn the museum registry into observed statements.

L0 is the reasoning substrate. It contains ONLY what the registry literally
states about an artifact, expressed as typed values. No LLM is involved, no
remote corpus is consulted, and nothing is inferred. Everything here is
`epistemic_mode=observed`.

What L0 deliberately does NOT do:
  - parse `ww_chicun` (尺寸). It is free text ('存14.8*832*3.4',
    '存长:(大)20.2 (小)9 高(大)8(小)5.8 底厚'), only 13/465 rows state a unit,
    and guessing a unit is how a 柱础护圈 ends up 2.1 metres tall. The literal
    is preserved and flagged instead; parsing is a separate reviewable pass.
  - align terms to the remote `archeology` corpus. That is L1 (anchor edges).
  - write wiki pages. Those are a projection of L0+L1, generated later.

NAMING RULES (learned the hard way — see the namespace-theft incident):
  Every id this domain creates is prefixed. Bare predicate names like `is_a`
  are GLOBAL singletons in semantic_entity: `entity_id` is the primary key and
  upsert does `ON CONFLICT ... namespace = EXCLUDED.namespace`, so writing a
  bare name silently relabels a predicate that other domains already use.

    artifact individual   wwybsj.artifact.<registry_no>
    predicate             wwybsj.predicate.<name>
    controlled term       wwybsj.term.<facet>.<registry value>
    qualifier property    wwybsj.qualifier.<key>
    reference property    wwybsj.ref.registry
    statement_key         wwybsj/L0/<registry_no>/<name>[/<discriminator>]

  Every statement also carries metadata_json.domain='wwybsj'. Domain scoping
  must never rely on the mutable `namespace` column alone.

Prerequisite: registry provenance events must exist.
    python3 wwybsj_ingest.py --all --execute

Usage:
    python3 wwybsj_l0.py --registry-no 8              # preview one record
    python3 wwybsj_l0.py --all                        # preview all (writes JSON)
    python3 wwybsj_l0.py --all --execute              # write to local TDB
    python3 wwybsj_l0.py --verify
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
    OUT_DIR, STREAM_ID, TARGET_DOMAIN,
    bianhao, call_summary, clean, get, load_records, post,
)

EXTRACTOR = "wwybsj_l0_v2"
PERIOD_MAP_PATH = Path(__file__).resolve().parent.parent / "period_normalization.json"
L0_OUT_DIR = OUT_DIR / "l0"
INGEST_INDEX = OUT_DIR / "ingest_index.json"

P = "wwybsj.predicate."          # predicate namespace
T = "wwybsj.term."               # controlled-term namespace
Q = "wwybsj.qualifier."          # qualifier namespace
REF_REGISTRY = "wwybsj.ref.registry"

# Registry facts are observed, not extracted: the registry IS the authority.
STATUS = "accepted"


# ---------------------------------------------------------------------------
# Ids
# ---------------------------------------------------------------------------

def artifact_id(bh: str) -> str:
    return f"wwybsj.artifact.{bh}"


def term_id(facet: str, value: str) -> str:
    return f"{T}{facet}.{value}"


def stmt_key(bh: str, name: str, disc: str = "") -> str:
    return f"wwybsj/L0/{bh}/{name}" + (f"/{disc}" if disc else "")


# ---------------------------------------------------------------------------
# Period normalization
# ---------------------------------------------------------------------------

def load_period_map() -> tuple[dict[str, str], set[str]]:
    """
    (label -> canonical, ambiguous labels) from period_normalization.json.

    The registry writes one polity several ways — 唐 / 唐代 / 晚唐 / 唐天宝年间,
    高句丽 / 高勾丽 (an OCR variant) — so aggregating by culture silently
    undercounts. Only labels that certainly denote the SAME polity are merged;
    西汉/东汉, 西周/东周, 北魏/东魏 keep their own terms because their year ranges
    genuinely differ. The merge affects only the anchorable `in_period` term:
    dated_to keeps registry_literal and the parsed interval untouched.
    """
    if not PERIOD_MAP_PATH.exists():
        return {}, set()
    payload = json.loads(PERIOD_MAP_PATH.read_text(encoding="utf-8"))
    rules = {r["from"]: r["to"] for r in payload.get("rules", [])}
    ambiguous = {a["label"] for a in payload.get("ambiguous_no_term", [])}
    return rules, ambiguous


_PERIOD_RULES, _PERIOD_AMBIGUOUS = load_period_map()


def canonical_period(era_label: str) -> tuple[str, str]:
    """(canonical term, status). status: canonical | merged | ambiguous | none."""
    label = (era_label or "").strip()
    if not label:
        return "", "none"
    if label in _PERIOD_AMBIGUOUS:
        return "", "ambiguous"
    merged = _PERIOD_RULES.get(label)
    return (merged, "merged") if merged else (label, "canonical")


# ---------------------------------------------------------------------------
# Typed value parsing
# ---------------------------------------------------------------------------

# 唐(618~907) · 战国时代(前475~前221) · 西汉(前206~公元25)
# 渤海（698年—926） · 渤海（公元698—926年） · 唐天宝年间(公元742-756)
_YEAR_RANGE = re.compile(
    r"[（(]\s*(?:公元)?\s*(前)?\s*(\d+)\s*年?\s*[~～—–\-—至]\s*"
    r"(?:公元)?\s*(前)?\s*(\d+)\s*年?\s*[)）]"
)


def parse_period(literal: str) -> dict[str, Any]:
    """
    Turn a registry era string into a comparable interval.

    Returns years only when the literal states them. A label with no years
    stays a label — inventing a range for '宋' or '北朝' would silently create
    a false interval that later interval reasoning would trust.
    """
    lit = clean(literal)
    m = _YEAR_RANGE.search(lit)
    label = re.split(r"[（(]", lit)[0].strip() or lit
    if not m:
        return {
            "era_label": label,
            "start_year": None,
            "end_year": None,
            "calendar": "CE",
            "parse_status": "label_only",
            "registry_literal": lit,
        }
    s_bce, s_year, e_bce, e_year = m.groups()
    start = -int(s_year) if s_bce else int(s_year)
    end = -int(e_year) if e_bce else int(e_year)
    return {
        "era_label": label,
        "start_year": start,
        "end_year": end,
        "calendar": "CE",
        "parse_status": "range_parsed",
        "registry_literal": lit,
    }


def period_source(rec: dict) -> tuple[str, str]:
    """(literal, registry_field) for the most specific era the record states."""
    jt = clean(rec.get("ww_niandai_jt"))
    if jt:
        return jt, "ww_niandai_jt"
    for k in ("ww_niandai_d", "ww_niandai_c", "ww_niandai_b"):
        v = clean(rec.get(k))
        if v:
            return v, k
    v = clean(rec.get("ww_niandai_a"))
    # ww_niandai_a holds the dating SCHEME ('中国历史学年代'), never a period.
    return ("", "") if v in {"", "其他", "中国历史学年代"} else (v, "ww_niandai_a")


_MASS_TO_G = {"g": 1.0, "kg": 1000.0}


def parse_mass(rec: dict) -> dict[str, Any] | None:
    raw = clean(rec.get("ww_zhiliang_jt"))
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    if value == 0:
        return None
    unit = clean(rec.get("ww_zhiliang_dw"))
    out: dict[str, Any] = {
        "value": value,
        "unit": unit or None,
        "unit_source": "registry_column" if unit else "missing",
        "registry_literal": raw,
    }
    # Normalizing is safe only because the unit is explicit in its own column.
    if unit in _MASS_TO_G:
        out["normalized_g"] = round(value * _MASS_TO_G[unit], 4)
    return out


_DIM_COLUMNS = (("ww_chang", "length", "长"),
                ("ww_kuan", "width", "宽"),
                ("ww_gao", "height", "高"))


def parse_dimensions(rec: dict) -> list[dict[str, Any]]:
    """
    Structured dimension columns only.

    The columns carry no unit anywhere in the schema or the DDL comments, so
    `unit` stays null and `unit_source` says so. A consumer that needs a unit
    must resolve it explicitly rather than assume centimetres.
    """
    out = []
    for column, dimension, label in _DIM_COLUMNS:
        raw = clean(rec.get(column))
        if not raw:
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        if value == 0:
            continue
        out.append({
            "dimension": dimension,
            "label_zh": label,
            "value": value,
            "unit": None,
            "unit_source": "unspecified",
            "registry_field": column,
            "registry_literal": raw,
        })
    return out


def parse_quantity(rec: dict) -> dict[str, Any] | None:
    raw = rec.get("ww_shuliang")
    try:
        count = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return {"count": count, "registry_literal": str(raw).strip()}


def split_materials(rec: dict) -> list[str]:
    """质地c is the specific material; '铜,金' means two materials, not one."""
    raw = clean(rec.get("ww_zhidi_c"))
    return [p.strip() for p in re.split(r"[,，、/]", raw) if p.strip()]


# ---------------------------------------------------------------------------
# Statement plan for one record
# ---------------------------------------------------------------------------

# name -> (facet, registry field). Single-valued controlled vocabulary.
_TERM_FACETS = (
    ("instantiates",      "category",     "ww_leibie"),
    ("has_grade",         "grade",        "ww_jibie"),
    ("acquired_by",       "acquisition",  "ww_laiyuan"),
    ("has_completeness",  "completeness", "ww_wancan_cd"),
)

# name -> registry field. Verbatim strings, no interpretation.
_LITERAL_FIELDS = (
    ("has_registry_no",        "ww_bianhao"),
    ("has_registry_scheme",    "ww_bh_leixing"),
    ("has_name",               "ww_mingchen"),
    ("has_original_name",      "ww_yuanming"),
    ("has_material_form",      "ww_zhidi_a"),
    ("has_material_class",     "ww_zhidi_b"),
    ("has_mass_range",         "ww_zhiliang_fw"),
    ("has_completeness_note",  "ww_wancan_zk"),
    ("has_conservation_state", "ww_baocun_zt"),
    ("has_period_scheme",      "ww_niandai_a"),
    ("registered_at",          "ww_ctime"),
)


def plan_record(rec: dict, anchor: dict) -> dict[str, Any]:
    """Build the full entity/statement/qualifier/reference plan for one record."""
    bh = bianhao(rec)
    subj = artifact_id(bh)

    entities: dict[str, dict] = {}
    statements: list[dict] = []
    qualifiers: list[dict] = []
    references: list[dict] = []

    def add_entity(entity_id: str, kind: str, role: str,
                   datatype: str | None = None, meta: dict | None = None) -> None:
        if entity_id in entities:
            return
        e = {
            "entity_id": entity_id,
            "entity_kind": kind,
            "semantic_role": role,
            "namespace": TARGET_DOMAIN,
            "status": "active",
            "metadata_json": {"domain": TARGET_DOMAIN, **(meta or {})},
        }
        if datatype:
            e["property_datatype"] = datatype
        entities[entity_id] = e

    add_entity(subj, "item", "individual", meta={
        "label": clean(rec.get("ww_mingchen")),
        "registry_no": bh,
        "record_id": rec["id"],
    })
    add_entity(REF_REGISTRY, "property", "annotation_property", "json",
               meta={"label": "登记记录出处"})

    def emit(name: str, *, value_type: str, value_json: Any = None,
             object_id: str | None = None, registry_field: str,
             disc: str = "", confidence: float = 1.0,
             extra_qualifiers: dict | None = None) -> None:
        key = stmt_key(bh, name, disc)
        prop = f"{P}{name}"
        # semantic_role is CHECK-constrained; the literal-valued role is spelled
        # 'datatype_property' (not 'data_property' — that fails as a bare HTTP 500).
        add_entity(prop, "property", "object_property" if object_id else "datatype_property",
                   "entity" if object_id else value_type, meta={"label": name})

        stmt: dict[str, Any] = {
            "statement_key": key,
            "subject_id": subj,
            "property_id": prop,
            "value_type": "entity" if object_id else value_type,
            "value_json": {} if object_id else (value_json or {}),
            "status": STATUS,
            "confidence": confidence,
            "created_by": EXTRACTOR,
            "metadata_json": {
                "domain": TARGET_DOMAIN,
                "layer": "L0",
                "statement_key": key,
                "record_id": rec["id"],
                "registry_no": bh,
                "registry_field": registry_field,
                "subject_label": clean(rec.get("ww_mingchen")),
            },
        }
        if object_id:
            # value_entity_id must be absent for non-entity statements: the
            # table has CHECK (value_type='entity') = (value_entity_id IS NOT NULL).
            stmt["value_entity_id"] = object_id
            stmt["metadata_json"]["object_label"] = object_id.rsplit(".", 1)[-1]
        statements.append(stmt)

        quals = {
            "epistemic_mode": "observed",
            "basis": "registry",
            "registry_field": registry_field,
            **(extra_qualifiers or {}),
        }
        for ordinal, (qkey, qval) in enumerate(quals.items()):
            qprop = f"{Q}{qkey}"
            is_text = isinstance(qval, str)
            add_entity(qprop, "property", "annotation_property",
                       "string" if is_text else "json", meta={"label": qkey})
            qualifiers.append({
                "statement_key": key,
                "property_id": qprop,
                "value_type": "string" if is_text else "json",
                "value_json": {"text": qval} if is_text else qval,
                "ordinal": ordinal,
            })

        references.append({
            "statement_key": key,
            "property_id": REF_REGISTRY,
            "value_type": "json",
            "value_json": {
                "gateway": "local",
                "domain": TARGET_DOMAIN,
                "stream_id": anchor["stream_id"],
                "event_id": anchor["event_id"],
                "registry_field": registry_field,
            },
            "source_span": f"{registry_field}={clean(rec.get(registry_field)) or '∅'}",
            "ordinal": 0,
        })

    # --- verbatim literals -------------------------------------------------
    for name, field in _LITERAL_FIELDS:
        v = clean(rec.get(field))
        if not v:
            continue
        if field == "ww_niandai_a" and v in {"其他", "中国历史学年代"}:
            # a scheme label is worth keeping, but it is not a period
            pass
        emit(name, value_type="string", value_json={"text": v}, registry_field=field)

    # --- controlled terms --------------------------------------------------
    for name, facet, field in _TERM_FACETS:
        v = clean(rec.get(field))
        if not v:
            continue
        tid = term_id(facet, v)
        add_entity(tid, "item", "concept", meta={
            "label": v, "facet": facet, "registry_field": field,
            # L1 will resolve these against the remote archeology corpus.
            "alignment": "unaligned",
        })
        emit(name, value_type="entity", object_id=tid, registry_field=field)

    for material in split_materials(rec):
        tid = term_id("material", material)
        add_entity(tid, "item", "concept", meta={
            "label": material, "facet": "material",
            "registry_field": "ww_zhidi_c", "alignment": "unaligned",
        })
        emit("made_of", value_type="entity", object_id=tid,
             registry_field="ww_zhidi_c", disc=material)

    # --- typed values ------------------------------------------------------
    literal, field = period_source(rec)
    period = parse_period(literal) if literal else None
    if period:
        emit("dated_to", value_type="json", value_json=period, registry_field=field,
             extra_qualifiers={"parse_status": period["parse_status"]})

        # A referenceable period TERM, so L1 can anchor it to the remote corpus
        # and an exhibit label can dereference the polity's own background.
        # dated_to alone cannot carry an anchor: it is a JSON value, not an entity.
        canon, status = canonical_period(period["era_label"])
        if canon:
            tid = term_id("period", canon)
            add_entity(tid, "item", "concept", meta={
                "label": canon, "facet": "period", "registry_field": field,
                "alignment": "unaligned",
            })
            emit("in_period", value_type="entity", object_id=tid, registry_field=field,
                 extra_qualifiers={"label_normalization": status,
                                   "registry_era_label": period["era_label"]})

    mass = parse_mass(rec)
    if mass:
        emit("has_mass", value_type="json", value_json=mass,
             registry_field="ww_zhiliang_jt",
             extra_qualifiers={"unit_source": mass["unit_source"]})

    for dim in parse_dimensions(rec):
        emit("has_dimension", value_type="json", value_json=dim,
             registry_field=dim["registry_field"], disc=dim["dimension"],
             extra_qualifiers={"unit_source": "unspecified"})

    quantity = parse_quantity(rec)
    if quantity:
        emit("has_quantity", value_type="json", value_json=quantity,
             registry_field="ww_shuliang")

    chicun = clean(rec.get("ww_chicun"))
    if chicun:
        emit("has_dimension_note", value_type="string", value_json={"text": chicun},
             registry_field="ww_chicun",
             extra_qualifiers={"parse_status": "unparsed_free_text"})

    # --- data-quality flags ------------------------------------------------
    # Flags are first-class statements, not log lines: a consumer that asks
    # "which artifacts can I reason about dimensionally" needs them queryable.
    flags: list[tuple[str, str]] = []
    if chicun and not parse_dimensions(rec):
        flags.append(("dimension_only_in_free_text",
                      "尺寸仅存在于自由文本 ww_chicun，结构化列全为 0，无法用于数值推理"))
    if parse_dimensions(rec):
        flags.append(("dimension_unit_unspecified",
                      "长/宽/高 列没有单位来源，跨藏品数值比较前必须显式确定单位"))
    if period and period["parse_status"] == "label_only":
        flags.append(("period_label_without_years",
                      f"年代仅有标签 {period['era_label']!r}，无年份区间，无法参与区间推理"))
    if mass and mass["unit_source"] == "missing":
        flags.append(("mass_unit_missing", "有质量数值但 ww_zhiliang_dw 为空"))
    if period and canonical_period(period["era_label"])[1] == "ambiguous":
        flags.append(("period_label_spans_multiple_polities",
                      f"年代标签 {period['era_label']!r} 跨多个政权，无法归入单一"
                      f"政权词项，不建 in_period 锚点；需策展人裁定"))

    for code, note in flags:
        emit("has_data_quality_flag", value_type="json",
             value_json={"code": code, "note": note},
             registry_field="(derived)", disc=code, confidence=1.0,
             extra_qualifiers={"epistemic_mode": "observed",
                               "basis": "registry_completeness_check"})

    return {
        "registry_no": bh,
        "record_id": rec["id"],
        "entities": list(entities.values()),
        "statements": statements,
        "qualifiers": qualifiers,
        "references": references,
        "flags": [code for code, _ in flags],
    }


# ---------------------------------------------------------------------------
# Provenance anchors
# ---------------------------------------------------------------------------

def load_anchors() -> dict[str, dict]:
    if not INGEST_INDEX.exists():
        raise SystemExit(
            f"{INGEST_INDEX} not found. L0 statements must cite a registry event.\n"
            f"Run first:  python3 {Path(__file__).parent / 'wwybsj_ingest.py'} --all --execute"
        )
    with open(INGEST_INDEX, encoding="utf-8") as f:
        idx = json.load(f)
    return {
        str(rec_id): {"stream_id": entry.get("stream_id", STREAM_ID),
                      "event_id": entry["event_id"]}
        for rec_id, entry in idx.get("events", {}).items()
        if entry.get("event_id")
    }


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def write_plans(plans: list[dict], batch_size: int) -> int:
    """Upsert plans through the semantic batch API. Returns error count."""
    errors = 0
    for start in range(0, len(plans), batch_size):
        chunk = plans[start:start + batch_size]
        batch = {"entities": [], "statements": [], "qualifiers": [], "references": []}
        seen_entities: set[str] = set()
        for plan in chunk:
            for e in plan["entities"]:
                if e["entity_id"] not in seen_entities:
                    seen_entities.add(e["entity_id"])
                    batch["entities"].append(e)
            batch["statements"].extend(plan["statements"])
            batch["qualifiers"].extend(plan["qualifiers"])
            batch["references"].extend(plan["references"])

        span = f"{chunk[0]['registry_no']}..{chunk[-1]['registry_no']}"
        result = post("/ontology/semantic/upsert-batch", batch)
        if "error" in result:
            print(f"  ✗ [{span}] {result['error']}", file=sys.stderr)
            errors += 1
            continue
        print(f"  ✓ [{span}] {len(batch['statements'])} statements, "
              f"{len(batch['entities'])} entities")
    return errors


def verify() -> None:
    listing = get("/ontology/statement/list",
                  {"subject_id": artifact_id("0004"), "limit": 100})
    if "error" in listing:
        print(f"verify failed: {listing['error']}")
        return
    rows = listing.get("statements", [])
    print(f"registry 0004: {len(rows)} statements")
    for entry in rows[:40]:
        st = entry.get("statement") or {}
        value = st.get("object_concept_id") or json.dumps(
            st.get("value_json") or {}, ensure_ascii=False)
        print(f"  {st.get('predicate', '?').replace(P, ''):24s} {value[:90]}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sel = p.add_mutually_exclusive_group(required=True)
    sel.add_argument("--registry-no", help="One artifact by ww_bianhao, e.g. 8 or 0008")
    sel.add_argument("--all", action="store_true")
    sel.add_argument("--verify", action="store_true", help="Read back one artifact")
    p.add_argument("--execute", action="store_true", help="Write (default: preview only)")
    p.add_argument("--batch-size", type=int, default=25)
    p.add_argument("--out-dir", default=str(L0_OUT_DIR))
    args = p.parse_args()

    if args.verify:
        verify()
        return 0

    records = load_records()
    if args.registry_no:
        want = re.sub(r"\D", "", args.registry_no).zfill(4)
        records = [r for r in records if bianhao(r) == want]
        if not records:
            raise SystemExit(f"registry_no={args.registry_no!r} not found")

    anchors = load_anchors()
    missing = [r["id"] for r in records if str(r["id"]) not in anchors]
    if missing:
        raise SystemExit(
            f"{len(missing)} record(s) have no registry provenance event "
            f"(first: id={missing[0]}). Run wwybsj_ingest.py --all --execute."
        )

    plans = [plan_record(r, anchors[str(r["id"])]) for r in records]

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    plan_path = out_dir / ("l0_plan.json" if args.all
                           else f"l0_plan_{plans[0]['registry_no']}.json")
    plan_path.write_text(json.dumps(plans, ensure_ascii=False, indent=2),
                         encoding="utf-8")

    n_stmt = sum(len(p["statements"]) for p in plans)
    n_ent = len({e["entity_id"] for p in plans for e in p["entities"]})
    flag_counts: dict[str, int] = {}
    for plan in plans:
        for code in plan["flags"]:
            flag_counts[code] = flag_counts.get(code, 0) + 1

    print(f"records     : {len(plans)}")
    print(f"statements  : {n_stmt}  (avg {n_stmt / max(len(plans), 1):.1f} per artifact)")
    print(f"entities    : {n_ent}")
    print(f"plan        : {plan_path}")
    if flag_counts:
        print("data-quality flags:")
        for code, count in sorted(flag_counts.items(), key=lambda kv: -kv[1]):
            print(f"  {count:4d}  {code}")

    if not args.execute:
        print("\nPREVIEW ONLY — pass --execute to write to the local TDB.")
        return 0

    print(f"\nwriting to {TARGET_DOMAIN} ...")
    errors = write_plans(plans, args.batch_size)
    print(call_summary())
    if errors:
        print(f"\n{errors} batch(es) failed", file=sys.stderr)
        return 1
    print("\ndone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
