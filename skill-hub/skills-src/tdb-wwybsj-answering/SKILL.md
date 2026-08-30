---
name: tdb-wwybsj-answering
description: Use when answering questions about the wwybsj museum collection with TDB, especially when combining local collection facts, wwybsj_business_terms field/term ontology, and remote TDB lab context. Use for item and collection research, normalization audits, cross-cultural comparison, lineage, typology, chronology, archaeological or museum interpretation, reports, and analytics. Always report evidence boundaries.
---

# TDB WWYBSJ Answering

## Overview

This skill answers questions about the `wwybsj` museum collection by combining local collection evidence with remote TDB lab context:

- local `wwybsj`: what this collection item is, what the registry says, what local wiki / statements already exist
- local `wwybsj_business_terms`: how museum-facing phrases, registry fields,
  and normalization audit terms map to business meaning before retrieval
- local full registry file: `wwybsj.json` in this skill directory, a full offline copy of the collection registry
- remote TDB lab domains: what broader archaeology, history, art history,
  anthropology/sociology, theory, environmental, or humanities literature says
  about comparable artifacts, terminology, cultural background, source text, and
  interpretation

Core rule:

- treat `wwybsj` as the primary domain for collection truth
- treat `archeology` as the secondary domain for interpretation and context
- use additional remote lab domains only when they fit the question's evidence need
- do not silently merge the two into one layer of certainty
- a local registry fact is stronger than a remote comparison
- business ontology can interpret a field or query phrase, but it is not item
  evidence by itself
- a remote comparison may explain a collection item, but must not be restated as if it were a direct fact about that item unless the evidence really says so

## Gateway Configuration

Use local and remote gateways with different evidence roles:

- local collection gateway: `http://10.124.48.91:8997`
  - authoritative for `domain=wwybsj`
  - use for local wiki pages, collection registry projections, local semantic statements, and item-level facts
  - use `wwybsj_business_terms` in the local term-mapping registry for
    museum-facing terms, field aliases, lookup phrases, and normalization
    audit policy
  - local collection items should be searched in local wiki first, especially with `GET /v2/wiki/search?domain=wwybsj&q=...`
- local full registry file: `wwybsj.json`
  - located beside this `SKILL.md`
  - contains the full `wwybsj` registry snapshot; use it for offline full-scan checks, registry-number disambiguation, and field-level fallback when the local gateway is unavailable or incomplete
  - key fields include `ww_bianhao`, `ww_mingchen`, `ww_niandai_jt`, `ww_leibie`, `ww_zhidi_c`, `ww_chicun`, `ww_zhiliang_jt`, `ww_zhiliang_dw`, `ww_jibie`, `ww_laiyuan`, `ww_wancan_cd`, `ww_wancan_zk`, and `ww_baocun_zt`
- remote archaeology gateway: `http://10.124.48.91:8989`
  - authoritative for `domain=archeology`
  - use for broader archaeological background, comparanda, terminology, source passages, and interpretation
- remote TDB lab auxiliary gateways:
  - `history`: `http://10.124.48.91:8990`
  - `art_history`: `http://10.124.48.91:8991`
  - `anthropology_sociology`: `http://10.124.48.91:8992`
  - `philosophy_theory`: `http://10.124.48.91:8993`
  - `geo_environment`: `http://10.124.48.91:8994`
  - `literature_humanities`: `http://10.124.48.91:8995`
  - use only as supporting context for chronology, style, iconography,
    religion, society, environment, theory, or transmitted-text comparison

Do not query `domain=wwybsj` on any remote lab gateway and treat an empty result as evidence that the local collection lacks the item. If the question is about a `wwybsj` collection object, start at `10.124.48.91:8997`.

### The collection gateway starts empty (critical)

`10.124.48.91:8997` is an isolated TDB that was re-initialized with the current
schema and **its knowledge tables start empty**. Content arrives only as DAC
Data Management → **TDB 入库** (`/tdb-pipeline`) runs ingest into target
`wwybsj`, which writes to this same gateway.

This changes what an empty result means, and getting it wrong produces confidently
wrong answers:

> An item missing from the local wiki or statements means **not yet ingested**,
> **not** absent from the collection. Collection membership is decided by
> `wwybsj.json`, the full registry snapshot beside this `SKILL.md` — which stays
> valid regardless of what the gateway holds.

So while the gateway is sparse:

- check `wwybsj.json` before saying an item is not in the collection
- say plainly that local wiki/statement evidence is absent and that the answer
  rests on the registry snapshot
- do not fall back to a remote lab gateway for `domain=wwybsj` to fill the gap —
  those are different databases and would answer about different material
- a registry-only answer is a legitimate answer; label it as registry-only

Check current scope live rather than assuming: `GET /v2/wiki/pages?domain=wwybsj&limit=1`
tells you whether anything has been ingested yet.

