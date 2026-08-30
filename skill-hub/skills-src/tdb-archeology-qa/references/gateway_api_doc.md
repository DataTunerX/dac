# TDB Gateway API 接口文档

本文档基于当前代码实现整理，来源主要为：

- `/Users/ningwu/eis/tdb/gateway/src/app.ts`
- `/Users/ningwu/eis/tdb/gateway/src/api/v2/*.routes.ts`
- `/Users/ningwu/eis/tdb/gateway/src/schema/v2/*.ts`

## 总览

- 根级接口：1 个
- `/v2` 命名空间接口：106 个
- 合计：107 个

说明：

- `GET /health` 和 `GET /v2/health` 都存在，返回相同的服务健康信息。
- 一部分“frontend”类接口目前保留了 schema，但实现中会直接返回 `DB_NOT_CONFIGURED`。
- `GET /v2/health/db` 目前也不会做真实 DB 探活，而是直接返回错误。

## 统一约定

- 服务根健康检查：`GET /health`
- 业务接口统一前缀：`/v2`
- 常见错误返回：
  - `400 BAD_REQUEST`：请求参数不合法
  - `500 INTERNAL_ERROR`：服务内部错误
  - 业务错误统一为 `{ error: { code, message, details? } }`

### 设计边界：Gateway 与 Agent

这一点对问答与检索特别重要：

- **gateway 不使用 LLM**。它只负责确定性的读写、检索、图遍历、溯源拼装、HTTP ↔ backend 转换。
- **agent 才负责问题理解与多步搜证策略**。例如：
  - 识别问题是在问定义、枚举、因果、对比还是阶段划分
  - 判断当前证据是否足够回答
  - 决定下一步该扩 wiki、ontology、还是 reverse provenance
- 因此，gateway 中新增的 evidence 类接口，目标是为 agent 提供**可验证、可组合的原子能力**，而不是在 gateway 内部“直接把题答出来”。

当前已经实现但要正确理解定位的接口包括：

- `GET /v2/ontology/fact/provenance`
- `GET /v2/wiki/page/evidence`
- `GET /v2/ontology/concept/evidence`
- `POST /v2/qa/evidence-pack`

其中 `POST /v2/qa/evidence-pack` 当前更适合做**调试与观察性辅助接口**，用于快速查看“从问题文本出发能召回哪些局部证据”，**不应被视为最终问答 agent**。

## 1. Health

| 方法 | 路径 | 说明 | 关键参数 | 返回 |
| --- | --- | --- | --- | --- |
| GET | `/health` | 根级健康检查 | 无 | `{ status, service, version }` |
| GET | `/v2/health` | v2 健康检查 | 无 | `{ status, service, version }` |
| GET | `/v2/health/db` | 数据库健康检查占位接口 | 无 | 当前实现直接报错 `DB_NOT_CONFIGURED` |

## 2. Frontend 聚合接口

这组接口 schema 完整，但当前 `frontend.routes.ts` 中统一走 `ensureService()`，会直接抛出 `DB_NOT_CONFIGURED`，因此现阶段属于“接口定义存在，但不可用”。

| 方法 | 路径 | 说明 | 关键参数 | 返回 |
| --- | --- | --- | --- | --- |
| POST | `/v2/context/pack` | 生成页面上下文包 | `user_id`, `role`, `page_type`, `object_ref?`, `selection?`, `goal?` | `contract_version`, `summary`, `current_state`, `ui_blocks`, `evidence` |
| POST | `/v2/object/360` | 生成对象 360 视图 | `object_ref`, `user_id?`, `role?`, `perspective?` | `object`, `summary`, `metrics`, `timeline`, `artifacts`, `decisions` |
| POST | `/v2/exception/feed` | 获取异常/待处理项列表 | `user_id`, `role`, `queue_context?`, `scope?`, `limit?` | `summary`, `total_open`, `items`, `recommended_actions` |
| POST | `/v2/decision/brief` | 生成审批/决策摘要 | `user_id`, `role`, `approval_ref`, `object_ref?`, `candidate_actions?` | `summary`, `recommendation`, `missing_prerequisites`, `impact_preview` |
| POST | `/v2/action/propose` | 推荐可执行动作 | `user_id`, `role`, `page_type`, `intent`, `object_ref?` | `summary`, `proposed_actions`, `missing_inputs`, `constraints` |
| POST | `/v2/action/simulate` | 模拟动作影响 | `user_id`, `role`, `action_key`, `object_ref?`, `args?` | `summary`, `simulation_status`, `selected_action`, `affected_objects`, `changes` |

## 3. Artifact

| 方法 | 路径 | 说明 | 关键参数 | 返回 |
| --- | --- | --- | --- | --- |
| POST | `/v2/artifact/create` | 创建 artifact | `artifact_type`, `name`, `description?` | Artifact 对象 |
| POST | `/v2/artifact/version/create` | 创建 artifact version | `artifact_id`, `version_number`, `status`, `valid_from`, `content_ref` 等 | ArtifactVersion 对象 |
| GET | `/v2/artifact/version/asof` | 查询某时刻有效版本 | `artifact_id`, `as_of_valid_time` | `{ artifact_version }` |

