# TDB WWYBSJ Advanced Task Protocols

Use this reference after `SKILL.md` route classification. Keep every task grounded
in the same evidence boundary:

- `wwybsj` gives collection truth: registry facts, local wiki, local statements,
  and local provenance.
- `archeology` gives interpretation: comparanda, terminology, cultural context,
  source passages, and broader historical explanation.
- Analytics datasets, if supplied separately, are a third layer. Do not treat
  visitor or exhibition metrics as archaeological evidence.

## 1. Cultural Comparison

Use for questions about different cultures, regions, periods, or collections:
`相似性`, `差异`, `影响`, `交流`, `同类器`, `跨文化比较`, `中外比较`,
`唐与渤海`, `草原与中原`, and similar prompts.

Retrieval:

1. Establish the local comparison slice in `wwybsj`: item ids, registry numbers,
   names, period labels, materials, categories, and any local place or acquisition
   evidence.
2. Resolve local controlled terms through L1 alignment when available.
3. Query `archeology` for comparable cultures, artifact classes, techniques,
   forms, motifs, contexts, and period anchors.
4. Pull provenance or source passages for each comparison axis.

### Theme Discovery Strategy

Use this when the user asks open-ended questions such as `这批展品能提出什么
不同文化的相似性`, `这批有什么跨文化主题`, or `怎么做文化比较`.

Do not start from a favorite historical narrative. Start from the collection
distribution and let dense clusters suggest themes:

1. Aggregate local `wwybsj` facts by category, material, period, acquisition, and
   category-by-period / material-by-period intersections.
2. Pull representative item names for the strongest clusters. Use these names to
   detect recurring motifs, forms, technologies, and contexts.
3. Look for repeated cross-cultural groupings, especially:
   - several cultures sharing one object class, material, motif, or technique
   - one culture/period cluster echoing a better-known regional tradition
   - one artifact class linking craft, architecture, ritual, military, exchange,
     or daily life
4. Turn each dense grouping into a candidate similarity theme. Phrase it as a
   research theme first, not as a conclusion.
5. Query remote `archeology` for the candidate theme's concepts and source text.
   Keep themes whose remote evidence supports the comparison axis. Downgrade or
   drop themes supported only by item-name coincidence.
6. Rank themes by:
   - local coverage: number and coherence of local items
   - cross-cultural spread: number of cultures/periods involved
   - interpretive value: whether it helps explain technology, ritual, social
     organization, exchange, or lifestyle
   - evidence strength: local facts plus remote background/provenance
7. Output themes with confidence and boundaries. Say which are ready for
   exhibition/research use and which need more provenance.

Useful local aggregation patterns:

```sql
-- category distribution
SELECT replace(value_entity_id,'wwybsj.term.category.','') AS category, COUNT(*)
FROM semantic_statement
WHERE metadata_json->>'domain'='wwybsj'
  AND property_id='wwybsj.predicate.instantiates'
  AND status='accepted'
GROUP BY 1 ORDER BY 2 DESC;

-- material distribution
SELECT replace(value_entity_id,'wwybsj.term.material.','') AS material, COUNT(*)
FROM semantic_statement
WHERE metadata_json->>'domain'='wwybsj'
  AND property_id='wwybsj.predicate.made_of'
  AND status='accepted'
GROUP BY 1 ORDER BY 2 DESC;

-- period distribution
SELECT value_json->>'era_label' AS period, COUNT(*),
       COUNT(*) FILTER (WHERE value_json->>'parse_status'='range_parsed') AS range_parsed
FROM semantic_statement
WHERE metadata_json->>'domain'='wwybsj'
  AND property_id='wwybsj.predicate.dated_to'
  AND status='accepted'
GROUP BY 1 ORDER BY 2 DESC NULLS LAST;

-- category by period
SELECT replace(c.value_entity_id,'wwybsj.term.category.','') AS category,
       d.value_json->>'era_label' AS period,
       COUNT(*)
FROM semantic_statement c
JOIN semantic_statement d ON c.subject_id=d.subject_id
WHERE c.metadata_json->>'domain'='wwybsj'
  AND d.metadata_json->>'domain'='wwybsj'
  AND c.property_id='wwybsj.predicate.instantiates'
  AND d.property_id='wwybsj.predicate.dated_to'
  AND c.status='accepted'
  AND d.status='accepted'
GROUP BY 1,2 HAVING COUNT(*) >= 4
ORDER BY 3 DESC, 1, 2;
```

High-yield theme patterns:

- `shared architectural system`: tile ends, roof tiles, eaves tiles, drip tiles,
  ridge ornaments, column-base fittings, palace/temple building components
- `shared motif system`: lotus, scroll/grass, auspicious beasts, Buddhist images,
  grapes, sea beasts, geometric or cord patterns
- `shared glaze and ceramic technology`: green glaze, sancai, celadon, whiteware,
  underglaze painting, molded or stamped decoration
- `shared Buddhist material culture`: Buddha images, bodhisattva images, lotus
  pedestals, temple architecture, devotional or ritual imagery
