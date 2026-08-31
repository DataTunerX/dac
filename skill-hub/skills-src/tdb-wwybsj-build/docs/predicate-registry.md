# wwybsj 谓词清单

全部谓词都在 `wwybsj.predicate.` 前缀下。**绝不使用裸名**（`is_a`、`related_to` 等在
`semantic_entity` 里是全局单例，写一次就会抢占其他域正在用的谓词的归属标签——
见 [layered-ontology.md](layered-ontology.md) §1.1）。

计数为 2026-08-14 实际库内统计。

---

## 1. L0 谓词（23 个，全部 `epistemic_mode=observed`）

`semantic_role` 一栏：`entity` 值走 `object_property`，字面值走 `datatype_property`
（拼成 `data_property` 会得到裸 HTTP 500）。

### 1.1 标识与命名

| 谓词 | value_type | 登记字段 | 条数 | 说明 |
|---|---|---|---|---|
| `has_registry_no` | string | `ww_bianhao` | 465 | 藏品总登记号。**inverse functional**——它是对外的唯一键，`record_id` 只是 JSON 行号，两者绝不可混（`record_id=12` 对应 `ww_bianhao=0008`）|
| `has_registry_scheme` | string | `ww_bh_leixing` | 465 | 编号体系名，全库唯一取值「藏品总登记号」|
| `has_name` | string | `ww_mingchen` | 465 | 文物名称。**functional** |
| `has_original_name` | string | `ww_yuanming` | 224 | 文物原名 |

### 1.2 分类与材质

| 谓词 | value_type | 登记字段 | 条数 | 说明 |
|---|---|---|---|---|
| `instantiates` | entity | `ww_leibie` | 465 | → `wwybsj.term.category.*`。**functional**。10 个取值，其中 4 个是联合桶（`玉石器、宝石` 等）|
| `made_of` | entity | `ww_zhidi_c` | 467 | → `wwybsj.term.material.*`。**非 functional**：`铜,金` 拆成两条（2 件文物如此）|
| `has_material_form` | string | `ww_zhidi_a` | 181 | 单一质地 / 复合或组合质地 |
| `has_material_class` | string | `ww_zhidi_b` | 465 | 无机质 / 无机复合或组合 |

### 1.3 年代

| 谓词 | value_type | 登记字段 | 条数 | 说明 |
|---|---|---|---|---|
| `dated_to` | json | `ww_niandai_jt` > `_d` > `_c` > `_b` | 377 | **functional**。typed 区间，见 §2.1 |
| `in_period` | entity | 同上 | 376 | → `wwybsj.term.period.*`。**functional**。`dated_to` 是用于推理的 typed 区间，`in_period` 是可被 L1 锚定的词项——**JSON 值挂不住锚点，必须是实体**。这是能写出文化/朝代背景的前提 |
| `has_period_scheme` | string | `ww_niandai_a` | 465 | 断代体系（中国历史学年代 / 其他）。**这是体系名，不是年代**，不要当年代用 |

字段优先级：`ww_niandai_jt`（具体年代）最优，其次 `_d` → `_c` → `_b`。
`ww_niandai_a` 只作为体系名单独记录，永不当作年代。

### 1.3.1 年代标签归并

登记簿有 **31 种**年代写法，同一政权被拆成多个标签，任何按文化聚合的分析都会算错：

```
唐代 53 / 唐 3 / 晚唐 1 / 唐天宝年间 1        高句丽 36 / 高勾丽 3（OCR 异体字）
战国时代 29 / 战国 25                        商 15 / 商代 7      明 12 / 明代 4 / 明崇桢 1
```

归并规则在 `../period_normalization.json`，31 → **20 个词项**，148 条 statement 走了归并。
每条带 `label_normalization` qualifier（`canonical` / `merged`）与 `registry_era_label`。

只并**确定同指**的（去「代」后缀、年号归朝代、修异体字）。**不并**真正不同的分期——
`西汉`/`东汉`、`西周`/`东周`、`北魏`/`东魏` 年份区间不同，合并会丢真信息；`南宋` 有独立
历史身份，不并入 `宋`。`宋-元` 跨两朝，**不建词项**，改发数据质量标记
`period_label_spans_multiple_polities`。