## 4. Entity

| 方法 | 路径 | 说明 | 关键参数 | 返回 |
| --- | --- | --- | --- | --- |
| POST | `/v2/entity/upsert` | 新增或更新实体 | `entity_id?`, `entity_type`, `display_name`, `external_refs?`, `status?` | Entity 对象 |
| GET | `/v2/entity/get` | 按 ID 获取实体 | `entity_id` | `{ entity }` |
| GET | `/v2/entity/list` | 实体列表/搜索 | `entity_type?`, `status?`, `q?`, `limit?`, `offset?` | `{ entities }` |

## 5. Ontology

### 5.1 Concept / Alias / Edge / Event Link

| 方法 | 路径 | 说明 | 关键参数 | 返回 |
| --- | --- | --- | --- | --- |
| POST | `/v2/ontology/concept/upsert` | 新增或更新概念 | `concept_id`, `canonical_name`, `concept_type`, `aliases?` | Concept |
| GET | `/v2/ontology/concept/get` | 查询概念 | `concept_id` | `{ concept }` |
| GET | `/v2/ontology/concept/evidence` | 查询某个概念相关的已接受 fact 及其 provenance | `concept_id`, `fact_limit?`, `evidence_limit?`, `stream_id?` | `{ concept, facts[] }` |
| GET | `/v2/ontology/concept/list` | 概念列表 | `concept_type?`, `q?`, `limit?`, `offset?` | `{ concepts }` |
| GET | `/v2/ontology/concept/search` | 搜索概念 | `q?`, `concept_type?`, `limit?`, `offset?` | `{ concepts }` |
| GET | `/v2/ontology/concept/neighbors` | 获取概念邻居 | `concept_id`, `direction`, `predicate?`, `limit?` | `{ neighbors }` |
| POST | `/v2/ontology/alias/upsert` | 新增或更新别名 | `concept_id`, `alias_text`, `confidence`, `extractor` | Alias |
| GET | `/v2/ontology/alias/list` | 别名列表 | `concept_id?`, `q?`, `limit?`, `offset?` | `{ aliases }` |
| GET | `/v2/ontology/alias/search` | 搜索别名 | `q?`, `concept_id?`, `limit?`, `offset?` | `{ aliases }` |
| POST | `/v2/ontology/edge/upsert` | 新增或更新概念边 | `src_concept_id`, `predicate`, `dst_concept_id`, `weight` | Edge |
| GET | `/v2/ontology/edge/list` | 查询概念边 | `src_concept_id?`, `predicate?`, `dst_concept_id?`, `limit?` | `{ edges }` |
| POST | `/v2/ontology/event-link/upsert` | 关联 event 与 concept | `stream_id`, `event_id`, `concept_id`, `role`, `confidence`, `extractor` 等 | EventConceptLink |
| GET | `/v2/ontology/event-link/list` | 查询 event-concept 关联 | `stream_id?`, `event_id?`, `concept_id?`, `role?`, `limit?` | `{ links }` |

### 5.2 Object Type / Relation Type

| 方法 | 路径 | 说明 | 关键参数 | 返回 |
| --- | --- | --- | --- | --- |
| POST | `/v2/ontology/object-type/upsert` | 新增或更新对象类型 | `type_id`, `display_name`, `description?`, `enabled?` | ObjectType |
| GET | `/v2/ontology/object-type/get` | 查询对象类型 | `type_id` | `{ object_type }` |
| GET | `/v2/ontology/object-type/list` | 对象类型列表 | `enabled_only?`, `q?`, `limit?`, `offset?` | `{ object_types }` |
| POST | `/v2/ontology/concept-type-assignment/upsert` | 给 concept 绑定对象类型归属 | `domain`, `concept_id`, `object_type_id`, `source_kind`, `assignment_status?`, `confidence?`, `metadata?` | ConceptTypeAssignment |
| GET | `/v2/ontology/concept-type-assignment/list` | 查询 concept-type assignment | `domain?`, `concept_id?`, `object_type_id?`, `assignment_status?`, `limit?`, `offset?` | `{ assignments }` |
| POST | `/v2/ontology/relation-type/upsert` | 新增或更新关系类型 | `predicate`, `src_type_id`, `dst_type_id`, `display_name` 等 | RelationType |
| GET | `/v2/ontology/relation-type/get` | 查询关系类型 | `predicate` | `{ relation_type }` |
| GET | `/v2/ontology/relation-type/list` | 关系类型列表 | `src_type_id?`, `dst_type_id?`, `enabled_only?`, `q?`, `limit?`, `offset?` | `{ relation_types }` |

### 5.3 Fact

| 方法 | 路径 | 说明 | 关键参数 | 返回 |
| --- | --- | --- | --- | --- |
| POST | `/v2/ontology/fact/upsert-with-evidence` | 写入 fact 及其证据 | `src_concept_id`, `predicate`, `dst_concept_id`, `confidence`, `extractor`, `status`, `evidence[]` | `{ fact, evidence_count }` |
| GET | `/v2/ontology/fact/get` | 查询单条 fact | `fact_id` | `{ fact }` |
| GET | `/v2/ontology/fact/list` | fact 列表 | `status?`, `stream_id?`, `stream_prefix?`, `predicate?`, `extractor?`, `limit?`, `offset?` | `{ facts }` |
| GET | `/v2/ontology/fact/search` | 搜索 fact | `q?`, `status?`, `stream_id?`, `stream_prefix?`, `predicate?`, `extractor?`, `src_concept_id?`, `dst_concept_id?` | `{ facts }` |
| POST | `/v2/ontology/fact/archive` | 归档 fact | `fact_id`, `reviewer`, `note` | `{ fact_id }` |