- `shared iron-technology horizon`: iron arrowheads, knives, axes, chisels,
  nails, cauldrons, agricultural tools, craft tools
- `shared exchange/consumption network`: coins, mirrors, porcelain, tea wares,
  portable prestige goods, trade-facing ceramics
- `long-duration ritual/status continuity`: jade, stone, bronze, mirrors, ritual
  vessels, burial or elite display items

For each proposed theme, state:

```markdown
- 主题：<short research/exhibition theme>
- 本地覆盖：<cultures/periods + representative item groups>
- 相似性轴：<form/material/motif/function/context/social meaning>
- 远端支撑：<concepts/source passages found, or background only>
- 可说到什么程度：<strong / medium / weak wording>
- 不能推出：<influence, migration, same workshop, same excavation context, etc.>
```

Example calibrated wording:

- Stronger: `这批展品可以支持一个关于唐、渤海、新罗建筑陶构件和莲花纹装饰的跨文化比较主题。`
- Medium: `这些材料显示出可比较的佛教视觉语汇和建筑装饰传统。`
- Weaker: `目前只能提出相似性观察，尚不足以证明直接传播路线或共同工坊。`

Comparison axes:

- form / shape / morphology
- material and craft technique
- motif / iconography / decoration
- function and use context
- chronology and period overlap
- archaeological context: settlement, tomb, ritual, military, production, trade
- social meaning: status, identity, religious practice, political order

### Background-First Comparison

Use this when the audience needs enough context to make their own comparison,
especially for prompts like `唐与渤海`, `绿釉与三彩`, `中原与东北`, or broad
museum interpretation.

Before the comparison section, write brief standalone introductions for each side:

- culture / period background from `archeology` or general historical context
- local `wwybsj` holdings that belong to that side
- exact local registry dating status: specific year range, reign period, coarse
  label only, blank date field, or name/date mismatch
- dominant object context: architecture, burial, ritual, daily use, sculpture,
  decorative component, etc.

Chronology wording must stay calibrated:

- `从通史背景看，唐代通常可放在...框架中；本馆该件/该组登记只写...`
- `从通史背景看，渤海通常可放在...框架中；本馆该件/该组中只有部分登记写明...`
- `该件名称含唐，但年代字段登记为渤海；应作为待复核项，不作为强证据。`
- `该件年代字段为空；只能作为器名/类型参照，不能参与年代排序。`

Only after these background blocks should the answer synthesize similarities and
differences. This prevents a remote historical range from silently becoming a
local item date.

Output shape:

```markdown
背景简介：
- <side A>: <culture context + local holdings + dating limits>
- <side B>: <culture context + local holdings + dating limits>

比较结论：
- 相似点：<axis + evidence>
- 差异点：<axis + evidence>
- 可能解释：<exchange, shared technology, parallel development, or uncertain>

证据边界：
- 本地可确认：<wwybsj facts>
- 远端比较依据：<archeology source/provenance>
- 不能推出：<claims not supported locally>
```

Guardrails:

- Do not claim influence or migration unless the evidence supports directionality.
- Prefer `相似`, `可比较`, `显示出共同技术背景` over `源自`, `传播自`,
  or `受 X 直接影响` unless provenance supports the stronger wording.
- A shared material or form is not enough to prove shared culture.
- Do not treat broad dynasty/polity dates as local collection dates. Report
  label-only dates, blank dates, and name/date mismatches in the evidence
  boundary.

## 2. Lineage, Typology, and Transmission

Use for `谱系`, `源流`, `演变`, `类型学`, `技术传统`, `传承`, `传播路径`,
`从哪里来`, `和谁一脉相承`.

Retrieval:

1. Identify whether the subject is an artifact individual, a local term, an
   artifact class, a material, a technique, or a motif.
2. For item-level lineage, start with local `instantiates`, `made_of`,
   `dated_to`, and any local provenience or acquisition facts.
3. For term/class lineage, use L1 alignment to reach remote concepts.
4. Search `archeology` for chronological predecessors, successors, typological
   variants, production methods, distribution, and named traditions.
5. Prefer evidence with explicit time order, spatial relation, and material/form
   continuity.

Output shape:

```markdown
谱系判断：
- 已知节点：<local item/type + date/material/category>
- 可比较上游：<earlier remote concepts, with evidence>
- 可比较下游/旁支：<later or parallel concepts, with evidence>
- 关系强度：<direct lineage / plausible tradition / loose comparandum / unknown>

不能确证：
- <missing excavation context, production workshop, direct textual linkage, etc.>
```

Guardrails:

- Do not turn typological resemblance into genealogical descent.
- Use `类型学上的近缘关系` for form-based relation and reserve `谱系` for cases
  with chronological and contextual support.
- If `dated_to` has `parse_status=label_only`, say time ordering is coarse.

## 3. Association, Chronology, and Social Interpretation

Use for `关联性`, `年代`, `生活方式`, `宗教`, `祭祀`, `战争`, `武器`,
`军事`, `部落`, `国家`, `政权`, `社会形态`, `聚落`, `墓葬`, and questions
that ask what archaeological finds imply about human life.