Before a broad interpretive or debugging answer, check health for the intended
remote gateway when practical: `GET /v2/health` or `GET /health`. If a remote
gateway is unreachable, report that auxiliary domain as unavailable instead of
silently substituting another gateway.

For wiki pages with Chinese slugs, URL-encode query parameters instead of placing raw Chinese text directly in the URL. Example:

```bash
curl -sG 'http://10.124.48.91:8997/v2/wiki/page' \
  --data-urlencode 'domain=wwybsj' \
  --data-urlencode 'slug=ww-0139-唐代海兽葡萄纹铜镜'
```

Default persona:

- answer like a careful museum researcher
- distinguish `登记事实`, `研究解释`, and `无法确证的部分`
- when evidence is mixed, keep the answer useful without overstating certainty
- show the evidence trail explicitly enough that a curator can audit the answer

## When to Use

Use this when:

- the user asks about one or more `wwybsj` collection items
- the user asks a collection-level question that may need both local holdings and remote archaeological context
- the user asks for cross-cultural similarity / difference, lineage, typology, chronology, association, or broader social interpretation
- the user asks for excavation-style reports, research summaries, exhibition planning evidence, or museum data analysis connected to the collection
- the user wants an explanation grounded in TDB rather than a freeform guess
- you need to debug why `wwybsj` alone answers too little, or why `archeology` alone answers too generally

Do not use this for batch building or writeback workflows. Use `wwybsj_build` for that.

## Task Routing

First classify the request before retrieval. Use the core retrieval workflow for all
routes, then read `references/task-protocols.md` when the request matches one of
these advanced routes:

- `cultural-comparison`: different cultures, regions, periods, or collections are
  being compared for similarity, difference, influence, exchange, or shared traits
- `lineage`: the user asks about genealogy, pedigree, source, succession,
  typological evolution, technical tradition, or transmission path
- `association-chronology-social`: the user asks about relatedness, chronology, or
  archaeological interpretation of lifestyle, religion, warfare, settlement,
  tribe, chiefdom, polity, or state formation
- `automated-report`: the user asks for an excavation report, research report,
  collection report, exhibition dossier, or other structured museum deliverable
- `museum-analytics`: the user asks to analyze audience, exhibition, education,
  media, research, or operational data alongside the collection

If more than one route applies, name the routes and keep the answer modular. For
example, a report about cultural exchange in a burial context may use
`cultural-comparison`, `association-chronology-social`, and `automated-report`.

Route rules:

- Do not let remote background become a local item fact.
- Do not infer culture, lineage, excavation context, or social organization from
  an item name alone.
- Use local `wwybsj` evidence to define the collection slice before making a
  collection-level claim.
- Use remote `archeology` evidence to explain categories, comparanda,
  archaeological context, and interpretation.
- Use remote auxiliary domains only for their natural support role: `history`
  for chronology/political setting, `art_history` for style/iconography/craft,
  `anthropology_sociology` for social/ritual interpretation,
  `philosophy_theory` for method/theory, `geo_environment` for landscape and
  environmental context, and `literature_humanities` for transmitted-text or
  humanities comparison.
- Keep historical period background separate from local registry dating. A
  dynasty or polity's general date range may frame the culture, but it is not a
  precise date for every collection item unless the local record gives that
  range.
- For museum analytics, distinguish collection knowledge from imported visitor,
  exhibition, education, media, or research datasets. If the operational dataset
  is absent, say what cannot be analyzed yet and propose the required fields.

## Domain Split

Always keep local collection truth separate from remote context in your head:

- `wwybsj`
  - local gateway: `http://10.124.48.91:8997`
  - full local registry file: `wwybsj.json` beside this skill
  - collection registry facts
  - business ontology: `term_mapping_registry.registry_name=wwybsj_business_terms`
    / `version_label=v1`, with rules in `term_mapping_rule`
  - local museum-facing wiki pages
  - local semantic statements and qualifiers
- `archeology`
  - remote gateway: `http://10.124.48.91:8989`
  - textbook / archaeology source context
  - comparison artifacts, terminology, cultural background
  - source-text evidence for interpretation
- remote auxiliary lab domains
  - `history`: `http://10.124.48.91:8990`, for chronology, dynasty/polity
    background, and historical sequence
  - `art_history`: `http://10.124.48.91:8991`, for style, iconography, craft
    tradition, object-form comparison, and museum art-historical framing
  - `anthropology_sociology`: `http://10.124.48.91:8992`, for social
    organization, ritual practice, settlement, kinship, and ethnographic analogy
  - `philosophy_theory`: `http://10.124.48.91:8993`, for interpretive theory,
    methodology, and concept-history framing
  - `geo_environment`: `http://10.124.48.91:8994`, for landscape, climate,
    resources, site formation, and environmental context
  - `literature_humanities`: `http://10.124.48.91:8995`, for transmitted texts,
    narrative motifs, and broader humanities comparison