**`dated_to` 的 `registry_literal` 与年份区间原样保留**——归并只影响可锚定的词项，
登记簿的原始表述不被覆盖。

### 1.4 量值

| 谓词 | value_type | 登记字段 | 条数 | 说明 |
|---|---|---|---|---|
| `has_mass` | json | `ww_zhiliang_jt` + `_dw` | 313 | **functional**。单位在独立列，故 `normalized_g` 安全 |
| `has_mass_range` | string | `ww_zhiliang_fw` | 370 | 质量区间桶（`0.01-1 kg` 等），登记簿自带的粗分级 |
| `has_dimension` | json | `ww_chang` / `ww_kuan` / `ww_gao` | 224 | 覆盖 129 件（一件多条）。**`unit` 恒为 null**——登记 schema 从未声明单位 |
| `has_dimension_note` | string | `ww_chicun` | 434 | 自由文本原文照存，`parse_status=unparsed_free_text`。**故意不解析**，理由见 layered-ontology.md §2.4 |
| `has_quantity` | json | `ww_shuliang` | 465 | **functional**。件数 |

### 1.5 状态与管理

| 谓词 | value_type | 登记字段 | 条数 | 说明 |
|---|---|---|---|---|
| `has_completeness` | entity | `ww_wancan_cd` | 465 | → `wwybsj.term.completeness.*`。**functional** |
| `has_completeness_note` | string | `ww_wancan_zk` | 380 | 完残状况自由描述（`残三块` 等）|
| `has_conservation_state` | string | `ww_baocun_zt` | 465 | 保存状态自由描述 |
| `has_grade` | entity | `ww_jibie` | 465 | → `wwybsj.term.grade.*`。**functional**。一级/二级/三级/一般/未定级 |
| `acquired_by` | entity | `ww_laiyuan` | 465 | → `wwybsj.term.acquisition.*`。**functional**。入藏途径 |
| `registered_at` | string | `ww_ctime` | 465 | 入库时间 |

### 1.6 元断言

| 谓词 | value_type | 来源 | 条数 | 说明 |
|---|---|---|---|---|
| `has_data_quality_flag` | json | 派生 | 751 | 覆盖全部 465 件。**非 functional**。是可查询的 statement，不是日志 |

标记代码：

| code | 条数 | 含义 |
|---|---|---|
| `dimension_only_in_free_text` | 335 | 尺寸仅在 `ww_chicun`，结构化列全 0，不可数值推理 |
| `period_label_without_years` | 287 | 年代仅有标签，无区间，不可时间推理 |
| `dimension_unit_unspecified` | 129 | 长/宽/高无单位来源，跨件比较前须先定单位 |
| `mass_unit_missing` | 0 | 有质量数值但 `ww_zhiliang_dw` 为空（实际未出现）|
| `period_label_spans_multiple_polities` | 1 | 年代标签跨多个政权（`宋-元`），无法归入单一政权词项 |

---

## 2. L0 的 typed 值形状

### 2.1 `dated_to`

```json
{
  "era_label": "唐",
  "start_year": 618,
  "end_year": 907,
  "calendar": "CE",
  "parse_status": "range_parsed",
  "registry_literal": "唐(618~907)"
}
```

`start_year` / `end_year` 为负表示公元前（`战国时代(前475~前221)` → `-475` / `-221`）。

只在字面明确写出年份时才产出年份。否则：

```json
{"era_label": "渤海", "start_year": null, "end_year": null,
 "calendar": "CE", "parse_status": "label_only", "registry_literal": "渤海"}
```

`parse_status` 分布：`range_parsed` 90 / `label_only` 287。

已验证可解析的字面形态：

```
唐(618~907)              战国时代(前475~前221)      西汉(前206~公元25)
渤海（698年—926）         渤海（698—926）            渤海（公元698—926年）
唐天宝年间(公元742-756)
```

**已知登记簿冲突**：`东周` 有三个互相矛盾的区间——`-770~-256` / `-770~-257` /
`-770~-258`。L0 保留 `registry_literal` 使冲突可查询，不做静默归一。