Retrieval:

1. Establish the local artifact set and its date/material/category constraints.
2. Separate direct association from contextual association:
   - direct: same local record, same excavated context, same site/tomb/layer, or
     local statement support
   - contextual: remote literature links artifact class to a social practice
3. Query remote `archeology` for contexts where the artifact class appears:
   settlement, burial, palace, craft production, ritual, warfare, trade, diet,
   dress, administration, and polity formation.
4. Recover provenance for social claims. Social interpretation needs stronger
   evidence than object description.

Interpretation ladder:

- `物性事实`: material, dimensions, form, condition, date
- `功能解释`: likely use based on class and comparanda
- `场景解释`: burial, settlement, ritual, production, military, trade, etc.
- `社会解释`: lifestyle, religious practice, warfare organization, identity,
  tribe/chiefdom/state formation

Output shape:

```markdown
年代与关联：
- 本地年代依据：<dated_to facts and parse status>
- 关联对象：<items/sites/classes/concepts>
- 关联类型：<direct / contextual / speculative>

社会解释：
- 生活方式：<supported interpretation>
- 宗教/礼制：<supported interpretation>
- 战争/权力：<supported interpretation>
- 部落或国家形态：<supported interpretation>

证据强度：
- 强：<direct or well-provenanced>
- 中：<class-level background>
- 弱：<analogy only>
```

Guardrails:

- Do not infer religion from decoration alone without contextual support.
- Do not infer warfare from the presence of metal unless the object type and
  context support military use.
- Do not infer tribe/state form from one artifact. Require a pattern across
  settlement, burial, production, administration, exchange, or textual evidence.

## 4. Automated Reports

Use for `自动发掘报告`, `发掘报告`, `研究报告`, `馆藏报告`, `展览研究`,
`策展报告`, `文物说明书`, `考古报告草稿`.

Before writing, identify the report type:

- excavation-style report: site/context/layers/features/finds
- collection report: registry facts, classification, conservation, research
- research report: question, evidence, analysis, uncertainty
- exhibition dossier: interpretive theme, object list, visitor-facing claims

Minimum report structure:

```markdown
# <title>

## 摘要
## 资料来源与方法
## 本地馆藏事实
## 考古背景与比较材料
## 年代、类型与关联分析
## 解释：生活方式 / 宗教 / 战争 / 社会组织
## 证据边界与不确定性
## 可继续补证的问题
```

Excavation-style guardrails:

- If no local excavation context exists, call it `发掘报告式研究草案` or
  `馆藏研究报告`, not a real excavation report.
- Do not invent trench, layer, tomb, unit, stratum, feature, coordinate, or
  excavation season data.
- If the collection was acquired by purchase/donation/collection, keep that
  separate from excavation provenance.

Evidence table:

```markdown
| claim | layer | source | confidence | note |
|---|---|---|---|---|
| <claim> | 登记事实 / 研究解释 / 未确证 | <path/id/source> | high/medium/low | <boundary> |
```

## 5. Museum Analytics

Use for `观众数据`, `展览数据`, `宣教数据`, `媒体数据`, `研究数据`,
`传播效果`, `观众画像`, `展览评估`, `教育活动`, `社媒`, `论文引用`,
and related museum operation or public-impact analysis.

Data layers:

- collection layer: `wwybsj` item facts and research context
- interpretation layer: `archeology` background and evidence
- analytics layer: external audience, exhibition, education, media, research, or
  operational datasets supplied by the user or connected tools

If analytics data is present, inspect schema first:

- audience: visit date, demographics if allowed, group type, ticket/channel,
  dwell time, survey response, satisfaction, route, repeat visits
- exhibition: object ids, gallery, label/theme, placement, duration, interactions,
  attendance, conversion, feedback
- education: activity id, audience segment, topic, object ids, participation,
  learning outcome, teacher/student feedback
- media: channel, campaign, post/article/video id, object/topic tags, reach,
  engagement, sentiment, referral
- research: publication, citation, topic, object ids, researcher, institution,
  method, finding, date

If analytics data is absent, do not fabricate metrics. Return:

```markdown
现有可分析：
- <collection/research facts available from TDB>

暂不能分析：
- <missing audience/exhibition/media/research fields>

建议补充字段：
- <minimum viable dataset>

可做的应用：
- <segmentation, theme planning, label A/B hypotheses, education route,
  media topic map, research impact map>
```

Application patterns:

- link objects to themes through local category/material/date and remote concepts
- build visitor segments by behavior or survey response, not by unsupported
  demographic assumptions
- evaluate exhibitions with attendance, dwell, interaction, recall, satisfaction,
  and learning outcomes
- evaluate media with reach, engagement, conversion to visit, and topic resonance
- evaluate research with object-topic networks, citations, collaboration, and
  evidence reuse

Privacy and ethics:

- Use aggregate analysis by default.
- Do not infer sensitive attributes unless explicitly present, allowed, and
  necessary.
- Separate observed visitor behavior from interpretive conclusions.