If the answer depends on a claim like `出土地`, `用途`, `器形归类`, `文化归属`, `同类器`, `艺术风格`, `宗教意义`, or `环境背景`, say which domain supports it.
Cross-domain evidence is supporting evidence unless it directly names the local
collection item or collection slice. Do not let an auxiliary-domain source
override local `wwybsj` registry facts.

## System 1 Answer Memory

Use TDB System 1 answer artifacts before the full retrieval workflow whenever
the question can be fingerprinted. System 1 is a fast path over previously
grounded answers, not a new evidence source.

Read `references/system1-answer-memory.md` before using, recording, or importing
System 1 artifacts. It defines the `question_fingerprint`, entity ids, recall
rules, validation rules, existing Q&A ingest rules, and
record-after-System-2 contract.

## Retrieval Workflow

Mandatory execution rule:

1. List the concepts you plan to check.
2. Try System 1 answer artifact recall when the question can be fingerprinted.
3. If System 1 safely serves the answer, still include the compact evidence
   boundary.
4. If System 1 misses, is stale, lacks provenance, or needs deeper reasoning,
   run System 2: resolve business terms through local `wwybsj_business_terms`
   before item retrieval when the question mentions field names, lookup
   phrases, counting/statistical fields, `period.raw_value`, `dynasty`, or
   normalization inconsistency.
5. Query local `wwybsj` item/wiki/statement evidence first.
6. Check the local full registry file when a full scan, disambiguation, or gateway fallback is needed.
7. Query remote `archeology` second. Add remote auxiliary lab domains only when
   the question needs their evidence. For interpretive, comparative,
   typological, functional, cultural-background, religious, artistic,
   environmental, or lineage claims, use the remote evidence ladder: wiki,
   ontology/statements/provenance, then chunks/source search. Do not stop after
   one layer unless the user explicitly asks for a quick answer or the gateway
   layer is unavailable.
8. Pull provenance / evidence for any structured claim you want to rely on.
9. Actively look for counter-evidence when the answer would make a strong
   causal, origin, exclusivity, typological-lineage, or status claim.
10. Use search hits to expand thin answers.
11. Compose the answer.
12. Record a System 1 answer artifact after successful, reusable System 2 answers.
13. Use inline numeric citations and a final `References` section in every
    user-facing answer unless the user explicitly asks for answer-only prose.
14. Include an evidence report unless the user explicitly asks for answer-only prose.

The evidence report is part of the answer process, not optional debugging output.

## Citation Discipline

Use scientific-literature style numeric citations in every user-facing answer.
This citation requirement applies alongside the local/remote evidence boundary:
local `wwybsj` registry/wiki evidence and remote TDB lab context should each get
their own citation numbers when they support different claims.

- Attach citations inline as `[1]`, `[2]`, etc. immediately after the sentence
  or clause they support. Do not use vague source phrases such as `TDB says`,
  `远端材料显示`, or `本馆登记显示` as a substitute for citations.
- Reuse the same citation number for repeated use of the same evidence object.
  Assign a new number only when the supporting source/evidence changes.
- Prefer citations backed by local registry rows, local wiki pages,
  statement/provenance, or source-text chunks. For structured claims, cite the
  reader-friendly source note and keep only the useful trace IDs in reserve:
  usually registry number / page slug / stream_id plus one of statement_id,
  event_id, evidence_id, or page_id when returned.
- End the answer with a `References` section listing each numeric citation as a
  short prose source note, not a raw metadata ledger. Include what the evidence
  supports and the minimum IDs needed to re-find it.
- If a claim is a synthesis across multiple cited pieces of evidence, cite all
  relevant numbers in the sentence, e.g. `[1][3]`.
- Do not invent hashes, statement IDs, evidence IDs, page IDs, or source
  metadata. If an endpoint returns useful text but no stable ID, write
  `id not returned` in the source note.
- The evidence report may reuse the same citation numbers. Do not make a
  separate uncited evidence report unless the user explicitly requests a debug
  ledger without citations.

### Step 1: Start from the question text

Extract likely anchors:

- item names
- registry numbers
- dynasty / period
- material
- artifact type
- place names
- question words implying cause, comparison, function, or traits

### Step 1a: Resolve business terms before querying

Normalize user-facing collection phrases into explicit lookup intent before item
retrieval. Prefer the local business ontology over hard-coded assumptions:

- Check the active mapping registry:
  `GET /v2/ontology/term-mapping/registry/list?domain=wwybsj&status=active&limit=20`
  and prefer `registry_name=wwybsj_business_terms`, `version_label=v1`.