说明：`stream_id` 默认精确匹配；`stream_prefix=true` 时匹配命名流本身及其点号分隔的子流，例如 `kb.customer.bmw` 包含 `kb.customer.bmw.account.southafrica`，但不包含 `kb.customer.bmw2`。

### 5.4 Wikidata-style / Semantic Statement API

这一组接口是最近最容易被遗漏的一批改动。它们不是在 `ontology_fact` 上继续堆字段，而是开始显式暴露
Wikidata 风格的 statement / qualifier / reference 写入面。

可以这样理解：

- `semantic/upsert-batch` 是新写入的正式 statement-first 入口
- `ontology_fact` 仍然是当前兼容层、治理层和许多现有查询的主要入口，但不应再被新 pipeline 当作事实 source of truth
- `ontology_edge` 只应作为兼容图投影；不要把 edge upsert 当作可溯源 statement 的主写入路径
- 它对应的设计背景可参考：
  - `/Users/ningwu/eis/tdb/docs/ontology_layer_explained.md`
  - `/Users/ningwu/eis/tdb/docs/multilayer_dynamic_semantic_arch.md`

| 方法 | 路径 | 说明 | 关键参数 | 返回 |
| --- | --- | --- | --- | --- |
| POST | `/v2/ontology/semantic/upsert-batch` | 批量写入 semantic entity / statement / qualifier / reference | `entities[]`, `statements[]`, `qualifiers[]`, `references[]` | `{ semantic_entity_count, semantic_statement_count, statement_qualifier_count, statement_reference_count }` |

关键 payload 形状：

- `entities[]`
  - `entity_id`, `entity_kind`, `semantic_role`, `namespace`, `status`, `property_datatype?`, `metadata_json`
- `statements[]`
  - `statement_key`, `subject_id`, `property_id`, `value_type`, `value_entity_id?`, `value_json`, `status`, `confidence?`, `created_by`, `metadata_json`
- `qualifiers[]`
  - `statement_key`, `property_id`, `value_type`, `value_json`, `value_entity_id?`, `ordinal`
- `references[]`
  - `statement_key`, `property_id`, `value_type`, `value_json`, `evidence_id?`, `source_span?`, `ordinal`

这组接口对 API 使用方式的影响：

1. 现在 gateway 已经不只是“事实三元组 + qualifier_json”的接口集合，而是开始支持 statement-first 写入。
2. `reference` 不再只是一个 citation string，而是 property-value 结构，可挂 `evidence_id` / `source_span`。
3. 这意味着上层系统如果要表达更接近 Wikidata 的 statement 模型，不需要继续把结构塞回 `ontology_fact.qualifier` 或 artifact JSON。
4. 新 pipeline 写入必须把 relation evidence 转成 `references[]`；只写 `statements[]` 仍会得到 provenance 为空的裸 statement。
5. 迁移期内，调用方需要明确区分：
   - 想走新语义内核写入：用 `ontology/semantic/upsert-batch`
   - 想走兼容治理路径：用 `ontology/fact/*`
   - 想服务旧图遍历：从 statement 投影到 `ontology_edge`，而不是用 `ontology_edge` 作为权威写入入口

当前 `run_pipeline.py` 对 relation candidate 的默认写入已经走
`load_relation_statements_to_tdb.py`，该脚本调用 `ontology/semantic/upsert-batch`
并写入 `references[]`。旧 `promote_relation_candidates.py` / `ontology_edge`
投影只在显式传 `--legacy-edge-projection` 时启用。

当前 caveat：

- `/v2/ontology/edge/upsert` 会为兼容层双写 semantic statement，但 edge payload 不携带
  Wikidata-style reference 信息，因此这类 `created_by=legacy_ontology_edge` statement 可能返回
  `statement/provenance.references=[]`。
- 这类 statement 可用于导航和召回；在没有 `statement_reference` 回填前，不应作为
  “逐条溯源到书/章/页/句”的强证据。

### 5.5 Term Mapping / Normalized Term / Raw Term

这组接口对应 `ontology layer` 之外但又紧挨 ontology 的“query interpretation / term normalization”层。
它们不是传统 ontology concept CRUD，而是把“原词如何解释、如何归一、如何映射到 concept / slot / JSON target”显式建模。