### 2.2 `has_mass`

```json
{
  "value": 0.48, "unit": "kg", "unit_source": "registry_column",
  "normalized_g": 480.0, "registry_literal": "0.480"
}
```

`unit_source` 取值：`registry_column`（单位在 `ww_zhiliang_dw` 列）/ `missing`。
`normalized_g` **只在单位显式存在时才产出**——这是它可以安全用于跨件比较的前提。
单位映射：`g`=1.0、`kg`=1000.0。

### 2.3 `has_dimension`

```json
{
  "dimension": "height", "label_zh": "高", "value": 11.3,
  "unit": null, "unit_source": "unspecified",
  "registry_field": "ww_gao", "registry_literal": "11.3"
}
```

`dimension` 取值：`length` / `width` / `height`（对应 `ww_chang` / `ww_kuan` / `ww_gao`）。

**`unit` 恒为 `null`，`unit_source` 恒为 `unspecified`。** 登记 schema 和 DDL 注释里
都没有单位声明，消费者必须显式确定单位，不得假设厘米。

### 2.4 `has_quantity`

```json
{"count": 3, "registry_literal": "3"}
```

### 2.5 `has_data_quality_flag`

```json
{"code": "dimension_only_in_free_text",
 "note": "尺寸仅存在于自由文本 ww_chicun，结构化列全为 0，无法用于数值推理"}
```

---

## 3. 契约与强制

### 3.1 真相来源是 `predicate_contract.json`

全部 26 个谓词的契约在 `../predicate_contract.json`，由 `wwybsj_predicates.py` 读取：

```bash
python3 wwybsj_predicates.py --validate                    # 校验（真正起作用的部分）
python3 wwybsj_predicates.py --validate --fail-on-violation # CI
python3 wwybsj_predicates.py --register --execute          # 镜像到 ontology_relation_type
python3 wwybsj_predicates.py --report                      # 已注册状况
```

### 3.2 为什么强制必须自己做

**数据库不会替你把关**，四条实测结论：

- `semantic_statement` 上**没有任何触发器**。
- `POST /v2/ontology/semantic/upsert-batch` **从不查** `ontology_relation_type`，
  它按面值接受 `property_id` 并按需创建 property 实体。
- `ontology_relation_type` **根本没有 `is_functional` 列**。functional 只能借
  `conflict_key='src_predicate'` + `conflict_policy` 间接表达，而那两列管的是
  pipeline 的 promotion，不是这条写入路径。
- 它的 `dst_type_id` 假定对象是实体，所以 21 个字面值/json 值谓词**根本无法在
  那张表里描述**。

另外 upsert API 只暴露 `predicate / src_type_id / dst_type_id / display_name /
description / is_symmetric / is_transitive / enabled`——`conflict_key` 和
`conflict_policy` 必须走 SQL。

所以：**能注册的注册（5 个），全部靠校验器强制（26 个）。**

### 3.3 已注册到 `ontology_relation_type`（5 个）

| predicate | src → dst | conflict_key | policy |
|---|---|---|---|
| `instantiates` | `collection_artifact` → `artifact_type` | `src_predicate` | `block_promotion` |
| `made_of` | `collection_artifact` → `material` | `src_predicate_dst` | `allow_multi` |
| `has_completeness` | `collection_artifact` → `condition` | `src_predicate` | `block_promotion` |
| `has_grade` | `collection_artifact` → `administrative_status` | `src_predicate` | `block_promotion` |
| `acquired_by` | `collection_artifact` → `collection_acquisition` | `src_predicate` | `block_promotion` |

新建了 1 个 object_type：`collection_acquisition`（入藏途径）。其余复用既有类型。

注：库内既有的 135 个 relation_type **全是默认值**（`src_type_id='entity'`、
`is_symmetric=f`、`conflict_key='src_predicate'`），这张表此前从未被当契约用过。

### 3.4 校验器的 14 项检查