- Search or interpret relevant terms with:
  `GET /v2/ontology/term-mapping/rule/search?registry_id=<id>&q=<term>&limit=20`
  or
  `GET /v2/ontology/term-mapping/interpret?domain=wwybsj&registry_name=wwybsj_business_terms&version_label=v1&raw_term=<term>&language=zh&context_hint=<hint>`.
- For field meaning, also use:
  `GET /v2/ontology/concept/search?domain=wwybsj&q=<field label>&limit=10`
  and
  `GET /v2/ontology/statement/list?subject_id=wwybsj.field.<json_field>&limit=50`.
- Treat term-mapping rules as interpretation policy. Use registry rows,
  wiki/evidence pages, statements, or `wwybsj.json` to establish item facts.
- If the business ontology is unavailable, empty, or obviously stale, say so
  and fall back to the built-in rules below.

Built-in fallback rules:

- Treat `展品`, `藏品`, `文物`, `馆藏`, and `藏件` as user-facing artifact entity
  terms in the `wwybsj` collection unless context clearly says otherwise.
- Resolve phrases matching `X号展品`, `X号藏品`, `X号文物`, `X号馆藏`, `X号藏件`,
  `第X号展品`, or `#X` as:
  - entity type: local `wwybsj` collection artifact
  - lookup field label: `藏品总登记号`
  - lookup field: `ww_bianhao`
  - lookup value: normalized digits from `X` without leading zeros
- When querying or reporting, make the normalized lookup explicit, e.g.
  `3号展品` -> `ww_bianhao=3` / `藏品总登记号 0003`.
- Use internal JSON/database `id` only when the user explicitly says
  `record_id`, `内部id`, `JSON id`, `数据库id`, or `记录ID`.
- If a number phrase is ambiguous because the user explicitly mentions both
  registry number and internal id, ask or report both candidate interpretations
  rather than silently choosing one.

For schema, analytics, or normalization-audit questions, use business ontology
field rules before choosing JSON fields:

- `藏品总登记号` / `登记号` / `编号` -> `ww_bianhao`
- `文物名称` / `名称` -> `ww_mingchen`
- `文物类别` / `类别` -> `ww_leibie`
- `具体质地` / `质地` / `材质` -> `ww_zhidi_c`
- `数量` / `件数` -> `ww_shuliang`
- `保存状态` -> `ww_baocun_zt`
- `具体年代` / `年代栏` / `具体政权` -> `ww_niandai_jt`
- `年代框架一级` / `断代框架` -> `ww_niandai_b`
- `period.raw_value` -> compose `ww_niandai_a`, `ww_niandai_b`,
  `ww_niandai_c`, `ww_niandai_d`, and `ww_niandai_jt`, preserving empty
  levels and registry literals
- `dynasty` normalization policy -> when `dynasty` means the specific level,
  prefer parsing `ww_niandai_jt`; keep `ww_niandai_b/c/d` as framework levels

### Step 2: Query local `wwybsj` first

Try in parallel when possible:

- `GET http://10.124.48.91:8997/v2/wiki/search?domain=wwybsj&q=...`
- `GET http://10.124.48.91:8997/v2/wiki/pages?domain=wwybsj&limit=...` when checking whether the local wiki exists or browsing local pages
- `GET http://10.124.48.91:8997/v2/wiki/page?domain=wwybsj&slug=...` when the slug is known
- `GET http://10.124.48.91:8997/v2/wiki/page/evidence?domain=wwybsj&slug=...` for page-level evidence
- `GET http://10.124.48.91:8997/v2/ontology/concept/search?domain=wwybsj&q=...`
- `GET http://10.124.48.91:8997/v2/ontology/statement/list?...` when you already have a subject concept
- `GET http://10.124.48.91:8997/v2/ontology/term-mapping/rule/search?...` for
  `wwybsj_business_terms` field aliases, lookup phrase rules, and normalization
  policies
- `GET http://10.124.48.91:8997/v2/ontology/term-mapping/interpret?...` for exact
  business-term interpretation; if concrete phrase patterns do not resolve,
  search for the stored pattern rule and apply its `split_rule` yourself
- `POST http://10.124.48.91:8997/v2/search/query` with `domain=wwybsj` only after wiki and structured local routes are checked
- `wwybsj.json` local file scan when you need the complete registry list, need to disambiguate duplicate names, or the gateway/wiki result is surprising

Use local `wwybsj` to answer:

- what items exist in the collection
- their names, dates, materials, classes, dimensions, source, condition, grade
- what local report pages already concluded

Treat `wwybsj.json` as local registry evidence, not as an interpretive source. It can establish fields recorded in the registry, but not broader archaeological meaning.

Treat `wwybsj_business_terms` as local business-ontology evidence for field
meaning, aliases, and normalization policy, not as a replacement for registry
facts. When it changes how a question is interpreted, mention the applied rule
briefly in the evidence report.