| 方法 | 路径 | 说明 | 关键参数 | 返回 |
| --- | --- | --- | --- | --- |
| POST | `/v2/ontology/term-mapping/registry/upsert` | 新增或更新 term mapping registry | `domain`, `registry_name`, `version_label`, `status`, `description?`, `owner?`, `metadata?` | TermMappingRegistry |
| GET | `/v2/ontology/term-mapping/registry/get` | 查询 registry | `registry_id` | `{ registry }` |
| GET | `/v2/ontology/term-mapping/registry/list` | 列出 registry | `domain?`, `status?`, `q?`, `limit?`, `offset?` | `{ registries }` |
| POST | `/v2/ontology/term-mapping/rule/upsert` | 新增或更新 term mapping rule | `registry_id`, `raw_term`, `term_type`, `normalization_status` 等 | TermMappingRule |
| GET | `/v2/ontology/term-mapping/rule/get` | 查询 rule | `rule_id` | `{ rule }` |
| GET | `/v2/ontology/term-mapping/rule/search` | 搜索 rule | `registry_id?`, `raw_term?`, `q?`, `language?`, `term_type?`, `semantic_slot?`, `review_status?`, `ambiguity_only?` | `{ rules }` |
| POST | `/v2/ontology/term-mapping/rule-evidence/upsert` | 给 rule 挂证据 | `rule_id`, `artifact_id?`, `artifact_version_id?`, `event_id?`, `memory_decision_id?`, `source_span?`, `note?`, `confidence?`, `evidence?` | TermMappingRuleEvidence |
| GET | `/v2/ontology/term-mapping/rule-evidence/list` | 查询 rule evidence | `rule_id?`, `limit?`, `offset?` | `{ evidence }` |
| GET | `/v2/ontology/term-mapping/interpret` | 在线解释单个 term | query 参数见 schema | `{ interpretation }` |
| POST | `/v2/ontology/term-mapping/interpret-batch` | 批量解释 term | body 参数见 schema | `{ interpretations }` |
| POST | `/v2/ontology/normalized-term/upsert` | 新增或更新 normalized term | term fields | NormalizedTerm |
| GET | `/v2/ontology/normalized-term/get` | 查询 normalized term | key fields | `{ normalized_term }` |
| GET | `/v2/ontology/normalized-term/search` | 搜索 normalized term | `q?`, `domain?`, `limit?`, `offset?` | `{ normalized_terms }` |
| POST | `/v2/ontology/normalized-term/cluster/upsert` | 新增或更新 term cluster | cluster fields | TermCluster |
| GET | `/v2/ontology/normalized-term/cluster/get` | 查询 cluster | cluster key | `{ cluster }` |
| GET | `/v2/ontology/normalized-term/cluster/list` | 列出 cluster | filters | `{ clusters }` |
| POST | `/v2/ontology/normalized-term/cluster-member/upsert` | 新增或更新 cluster member | member fields | ClusterMember |
| GET | `/v2/ontology/normalized-term/cluster-member/list` | 查询 cluster member | filters | `{ members }` |
| POST | `/v2/ontology/raw-term/upsert` | 新增或更新 raw term | raw term fields | RawTerm |
| GET | `/v2/ontology/raw-term/get` | 查询 raw term | raw term key | `{ raw_term }` |
| GET | `/v2/ontology/raw-term/search` | 搜索 raw term | filters | `{ raw_terms }` |
| POST | `/v2/ontology/raw-term/candidate/upsert` | 新增或更新 raw term candidate | candidate fields | RawTermCandidate |
| GET | `/v2/ontology/raw-term/candidate/list` | 查询 raw term candidate | filters | `{ candidates }` |
| POST | `/v2/ontology/normalized-term/raw-term-mapping/upsert` | 写入 normalized-term 与 raw-term 的映射 | mapping fields | RawTermNormalization |
| GET | `/v2/ontology/normalized-term/raw-term-mapping/list` | 查询映射 | filters | `{ mappings }` |
| POST | `/v2/ontology/relation-candidate/upsert` | 写入 relation candidate | candidate fields | RelationCandidate |
| GET | `/v2/ontology/relation-candidate/list` | 查询 relation candidate | filters | `{ relation_candidates }` |

对 API 设计理解的影响：

1. 现在的 ontology API 已经不是只有 “concept / relation / fact” 三层，而是出现了明显的四层：
   - concept / type / fact
   - semantic statement write path
   - term mapping registry
   - raw / normalized / cluster / candidate
2. 这批接口是 query understanding、normalization、registry governance 的主入口，不应再被误解为只是“ontology alias 的附属表”。
3. 如果上层 agent / pipeline 在做术语解释、compound term 拆分、ambiguity 管理，应该优先考虑这组接口，而不是继续往 concept alias 或 fact qualifier 里塞过程性信息。

## 6. Governance

### 6.1 Rule / Authority / Override

| 方法 | 路径 | 说明 | 关键参数 | 返回 |
| --- | --- | --- | --- | --- |
| POST | `/v2/rule/upsert` | 新增或更新规则 | `rule_key`, `rule_version`, `severity`, `expression`, `effective_from` | Rule |
| POST | `/v2/authority/grant` | 授权某主体执行动作 | `grantee_id`, `action_type`, `scope?`, `valid_from`, `valid_to?` | AuthorityGrant |
| POST | `/v2/rule/override` | 创建规则覆盖 | `rule_key`, `rule_version`, `authority_grant_id`, `valid_from`, `case_id?`, `event_id?` | RuleOverride |
| GET | `/v2/authority/check` | 检查主体是否有权限 | `grantee_id`, `action_type`, `scope?`, `as_of_valid_time`, `as_of_system_time?` | `{ allowed, authority_grant }` |
| GET | `/v2/rule/override/asof` | 查询某时刻生效的 override | `rule_key`, `rule_version?`, `as_of_valid_time`, `as_of_system_time?` | `{ overrides }` |