| 检查 | 内容 |
|---|---|
| V1 | 库内在用但契约未声明的谓词 |
| V3 | `value_type` / `layer` 与契约不符 |
| V4 | **functional 被违反**（同一主体同一谓词多于一条）|
| V5 | **inverse functional 被违反**（同一值被多个主体持有）|
| V6 | 主体 id 前缀与 `subject_kind` 不符 |
| V7 | entity 值的对象 facet 与契约不符 |
| V8 | `epistemic_mode` 超出该层允许集合 |
| V9 | 必需 qualifier 缺失 |
| V10 | 必需 reference 缺失 |
| V11 | json 值必需键缺失 |
| V12 | json 枚举字段取值非法 |
| V13 | 使用了被禁谓词（`related_to` / artifact 上的 `influenced_by`）|
| V14 | 使用了非 `wwybsj.` 前缀的谓词（命名空间抢注防线）|

**当前状态：26 个谓词、9363 条 statement，14 项检查全部通过。**

校验器本身做过自测——用扰动契约（不动数据）逐项触发 V1/V3/V4/V5/V6/V7/V8/V9/V10/
V11/V12/V13，V14 用一条一次性裸名探针触发后立即删除。一个永远通过的校验器没有价值。

自测中发现并修掉了校验器自己的两个 bug：

1. `sql()` 用了 `out.strip()`，而 **Python 里 `'\x1f'.isspace()` 是 `True`**，
   所以作为字段分隔符的首个 `\x1f` 被剥掉了——任何首列为 NULL 的行会静默变成
   单字段行。改用 `rstrip("\n")`。
2. V5 对实体值谓词误用 `value_json->>'text'` 比较，全为 NULL 会导致**误报**。改为
   按 `value_type` 选择 `value_entity_id` 或 `value_json::text`。

### 3.5 functional 清单（校验器强制）

**functional（9 个 + 6 个字面值，共 15 个）**：`has_registry_no` `has_registry_scheme`
`has_name` `has_original_name` `instantiates` `has_material_form` `has_material_class`
`dated_to` `has_period_scheme` `has_mass` `has_mass_range` `has_dimension_note`
`has_quantity` `has_completeness` `has_completeness_note` `has_conservation_state`
`has_grade` `acquired_by` `registered_at` `alignment_status`

**inverse functional（1 个）**：`has_registry_no`——两件文物共用一个藏品总登记号是
严重错误。

**非 functional（5 个）**：`made_of`（铜,金 → 两条）· `has_dimension`（长/宽/高 →
最多三条）· `has_data_quality_flag` · `aligned_to`（exact + broader 可并存）·
`alignment_candidate` · `alignment_rejected`

### 3.6 传递性 / 对称性

L0/L1 当前没有传递或对称谓词，`is_symmetric` / `is_transitive` 全为 `false`。
L2 若引入以下谓词，需在契约里一并声明（`planned_L2_predicates` 已占位）：

```
typological_parallel   symmetric  = true   defeasible = true
part_of                transitive = true
precedes               transitive = true   antisymmetric = true
```

### 3.7 被禁谓词

契约的 `forbidden_predicates` 段，由 V13 强制：

- **`related_to`** —— 无类型约束的 catch-all。旧 profile 里它的
  `subject_types`/`object_types` 几乎是全集，等于让类型检查失效。
- **artifact 上的 `influenced_by`** —— 主体错位，见 layered-ontology.md §0.1c。

## 4. L1 谓词（4 个，`epistemic_mode=inferred`）

主体是**受控词项**（`wwybsj.term.*`），不是文物。

| 谓词 | value_type | 条数 | 说明 |
|---|---|---|---|
| `aligned_to` | json | 23 | 锚点边。值是远端**同名概念簇**，不是单个 id |
| `alignment_candidate` | json | 1 | wiki-only 命中，`hypothesized` + `blocked_pending_review`，**不参与推理** |
| `alignment_rejected` | json | 2 | 同形词否决记录（`金`、`石`），可查询而非日志 |
| `alignment_status` | json | 36 | 每个词项一条，汇总对齐结果与尝试过的词面 |

### 4.1 `aligned_to` 值形状