If local `wwybsj` is thin, record that explicitly. Do not pretend the local domain answered more than it did.

### Step 3: Query remote TDB lab context second

Use remote `archeology` for:

- terminology normalization
- comparable artifacts
- cultural and historical background
- source text explaining likely function, form, or context

Use remote auxiliary lab domains only when the local collection question needs
their discipline-specific evidence:

- `history`: dynasty, polity, chronology, political geography, historical
  sequence, diplomatic or trade background
- `art_history`: style, iconography, craft tradition, visual comparison,
  museum-facing art interpretation
- `anthropology_sociology`: social organization, ritual practice, settlement,
  kinship, warfare, tribe/chiefdom/polity/state-formation interpretation
- `philosophy_theory`: theory of interpretation, method, category critique,
  concept history
- `geo_environment`: landscape, climate, resources, environmental archaeology,
  site formation, paleoecology
- `literature_humanities`: transmitted texts, narrative motifs, philology, or
  broader humanities comparison

Use the remote evidence ladder. The ladder is mandatory for interpretive,
comparative, typological, functional, cultural-background, or lineage claims.
Each layer should contribute to reasoning or be reported as empty/unavailable:

1. Wiki layer:
   - `GET http://10.124.48.91:8989/v2/wiki/search?domain=archeology&q=...`
   - for auxiliary domains, use the matching gateway and domain name from the
     lab routing table
   - use for broad topic discovery, candidate page titles, terminology, related
     cultures/sites, and concise background
   - when a page looks relevant, fetch the page and page evidence if available
2. Ontology layer:
   - `GET http://10.124.48.91:8989/v2/ontology/concept/search?domain=archeology&q=...`
   - `GET http://10.124.48.91:8989/v2/ontology/statement/list?...`
   - for auxiliary domains, query the same ontology routes on that domain's
     gateway, with that domain's `domain=<name>`
   - use for explicit relations such as class membership, material, date,
     related site/culture, function, typological association, or named comparanda
   - retrieve `statement/provenance` for statements that become answer pillars
3. Chunk / source-text layer:
   - `POST http://10.124.48.91:8989/v2/search/query` with `domain=archeology`
   - for auxiliary domains, call `/v2/search/query` on the matching gateway with
     `domain=<name>`
   - use for source passages that explain form, function, context, chronology,
     distribution, or scholarly wording
   - prefer chunks that name the artifact class, culture/site/period, and the
     interpretive axis in the same passage

Remote scope guard:

- After every remote `search/query`, inspect `resolved_stream_ids`.
- `resolved_stream_ids: []` with non-empty hits means the search probably ran
  unscoped because the domain is wrong or unbound. Do not use those hits as
  evidence; check `GET /v2/search/domain-stream/list?domain=<domain>` and
  report the binding problem.
- `resolved_stream_ids: [...]` with zero hits means the domain scope is valid
  but the query missed; retry with shorter anchors, proper nouns, split artifact
  terms, or `mode: "lexical"`.
- If a domain gateway is unreachable, mark that auxiliary layer unavailable and
  continue with the available domains, preserving the evidence boundary.

The layers should talk to each other:

- Start with item names, artifact class, material, motif, period, and place
  anchors from local `wwybsj`.
- Use wiki hits to harvest better ontology terms.
- Use ontology concepts/statements to harvest source-search terms.
- Use chunks to find specific phrases, site names, disciplinary terms, or
  typological variants, then retry wiki/ontology when the first ontology pass
  was thin.
- Use remote auxiliary-domain hits as expansion anchors back into `archeology`
  or local `wwybsj` only when the source text actually names a relevant artifact
  class, culture, motif, place, period, or interpretive relation.
- Search synonyms and adjacent terms when literal local names fail, e.g. split
  `绿釉莲纹柱础护圈` into `绿釉`, `莲纹`, `柱础`, `建筑构件`, and relevant culture
  or period terms.

Remote layer use:

- Wiki alone can support background orientation, not a strong interpretation.
- Ontology without provenance can suggest a reasoning path, but answer wording
  must be downgraded until provenance or chunk support is recovered.
- Chunk/source text can support explanation, but do not treat a single passage as
  direct local item evidence.
- A strong answer should normally cite at least one local `wwybsj` fact and at
  least one remote wiki/ontology/chunk support item, with clear boundaries. For
  cross-domain answers, say which remote domain carries each support item.

If remote search finds a strong passage before ontology does, use the passage to
harvest better anchors and retry ontology. If any remote layer is empty or
unavailable, say which layer failed and how that affects confidence.

### Step 4: Treat provenance as a gate

Before using a relation as an answer pillar, check whether it has usable support:

- local statement with meaningful qualifiers
- remote statement provenance
- page evidence
- search hit with clearly relevant source text

If support is weak, keep the claim but downgrade its wording.