### 6.2 Ontology Fact Review / Provenance

| 方法 | 路径 | 说明 | 关键参数 | 返回 |
| --- | --- | --- | --- | --- |
| POST | `/v2/ontology/fact/review` | 审核单条 fact | `fact_id`, `decision`, `reviewer?`, `note?` | 审核结果 |
| GET | `/v2/ontology/fact/history` | 查看 fact 历史 | `fact_id`, `evidence_limit?`, `stream_id?` | `fact`, `reviews`, `evidence`, `evidence_count` |
| GET | `/v2/ontology/fact/provenance` | 查看 fact 溯源 | `fact_id`, `evidence_limit?`, `stream_id?` | history + `linked_cases`, `linked_alerts` |
| POST | `/v2/ontology/fact/review/bulk` | 批量审核 fact | `decision`, `status?`, `stream_id?`, `predicate?`, `limit?`, `dry_run?` 等 | 批量审核结果 |

补充说明：

- `GET /v2/ontology/fact/provenance` 现在会在返回的 `evidence[]` 中尽量补充 `sentence`：
  - 优先使用证据里已有的 `sent_index`
  - 若旧数据缺少 `sent_index`，会在同一 `event_id` 的句子窗口里做 deterministic fallback
- 但如果底层 event sentence 本身就是整段甚至整章文本，gateway 只能返回那段原始 sentence，无法在不引入 LLM 的前提下进一步“理解式切句”。
- 调用层最近需要特别注意：
  - `fact_id >= 1` 的 fact 才能稳定走 provenance
  - legacy 路径如果落到 `fact_id = 0`，通常不能把它当作强 provenance-bearing relation
  - provenance 成功返回也不等于证据一定高质量，仍要区分：
    - usable evidence
    - weak fallback
    - mismatched local sentence

### 6.3 Ontology Case

| 方法 | 路径 | 说明 | 关键参数 | 返回 |
| --- | --- | --- | --- | --- |
| POST | `/v2/ontology/case/open` | 创建 case | `stream_id`, `title`, `description?`, `priority?`, `owner?`, `fact_ids?` | case 创建结果 |
| GET | `/v2/ontology/case/list` | case 列表 | `stream_id?`, `status?`, `limit?` | case 列表 |
| GET | `/v2/ontology/case/detail` | case 详情 | `case_id`, `evidence_limit?` 等 | case 明细 |
| GET | `/v2/ontology/case/explain` | case 解释/摘要 | `case_id`, `evidence_limit?` 等 | case explain |
| POST | `/v2/ontology/case/update` | 更新 case 状态/负责人等 | `case_id` + 更新字段 | 更新结果 |

### 6.4 Ontology Alert

| 方法 | 路径 | 说明 | 关键参数 | 返回 |
| --- | --- | --- | --- | --- |
| POST | `/v2/ontology/alert/open` | 创建 alert | `stream_id`, `severity`, `message`, `case_id?`, `rule_key?` 等 | alert 创建结果 |
| GET | `/v2/ontology/alert/list` | alert 列表 | `stream_id?`, `status?`, `severity?`, `limit?` 等 | alert 列表 |
| GET | `/v2/ontology/alert/explain` | alert 解释 | `alert_id` | alert explain |
| POST | `/v2/ontology/alert/update` | 更新 alert | `alert_id` + 更新字段 | 更新结果 |

### 6.5 Ontology Ops

| 方法 | 路径 | 说明 | 关键参数 | 返回 |
| --- | --- | --- | --- | --- |
| GET | `/v2/ontology/ops/config` | 查看规则运行配置 | `rule_name?` 等 | config 列表 |
| POST | `/v2/ontology/ops/config/upsert` | 更新规则运行配置 | `rule_name`, 配置字段 | upsert 结果 |
| POST | `/v2/ontology/ops/rules/run` | 触发规则运行 | 运行参数 | run 结果 |
| GET | `/v2/ontology/ops/runs` | 查看运行记录 | `rule_name?`, `limit?` 等 | run 列表 |
| GET | `/v2/ontology/ops/run/explain` | 查看某次运行明细 | `run_id` | run explain |

## 7. Decision

| 方法 | 路径 | 说明 | 关键参数 | 返回 |
| --- | --- | --- | --- | --- |
| POST | `/v2/decision/create` | 创建决策记录 | `case_id`, `event_seq`, `projection_version`, `chosen_action`, `detail?` 等 | Decision |
| POST | `/v2/decision/evidence/attach` | 给决策附证据 | `decision_id`, `artifact_version_id`, `citation?` | DecisionEvidence |
| GET | `/v2/decision/get` | 获取决策 | `case_id`, `event_seq`, `projection_version` | `{ decision, evidence }` |
| GET | `/v2/decision/trace` | 获取决策全链路 | 同上 | `decision`, `evidence`, `event`, `snapshot_anchor`, `artifact_versions`, `explanation` |
| GET | `/v2/decision/explain` | 获取决策解释 | 同上 | 与 `trace` 相同结构 |