```json
{
  "matched_surface": "陶器",
  "is_whole_label": true,
  "match_relation": "exact",
  "match_kind": "concept_cluster",
  "remote_domain": "archeology",
  "remote_gateway": "http://10.124.48.91:8989",
  "remote_canonical_name": "陶器",
  "basis": "remote_exact_concept_name_match",
  "resolved_at": "2026-08-14T...",
  "concept_ids": ["...", "…20 个…"],
  "primary_concept_id": "<字典序最小>",
  "primary_selection_rule": "lexicographic_min",
  "cluster_size": 20,
  "concept_types": ["entity"],
  "search_result_truncated": true,
  "ids_search_did_not_return": [],
  "cluster_completeness": "unknown_search_is_not_stable",
  "search_limit_used": 200
}
```

经过复核的锚点另带 `review` 子对象（`reason` / `evidence` / `reviewer` /
`review_status` / `reviewed_at`）；被排除成员的锚点另带 `excluded_concept_ids` 与
`exclusion_note`。

**消费约定：推理时 union `concept_ids` 全簇**，不要只用 `primary_concept_id`。
理由见 layered-ontology.md §3.3。

### 4.2 `match_relation`

SKOS 风格，指**远端目标**相对本地词项的宽窄：

| 值 | 条数 | confidence | 实例 |
|---|---|---|---|
| `exact` | 18 | 0.95（整词）/ 0.8（成分）| `陶器`→`陶器` |
| `broader` | 4 | 0.7 | `瓷器`→`陶瓷器`、`金`→`金属` |
| `narrower` | 1 | 0.7 | `铜器`→`青铜器`（青铜器 ⊂ 铜器）|
| `close` | 0 | 0.7 | 暂未使用 |

### 4.3 `alignment_status`

```json
{"status": "aligned_by_components", "reason": "",
 "attempted_surfaces": ["玉石器、宝石", "玉石器", "宝石"],
 "anchor_count": 2, "rejected_exact_count": 0, "candidate_count": 0,
 "artifact_uses": 229, "facet": "category", "label": "玉石器、宝石"}
```

`status` 取值：

| 值 | 词项数 | 含义 |
|---|---|---|
| `aligned` | 6 | 整词精确同名对齐 |
| `aligned_by_components` | 10 | 联合桶按成分对齐，或仅有 broader/narrower 映射 |
| `not_applicable` | 17 | 管理类词汇，不尝试对齐（**正确的边界，不是缺口**）|
| `unaligned` | 1 | 尝试过但无可用目标（`石`，同形词否决）|
| `leave_unaligned` | 1 | 复核决定不对齐（`宝玉石`，远端确实没有）|

---

## 5. L2 谓词（4 个）

主体是**文物个体**。主体是通用概念的断言属于 archeology 域，抽到本地只是换条路径的复制。

| 谓词 | value_type | 条数 | epistemic_mode | 说明 |
|---|---|---|---|---|
| `typological_parallel` | json | 240 | attributed | 可比同类器；symmetric、defeasible。要求 `form_level` 以上证据 |
| `probable_original_context` | json | 132 | **hypothesized** | 原文谈的是类别，套到个体上是推断。要求 `form_head_level` 证据 |
| `dating_corroboration` | json | 130 | attributed | **`stance` 是计算值**（`supports`/`questions`/`partial_overlap`/`undetermined`），由 `period_intervals.json` 与引用中解析出的年份做区间比对得出，不是 LLM 判断；原判断留在 `llm_stance`。允许 `class_level` 证据——断代是类属性 |
| `has_research_gap` | json | 892 | inferred | 三种 `reason`：`insufficient_evidence` / `rejected_by_gate`（带 `gate`）/ `no_on_topic_candidates`。**混为一谈会掩盖『证据讲错了东西』这一类** |

`evidence_scope` 三级：`form_head_level`（形制中心词命中，功能性断言唯一可用）>
`form_level`（其他形制词）> `class_level`（仅类别/材质/年代）。

~~已知缺陷：`stance` 全是 `supports`~~ —— **已修**，改为区间比对计算值：
`undetermined` 104 / `supports` 18 / `partial_overlap` 7 / `questions` 1。
见 layered-ontology.md §4.7。

## 6. L3 谓词（1 个）

| 谓词 | value_type | 条数 | 说明 |
|---|---|---|---|
| `has_exhibit_prose` | string | 464 | **functional**。展品描述段。`status=proposed`、`reviewed=false`、`extraction_text=false` |