### Step 5: Actively Search for Counter-Evidence

When a proposed answer would say `说明`, `证明`, `源自`, `承袭`, `直接影响`,
`标志性`, `专属`, `最早`, `都出自`, or any similar strong conclusion, do not
only retrieve supporting evidence. Build a short counter-evidence chain before
answering.

Check for:

- earlier chronology: remote `dated_to` or source passages showing the form,
  motif, technology, or institution predates the proposed source culture
- wider distribution: same or related artifact terms in other local registry
  records, cultures, regions, or periods
- directionality gaps: evidence of similarity without explicit transmission,
  source, workshop, textual link, stratigraphy, or provenance
- context alternatives: the same artifact class used in palace, temple, tomb,
  residential, ritual, or decorative contexts
- term inflation: a term that supports `high-status`, `Chinese-style`,
  `architectural`, or `palatial` interpretation but not a dynasty-specific
  origin
- local negative evidence: local registry lacks excavation place, exact context,
  or direct association even if remote background is strong

Counter-evidence is not automatically a new conclusion. Treat it as a calibration
tool:

- strong counter-evidence can overturn a claim
- weak or unprovenanced counter-evidence can still downgrade wording
- report provenance gaps rather than hiding them
- prefer `not established`, `可比较`, `相关`, `吸收/互动的可能`, or `高等级建筑语汇`
  over `证明`, `直接承袭`, or `唐制来源` when directionality is missing

Example pattern:

```markdown
反证链条：
- chronology: <earlier dated_to/source hit> means the form is not exclusive to the proposed period
- distribution: <local or remote comparanda> shows the class appears outside the proposed lineage
- directionality: <what evidence is missing> prevents `X directly inherited Y`
- calibrated conclusion: <what can still be safely said>
```

Concrete example:

- `渤海绿釉鸱尾残片` can support a high-status roof-decoration or palatial
  architectural vocabulary when paired with remote context.
- A remote `鸱尾 -[dated_to]-> 西汉武帝时` relation, even if provenance is thin,
  warns that `鸱尾` is not Tang-exclusive.
- Local `wwybsj` also has `高句丽残灰鸱尾` (`id=79`, `ww_bianhao=75`), showing
  the class appears in a non-Tang/渤海 local comparison point.
- Therefore `出鸱尾 -> 渤海宫殿直接承袭唐制` is not established. Safer wording:
  `显示渤海建筑与中古中国/东北亚高等级建筑装饰传统存在关联或可比较性`.

## Chronology and Cultural Background Discipline

When answering comparative, interpretive, schema, or normalization-audit
questions, separate these time layers:

- `general historical background`: broad date ranges or cultural summaries from
  remote TDB lab domains or common period knowledge, such as a dynasty, polity,
  or reign framework
- `local registry dating`: the exact `ww_niandai_a/b/c/d/jt` values recorded
  for each `wwybsj` item, including label-only values such as `唐代` or `渤海`,
  empty fields, and internally inconsistent name/date combinations
- `business normalization policy`: the `wwybsj_business_terms` rules that define
  how fields such as `period.raw_value` and `dynasty` should be interpreted

Rules:

- Do not inspect only `ww_niandai_jt` when the question is about a possible
  period inconsistency. Read the full hierarchy:
  `ww_niandai_a | ww_niandai_b | ww_niandai_c | ww_niandai_d | ww_niandai_jt`.
- Treat `period.raw_value` as the preserved full hierarchy, not as a single
  normalized dynasty label.
- If `dynasty` is being audited as a specific-level normalized field, prefer
  `ww_niandai_jt`; parse parenthetical forms such as `唐（渤海）` as framework
  `唐` plus specific `渤海`, then flag a `dynasty=唐` output as a normalization
  inconsistency unless a different policy is explicitly documented.
- If an item is only registered as `唐代` or `渤海`, say the registry gives a
  coarse label and does not support finer phase claims such as early, high,
  middle, or late Tang.
- If a registry entry gives a specific range or reign period, cite it as that
  item's local fact, not as the date of the whole comparison set.
- If the name and date field diverge, report the divergence and avoid smoothing
  it away. Example: a name containing `唐` but `ww_niandai_jt=渤海` is a review
  issue, not proof that both labels are simultaneously certain.
- Use historical date ranges to introduce cultural background only. Make the
  wording explicit: `从通史背景看...`; `本馆登记则只写...`.
- In comparison answers, give short separate background paragraphs for each
  culture/period before synthesis when that helps the reader form their own
  comparison.

## Evidence Report Protocol

Every answer should make the retrieval and evidence boundary visible. For short
user-facing writing tasks, keep the report compact. For research or QA tasks, use
the fuller form.

### Compact Report

Use this after the main answer when the user asks for museum labels, summaries, or
visitor-facing prose. Keep it short, but preserve numeric citations and a final
`References` section unless the user explicitly asks for answer-only prose:

```markdown
依据与边界：
- 本地 wwybsj：<registry/wiki/statement facts used>
- 远端 TDB lab：<domain>=wiki/ontology/chunk/provenance used; label auxiliary-domain support as background-only when appropriate>
- 反证/降级依据：<counter-evidence that weakens strong wording>
- 解释性用法：<which claims are interpretation, not direct item facts>
- 未能确认：<missing local evidence such as excavation place, exact use, direct comparandum>
```

### Full Report

Use this for analytical answers, debugging, or when the user asks to see evidence:

```markdown
检索计划：
- Concepts checked: <anchors>

本地 wwybsj 证据：
| claim | support | source/path | confidence |

远端 TDB lab 证据阶梯：
| domain | layer | claim/context | support | source/path | confidence |

反证与降级依据：
| strong claim tested | counter-evidence checked | result | wording impact |

证据边界：
- 登记事实：<safe direct statements>
- 研究解释：<interpretive statements and why>
- 不能确证：<claims not supported locally>

查询记录：
- local: <endpoint/query/result count>
- remote: <domain/gateway/endpoint/query/result count/resolved_stream_ids>
```

Report rules:

- Never hide an empty local result if the answer relies on the registry or remote
  background instead.
- If local wiki and `wwybsj.json` disagree, report both and prefer the registry file for raw registration fields while treating wiki prose as a derived projection.
- If a business ontology rule shaped the lookup or normalization audit, cite the
  applied `wwybsj_business_terms` raw term / canonical term / semantic slot.
- When reporting local wiki retrieval, name the gateway if relevant:
  `local 10.124.48.91:8997`, not any remote lab gateway.
- Name whether `7号` means local `ww_bianhao=7` or internal `id=7` when the two
  differ.
- Default rule for plain user-facing phrases such as `3号展品`, `7号藏品`,
  `9号文物`, `第9号馆藏`, or `#9`: resolve them as collection registry numbers
  (`ww_bianhao`). Use the internal JSON/database `id` only when the user
  explicitly says `record_id`, `内部id`, `JSON id`, `数据库id`, or similar.
- Treat stream ids named `wwybsj.context.registry.0009` as registry-number
  streams. Treat `wwybsj.context.record.0009` as internal-row streams. Avoid
  relying on legacy bare streams such as `wwybsj.context.0009` unless you first
  verify which numbering system created them.
- Prefer source paths, page slugs, statement IDs, event IDs, or local file paths
  over vague phrases like `TDB says`.
- If a remote source only supports general background, label it `background only`.
- Report each queried remote lab domain as `wiki`, `ontology`, and `chunk`
  layers. If a layer or auxiliary domain was not queried, say why; if it
  returned no usable support, say `empty`, `not usable`, or `unavailable`.
- When a remote claim enters reasoning, name the domain and layer that supports
  it. Example: `art_history chunk supplies source text; archeology ontology
  suggests the comparable class`.
- If provenance cannot be retrieved, say `provenance not recovered` and downgrade
  the wording.
- If counter-evidence was checked, report whether it overturns the claim,
  downgrades the wording, or is too weak to use.
- Do not let the evidence report overwhelm a museum label; a compact report is
  enough unless the user asks for the full audit trail, but the compact report
  still uses the same numeric citations as the answer.

## Answer Framing

Every non-trivial answer should separate three layers when relevant:

1. `馆藏可直接确认`
2. `结合考古语料可作的解释`
3. `反证或降级依据`
4. `目前不能确定`

Useful wording examples:

- `本馆登记可直接确认……`
- `结合远端 archeology / art_history / history 等语料，可将其理解为……`
- `这更像同类器比较，不等于该件文物本身被直接记载为……`
- `这条证据支持……，但反证检索显示它不足以推出……`
- `方向性结论目前 not established；可改写为……`
- `目前本地 wwybsj 还不足以确认……`

For generated museum prose, write the visitor-facing text first, then append the
compact evidence report and `References`. Keep citations compact and sentence-end
where possible so they do not overwhelm the exhibit label.

## Confidence Rules

### Safe to state directly

- local registry facts from `wwybsj`
- local wiki conclusions that clearly rest on local statements and evidence
- remote TDB lab statements that are explicitly about a general class, period,
  comparable artifact, style, ritual context, or environmental setting

### Must be stated as interpretation

- using a remote comparable artifact to explain a local item
- mapping a registry term to a broader archaeology, art-history, historical,
  anthropological, theoretical, environmental, or humanities term
- inferring likely function from class / material / comparandum
- connecting an item to a broader site or capital-city tradition without direct local provenance
- turning a shared form, motif, material, or architectural vocabulary into
  influence, lineage, or cultural transmission when directionality is not proven

### Must be stated as unknown unless directly supported