## 8. QA / Evidence Assist

| 方法 | 路径 | 说明 | 关键参数 | 返回 |
| --- | --- | --- | --- | --- |
| POST | `/v2/qa/evidence-pack` | 从问题文本出发，组装一个小型局部证据包 | `question`, `domain`, `stream_id?`, `wiki_limit?`, `concept_limit?`, `fact_limit?`, `evidence_limit?` | `{ question, domain, query_variants, wiki_hits, concept_hits, fact_hits }` |

补充说明：

- 这是一个**辅助接口**，不是最终问答接口。
- 它目前会：
  - 从问题文本中生成若干 query variants
  - 命中 wiki page / ontology concept
  - 读取这些命中对象周围的已接受 fact 及 provenance
  - 按轻量 anchor 规则做排序
- 它**不会**：
  - 理解复杂问句的完整语义
  - 做多轮搜证
  - 判断“证据是否足够回答”
  - 代替上层 agent 做问题分解

推荐用途：

- 调试某题从 TDB 当前状态能召回什么
- 快速检查某个问题的 anchor 命中是否偏了
- 帮助观察 gap fill / ontology / wiki 是否已经产出可用局部证据

不推荐用途：

- 把它当作最终 QA pipeline 的唯一输入
- 期待它单次调用就稳定覆盖多跳、多阶段、上下文依赖问题

## 9. Wiki

| 方法 | 路径 | 说明 | 关键参数 | 返回 |
| --- | --- | --- | --- | --- |
| POST | `/v2/wiki/page` | 创建或更新 wiki 页面 | `domain`, `slug`, `title`, `content`, `page_type` 等 | page upsert 结果 |
| GET | `/v2/wiki/page` | 获取单个 wiki 页面 | `domain`, `slug` | `{ page }` |
| GET | `/v2/wiki/page/evidence` | 获取某个 wiki 页关联的已接受 fact 与 provenance | `domain`, `slug`, `fact_limit?`, `evidence_limit?`, `stream_id?` | `{ page, facts[] }` |
| GET | `/v2/wiki/search` | 搜索 wiki 页面 | `domain`, `q`, `page_type?`, `knowledge_level?`, `authority_kind?`, `limit?` | `{ results }` |
| GET | `/v2/wiki/index` | 获取 wiki index 页面 | `domain` | `{ index_content }` |
| GET | `/v2/wiki/pages` | 列出 wiki 页面 | `domain`, `page_type?`, `knowledge_level?`, `authority_kind?` | `{ pages }` |
| POST | `/v2/wiki/link` | 写入 wiki 页间链接 | `domain`, `from_slug`, `to_slug`, `link_text?` | link upsert 结果 |
| POST | `/v2/wiki/log` | 追加 wiki 操作日志 | `domain`, `action_type`, `summary?` 等 | log |
| GET | `/v2/wiki/log` | 查询 wiki 日志 | `domain`, `limit?` | `{ logs }` |
| GET | `/v2/wiki/lint` | 运行 wiki lint | `domain` | `{ issues }` |
| POST | `/v2/wiki/export` | 导出 wiki markdown | `domain`, `output_dir` | export 结果 |
| POST | `/v2/wiki/reinforce` | 强化页面置信度 | `page_id`, `delta_confidence?` | `{ page }` |

补充说明：

- `GET /v2/wiki/page/evidence` 是 page 级证据观察接口。
- 它当前通过 page title 去匹配 ontology fact 两端标签，再回查 fact provenance。
- 这适合做 page grounding / 调试，但不等于“这个 page 就足够回答问题”。
- 参数上要注意：
  - 它要求 `domain + slug`
  - 不是 `page_id`
  - 如果 page 只连到 legacy `fact_id = 0` 或根本没有关联 facts，返回可能为空或直接失败，这时 page 仍可作为导航入口，但不能当作强证据页。

## 10. Memory

| 方法 | 路径 | 说明 | 关键参数 | 返回 |
| --- | --- | --- | --- | --- |
| POST | `/v2/memory/decision/record` | 记录决策记忆 | `topic_id`, `decision`, `rationale`, `source_evidence[]` 等 | 记录结果 |
| POST | `/v2/memory/episode/summary/record` | 记录 episode 总结 | `topic_id`, `summary`, `source_evidence[]` 等 | 记录结果 |
| POST | `/v2/memory/answer/artifact/record` | 记录答案工件 | `domain_id`, `intent`, `normalized_question`, `answer_text`, `freshness_policy`, `validation_contract` 等 | answer artifact |
| POST | `/v2/memory/answer/artifact/recall` | 召回答案工件 | `domain_id`, `intent`, `question_fingerprint`, `entity_ids?`, `limit?` | recall 结果 |
| POST | `/v2/memory/answer/validation/record` | 记录答案校验结果 | `answer_artifact_id`, `check_spec`, `observed_values`, `pass` 等 | validation 结果 |
| POST | `/v2/memory/entity/state/get` | 获取实体状态记忆 | `entity_id?` 或 `entity_ref?`, `include?`, `as_of?` | entity state |
| POST | `/v2/memory/relation/record` | 记录实体关系 | `source_entity_id?`, `target_entity_id?`, `predicate`, `valid_from` 等 | relation 结果 |
| POST | `/v2/memory/relation/get` | 获取实体关系 | `source_entity_id?`, `predicate?`, `as_of_valid_time` | relation 列表 |
| POST | `/v2/memory/entity/state/upsert` | 更新实体 durable state | `entity_id?`, `entity_ref?`, `durable_state` | upsert 结果 |
| POST | `/v2/memory/task/context/get` | 获取任务上下文 | `topic_id`, `run_id?`, `include?`, `max_items?`, `as_of?` | task context |