它是**文本投影产物，不是语义断言**——值是文本块，不参与抽取，因此不会在本地制造一份
可查询的远端知识副本。`derived_from` 列出转述的 statement id。

必需 value 键：`text` / `derived_from` / `char_count` / `prose_version`。

## 7. qualifier 键

| 键 | 条数 | 取值 |
|---|---|---|
| `epistemic_mode` | 9363 | `observed` / `inferred` / `attributed` / `hypothesized` |
| `basis` | 9363 | `registry` / `registry_completeness_check` / `remote_exact_concept_name_match` / `reviewed_mapping` / `reviewed_homograph_veto` / `reviewed_wiki_document_anchor` / `remote_wiki_title_match` / `alignment_pass` |
| `registry_field` | 9301 | 登记字段名，或 `(derived)` |
| `parse_status` | 811 | `range_parsed` / `label_only` / `unparsed_free_text` |
| `unit_source` | 537 | `registry_column` / `unspecified` / `missing` |
| `resolved_at` | 62 | ISO 时间戳（L1）|
| `review_status` | 26 | `auto_unreviewed` / `machine_reviewed_pending_curator` / `reviewed_document_only` / `blocked_pending_review` |
| `match_kind` | 24 | `concept_cluster` / `wiki_page` |
| `match_relation` | 23 | `exact` / `broader` / `narrower` / `close` |
| `remote_cluster_size` | 23 | `{"size": N}` |

L2 新增（已在用）：`defeasible` / `slot` / `retrieval_run`。
L3 新增（已在用）：`extraction_text` / `reviewed` / `prose_version` / `derived_from`。
L0 新增（已在用）：`label_normalization` / `registry_era_label`。

---

## 8. reference 属性

| 属性 | 条数 | 指向 |
|---|---|---|
| `wwybsj.ref.registry` | 9301 | 本地 `wwybsj.artifacts` 流的登记事件。**每条 L0 statement 都有，缺失数 0** |
| `wwybsj.ref.remote_concept` | 24 | 远端概念簇。`concept_ids` + `primary_concept_id` + `canonical_name` |

`wwybsj.ref.remote_passage`（502 条）——L2 的远端原文段落，带 `stream_id`/`event_id`/
`source_span`。L3 无 reference：它的出处是 `derived_from` 指向的本地断言。

远端 id 在本地库**没有对应行，这是故意的**：它们是回远端解析的句柄，不是本地外键。

---

## 9. 词项清单（56 个）

`uses` = 引用它的 statement 数。

### category（10，全部有远端通路）

| 词项 | uses | 对齐状态 | 锚点 |
|---|---|---|---|
| `玉石器、宝石` | 229 | aligned_by_components | 玉石器[exact] + 宝石[exact] |
| `石器、石刻、砖瓦` | 51 | aligned_by_components | 石器[exact] + 石刻[exact] + 砖瓦[exact] |
| `铜器` | 44 | aligned | 铜器[exact] + 青铜器[narrower] |
| `陶器` | 40 | aligned | 陶器[exact] |
| `瓷器` | 36 | aligned | 瓷器[exact] + 陶瓷器[broader] |
| `铁器、其他金属器` | 26 | aligned_by_components | 铁器[exact] |
| `雕塑、造像` | 21 | aligned_by_components | 雕塑[exact] + 造像[exact] |
| `金银器` | 11 | aligned | 金银器[exact] |
| `钱币` | 6 | aligned | 钱币[exact] |
| `漆器` | 1 | aligned | 漆器[exact] |

### material（10，7 个有锚点）