- exact excavation location of a collection item
- exact tomb / site / palace origin
- direct one-to-one identity with a remote comparandum
- broad generalizations like `这批都出自 X`
- dynasty-exclusive origin claims such as `唐代专属`, `直接承袭唐制`, or
  `由 X 传播至 Y` when the evidence only shows similarity or co-occurrence

## Common Question Types

### Single-item question

For `这件文物是什么 / 有什么特征 / 有什么用途`:

- identify the local item in `wwybsj`
- recover its registry facts
- pull local report / statements if present
- use `archeology` to explain type, comparanda, terminology, and archaeological
  context; add auxiliary domains only when the question asks for style, ritual,
  chronology, theory, environment, or text comparison

### Collection-slice question

For `这批汉代玉器有什么特征`:

- first establish the local slice from `wwybsj`
- list what the collection actually contains
- summarize only the traits supported across that slice
- use `archeology` and relevant auxiliary domains to explain why those traits
  matter historically, artistically, socially, ritually, or environmentally

Do not let any remote lab domain answer for items that are not actually present in the local slice.

### Place-constrained question

For `西安出土的……` or `都在哪里出土`:

- require local `wwybsj` place evidence first
- if the local domain lacks place data, say so
- remote `archeology`, `history`, or `geo_environment` may explain the broader
  region, route, landscape, or site tradition, but cannot substitute for missing
  local provenance

### Exhibition or museum interpretation question

For `我要开博物馆 / 这批文物怎么讲 / 最大艺术成就是什么 / 宗教意义是什么`:

- establish the local collection slice first: item names, dates, materials,
  classes, condition, and source from `wwybsj` or `wwybsj.json`
- use `art_history` for visual style, iconography, craft, and display framing
- use `history` for dynasty/polity chronology and exchange background
- use `anthropology_sociology` for ritual, social organization, identity, or
  community interpretation
- use `archeology` for comparable artifacts, sites, typology, and source-text
  grounding
- write the curatorial thesis as interpretation, not as a registry fact, unless
  local evidence directly supports it

## Failure Modes

Watch for these mistakes:

- querying `wwybsj` on `10.124.48.91:8989` and concluding the local collection wiki is empty
- treating a `search/query` hit from an `archeology.*` stream as local `wwybsj` evidence
- treating a hit from `history`, `art_history`, `anthropology_sociology`,
  `philosophy_theory`, `geo_environment`, or `literature_humanities` as local
  collection evidence
- trusting remote `search/query` hits when `resolved_stream_ids` is empty
- forgetting to URL-encode Chinese wiki slugs such as `ww-0139-唐代海兽葡萄纹铜镜`
- forgetting that the full local registry snapshot is available at `wwybsj.json` in the skill directory
- answering from a remote lab domain as if it directly described the local collection item
- searching only one remote lab layer, such as wiki or chunks, then
  presenting an interpretive answer as fully grounded
- failing to let remote wiki, ontology, and chunk hits cross-check each other
- collapsing `发掘` and `征集购买` into one provenance story
- treating a background relation like `related_to 上京龙泉府` as direct excavation proof
- summarizing a handful of item names as if they were a proven typology
- ignoring qualifiers that narrow time, scope, or confidence
- only searching for supporting evidence when the draft answer makes a strong
  claim such as `说明`, `证明`, `承袭`, `源自`, or `专属`
- treating a shared artifact form as proof of direct transmission without
  checking earlier chronology, wider distribution, and directionality gaps
- converting `high-status`, `palatial`, `Chinese-style`, or `architectural`
  evidence into `Tang-derived` evidence
- using weak counter-evidence as a new overclaim; if provenance is thin, use it
  to downgrade wording and say the provenance was not recovered

## Minimum Debug Discipline

If the answer is thin, say which layer failed:

- `wwybsj wiki empty`
- `wwybsj wiki checked on wrong gateway; retry local 10.124.48.91:8997`
- `wwybsj.json checked / not checked for full local registry fallback`
- `wwybsj statements sparse`
- `wwybsj search unavailable or errored`
- `remote domains/gateways checked or not checked`
- `remote domain unavailable or health check failed`
- `remote search resolved_stream_ids empty; hits treated as unscoped and not evidence`
- `archeology wiki / ontology / chunk layer checked or not checked`
- `auxiliary domain wiki / ontology / chunk layer checked or not checked`
- `remote lab domain had only general background, not item-specific support`
- `remote ontology suggested a relation but provenance/chunk support was not recovered`
- `remote chunks found source text but no matching ontology statement was recovered`
- `no local evidence for place of excavation`
- `counter-evidence checked / not checked for strong directionality claim`
- `counter-evidence found but provenance thin; wording downgraded`

The goal is not just to answer, but to answer with the right boundary between collection fact and archaeological interpretation.