## 11. Search

| 方法 | 路径 | 说明 | 关键参数 | 返回 |
| --- | --- | --- | --- | --- |
| POST | `/v2/search/query` | 统一检索接口 | `query`, `domain?`, `case_id?`, `stream_id?`, `stream_ids?`, `stream_prefix?`, `mode?`, `limit?`, `query_embedding?`, `alpha?` | `{ query, resolved_stream_ids, hits[] }` |
| POST | `/v2/search/domain-stream/bind` | 注册一个 domain 到 stream 的绑定 | `domain`, `stream_id`, `binding_kind?`, `source?`, `status?`, `priority?` | binding 记录 |
| POST | `/v2/search/domain-stream/unbind` | 将一个 domain-stream 绑定置为 inactive | 同 bind | binding 记录 |
| GET | `/v2/search/domain-stream/list` | 查看 domain-stream 绑定 | `domain?`, `stream_id?`, `status?`, `limit?` | `{ bindings[] }` |

说明：

- `mode` 支持 `lexical`、`vector`、`hybrid`
- `domain` 是一个比 `stream_id` 更高一层的检索作用域。当前设计中：
  - `wiki` 天然按 `domain` 组织
  - `search/query` 仍然真正执行在 `stream_id` 上
  - 因此需要 `domain -> stream_ids` 绑定表来把二者接起来
- 当请求只带 `domain`、不带 `stream_id/stream_ids` 时，gateway 会先解析这个 domain 下所有 active 的 stream 绑定，再把这些流喂给搜索后端。
- 当请求同时带 `domain` 和 `stream_id/stream_ids` 时，gateway 会校验这些 stream 是否都属于该 domain；不属于则直接报错，而不是静默跨域检索。
- `stream_id` / `stream_ids` 默认精确匹配；`stream_prefix=true` 时匹配命名流本身及其点号分隔的子流。
- `resolved_stream_ids` 表示这次搜索最终实际使用的 stream 范围，便于 agent 和人工调试确认“这个 domain 最后到底落到了哪些流上”。
- 每条命中包含 `doc_id`, `case_id`, `stream_id`, `event_id`, `event_seq`, `content`, `lexical_score`, `vector_score`, `hybrid_score`

## 12. Plan

| 方法 | 路径 | 说明 | 关键参数 | 返回 |
| --- | --- | --- | --- | --- |
| POST | `/v2/plan/validate` | 校验 query plan | `version=tdb.queryplan.v2`, `execution_mode?`, `goal?`, `context?`, `steps[]` | 校验结果、诊断信息 |
| POST | `/v2/plan/explain` | 解释 query plan | 同 `validate` | 校验结果 + `plan_id`, `goal` |
| POST | `/v2/plan/dry-run` | 干跑执行 plan | 同 `validate` | dry-run 结果、诊断信息 |
| POST | `/v2/plan/execute` | 执行 plan | 同 `validate` | 执行结果、step results、vars |
| POST | `/v2/plan/replay` | 重放 plan 请求 | 同 `validate` | replay 结果、trace |
| GET | `/v2/plan/run/get` | 查询单次 plan run | `plan_id` | `run`, `request`, `response`, `trace` |
| GET | `/v2/plan/run/list` | 查询 plan run 列表 | `execution_kind?`, `success?`, `goal_q?`, `replay_of_plan_id?`, `limit?` | run 列表 |
| POST | `/v2/plan/replay/by-id` | 按历史 plan_id 重放 | `plan_id` | replay 结果、trace |

## 13. Snapshot

| 方法 | 路径 | 说明 | 关键参数 | 返回 |
| --- | --- | --- | --- | --- |
| POST | `/v2/snapshot/write` | 写入快照 | `case_id`, `event_seq`, `projection_version`, `state_blob`, `state_hash?` | Snapshot |
| GET | `/v2/snapshot/latest` | 获取最新可用快照 | `case_id`, `projection_version`, `target_seq` | `{ snapshot }` |

## 14. Event

| 方法 | 路径 | 说明 | 关键参数 | 返回 |
| --- | --- | --- | --- | --- |
| POST | `/v2/event/append` | 追加事件 | `case_id?`, `stream_id?`, `event_type`, `payload?`, `event_text?`, `embedding?`, `valid_time` | `{ event_id, event_seq, system_time }` |
| GET | `/v2/event/read` | 读取事件流 | `case_id`, `from_seq?`, `to_seq?`, `limit?` | `{ events }` |
| GET | `/v2/event/sentences` | 读取某个 stream 的句子切分结果 | `stream_id`, `event_id?`, `limit?` | `{ sentences }` |