| 词项 | uses | 对齐状态 | 锚点 / 原因 |
|---|---|---|---|
| `宝玉石` | 230 | leave_unaligned | 远端 `limit=200` 搜索返回 0 条，确实不存在；对齐到器物类 `玉石器` 是类型错误 |
| `陶` | 58 | aligned | 陶[exact] |
| `铜` | 50 | aligned | 铜[exact]，簇内排除 `b319e504`（`甜饼 -consists_of-> 铜`）|
| `砖瓦` | 48 | aligned | 砖瓦[exact] |
| `瓷` | 36 | aligned_by_components | 陶瓷器[broader] + wiki 文档锚点（页面是真实材料学）|
| `铁` | 22 | aligned | 铁[exact] |
| `金` | 13 | aligned_by_components | **同形词否决**（4 个同名概念全是金朝）→ 金属[broader] |
| `其他金属` | 5 | aligned_by_components | 金属[broader]（兜底值的语义上界）|
| `石` | 4 | unaligned | **同形词否决**（容量单位「石」=十斗）；类别 `石器` 已有通路 |
| `其他无机质` | 1 | not_applicable | 登记兜底值，不指称任何概念 |

### period（20，全部有锚点）

登记簿 31 种写法归并而来。**东北亚三政权是优质锚点**（本馆核心 82 件）：

```
高句丽 39 件  -is_a-> 东北古民族一支 · -related_to-> 历代中原王朝 · -introduced_to-> 儒教
渤海   25 件  -instance_of-> 地方国家政权 · -influenced_by-> 唐 · 肃慎系 -consists_of-> 渤海
新罗   18 件  -influenced_by-> 唐代/唐音乐 · -uses_method-> 中国章服之制 · -introduced_to-> 倭
```

**中原朝代的单字写法在远端是系统性垃圾**——`唐` 的 5 个同名概念是先周古国唐
（`changed_into 晋`）、爵邑（`defined_as 所封之爵邑`）、河北唐县、以及一条带
`10.2 °C` 的气候数据；`元` 唯一那个是经纬度 `127°44′ W`；`宋` 两个都是古文字里的氏族；
`清`/`明`/`汉`/`商`/`新石器` 零同名概念。

所以改用**长写法**作 `close` 映射，实测质量截然不同：

| 词项 | 锚点 | 关系 |
|---|---|---|
| `唐` 58 件 | `唐朝`×15 | close（`-consists_of-> 十道/十五道`）|
| `战国` 54 件 | `战国` exact + `战国时期`×32 | exact + close |
| `宋` 40 件 | `宋代`×12 | close |
| `清` 37 件 | `清代`×8 | close（`-has_feature-> 考据学获得极大发展`）|
| `商` 22 件 | `商代`×20 | close |
| `明` 17 件 | `明朝`×14 | close |
| `金` 13 件 | `金` exact + `金朝`×15 | exact + close |
| `汉` 5 件 | `汉代`×10 | close（`-influenced_by-> 秦文化和楚文化`）|
| `元` 1 件 | `元代`×6 | close |
| `新石器` 1 件 | `新石器时代`×15 | close |
| `西汉`/`东汉`/`西周`/`东周`/`南宋`/`北魏`/`东魏` | 各自 exact | 长写法本身即通行 |

**同形词否决是分 facet 的**：`金` 在 material facet 被否决（那些概念指金朝，不是金属），
在 period facet 反而正确。

`渤海` 排除了 3 个成员：`88ddb850`（渤海**海**——`渤海海面封冻 associated_with`）、
`2ee48828`（渤海**郡**——`part_of 辽国`）、`ab0e4780`（无事实）。但
`渤海海面封冻 -associated_with-> 渤海` 仍会在解引用时出现，因为它挂在**被保留的**
`3f88ffe8` 上——**远端图自身的错边，只能在投影层按谓词白名单拦**。

### grade / acquisition / completeness（16，全部 not_applicable）

藏品管理词汇，不是考古概念，**不尝试对齐**。共覆盖 1396 条 statement。

```
grade         三级 197 · 一般 140 · 二级 71 · 未定级 46 · 一级 11
acquisition   发掘 166 · 征集购买 91 · 旧藏 86 · 采集 56 · 拨交 46 · 接受捐赠 15 · 移交 5
completeness  残缺 282 · 基本完整 119 · 完整 59 · 严重残缺(含缺失部件) 5
```

去查会怎样的活教材：远端 `一般` 页面 = `Defined As [[艺术的和知识的活动]]`
flags=`['invalid_supporting_signal_id']`；`完整` 页面 =
`Has Property [[较完整的国体（the Shan state）]]`。