## 15. State

### 13.1 Property

| 方法 | 路径 | 说明 | 关键参数 | 返回 |
| --- | --- | --- | --- | --- |
| POST | `/v2/state/property/upsert` | 写入对象属性状态 | `object_id`, `key`, `value`, `valid_from`, `source_event_id?`, `confidence?` | PropertyRecord |
| GET | `/v2/state/property/asof` | 查询某时刻属性值 | `object_id`, `key`, `as_of_valid_time`, `as_of_system_time?` | `{ property }` |
| GET | `/v2/state/property/diff` | 比较两个时刻属性差异 | `object_id`, `key`, `from_valid_time`, `to_valid_time` 等 | diff 结果 |
| GET | `/v2/state/property/why` | 解释为何选中某条属性记录 | `object_id`, `key`, `as_of_valid_time`, `candidate_limit?` | selected + explanation + candidates |

### 13.2 Edge

| 方法 | 路径 | 说明 | 关键参数 | 返回 |
| --- | --- | --- | --- | --- |
| POST | `/v2/state/edge/upsert` | 写入对象关系边 | `src_id`, `predicate`, `dst_id`, `valid_from`, `source_event_id?`, `confidence?` | EdgeRecord |
| GET | `/v2/state/edge/asof` | 查询某时刻边集合 | `src_id`, `predicate?`, `as_of_valid_time`, `as_of_system_time?` | `{ edges }` |
| GET | `/v2/state/edge/diff` | 比较两个时刻边差异 | `src_id`, `predicate?`, `from_valid_time`, `to_valid_time` 等 | diff 结果 |

## 16. Ingest

所有 ingest 接口都以批量导入为目标，统一包含：

- `stream_id`
- `ingest_run_id?`
- `dry_run?`
- `items[]`

通用返回通常包含：

- `ingest_run_id`
- `stream_id`
- `accepted`
- `rejected`
- `errors[]`
- `ref_state_delta`

| 方法 | 路径 | 说明 | 关键参数 | 返回 |
| --- | --- | --- | --- | --- |
| POST | `/v2/ingest/entities` | 批量导入实体 | `items[].entity_type`, `display_name`, `entity_ref?`, `entity_id?` | entities ingest 结果 |
| POST | `/v2/ingest/artifacts` | 批量导入 artifact 及版本 | `items[].artifact`, `items[].versions[]`, `artifact_ref?` | artifacts ingest 结果 |
| POST | `/v2/ingest/events` | 批量导入事件 | `items[].event_ref?`, `case_id?`, `actor_ref?`, `payload?`, `valid_time?` 等 | events ingest 结果 |
| POST | `/v2/ingest/text` | 批量把文本导入为事件 | `generate_embedding?`, `event_type?`, `items[].text`, `items[].payload?` | text ingest 结果 |
| POST | `/v2/ingest/bundle` | 一次性导入多类对象 | `entities?`, `artifacts?`, `events?`, `properties?`, `edges?`, `defaults?` | 各 phase 汇总结果 |
| POST | `/v2/ingest/property` | 批量导入属性状态 | `items[].object_id?`, `object_ref?`, `key`, `value`, `valid_from` | property ingest 结果 |
| POST | `/v2/ingest/edge` | 批量导入关系边 | `items[].src_id?`, `src_ref?`, `predicate`, `dst_id?`, `dst_ref?`, `valid_from` | edge ingest 结果 |

## 源码索引

路由注册：

- `/Users/ningwu/eis/tdb/gateway/src/app.ts`
- `/Users/ningwu/eis/tdb/gateway/src/api/v2/index.ts`

按模块定义：

- `/Users/ningwu/eis/tdb/gateway/src/api/v2/health.routes.ts`
- `/Users/ningwu/eis/tdb/gateway/src/api/v2/frontend.routes.ts`
- `/Users/ningwu/eis/tdb/gateway/src/api/v2/artifact.routes.ts`
- `/Users/ningwu/eis/tdb/gateway/src/api/v2/entity.routes.ts`
- `/Users/ningwu/eis/tdb/gateway/src/api/v2/ontology.routes.ts`
- `/Users/ningwu/eis/tdb/gateway/src/api/v2/governance.routes.ts`
- `/Users/ningwu/eis/tdb/gateway/src/api/v2/decision.routes.ts`
- `/Users/ningwu/eis/tdb/gateway/src/api/v2/memory.routes.ts`
- `/Users/ningwu/eis/tdb/gateway/src/api/v2/search.routes.ts`
- `/Users/ningwu/eis/tdb/gateway/src/api/v2/plan.routes.ts`
- `/Users/ningwu/eis/tdb/gateway/src/api/v2/snapshot.routes.ts`
- `/Users/ningwu/eis/tdb/gateway/src/api/v2/event.routes.ts`
- `/Users/ningwu/eis/tdb/gateway/src/api/v2/state.routes.ts`
- `/Users/ningwu/eis/tdb/gateway/src/api/v2/ingest.routes.ts`
