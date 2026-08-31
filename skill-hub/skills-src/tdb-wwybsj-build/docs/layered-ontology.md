# wwybsj 分层本体设计

> 状态：L0、L1、L2、L3 与 wiki 投影层均已建成并验证。
> 文中所有数字都来自 2026-08-18 的实际库内统计，不是估计值。

---

## 0. 核心论点

### 0.1 引用，不是复制

最初的做法是：对每件文物去远端 `archeology` 语料检索，让 LLM 综合成一篇 markdown，
再让抽取 pipeline 从这篇 markdown 里抽三元组写进本地库。这条路线被废弃了，原因有三：

**(a) 拉过来的不是关于这件文物的证据，是章节级通论背景。** 语料是教科书，不可能有
465 件具体藏品的条目级覆盖。所有陶器都会命中同一批"渤海/陶器/釉陶"段落。465 条记录
会造出 465 份几乎相同的背景副本。

**(b) 证据链在交接处断掉。** pipeline 以 LLM 写的综合稿为 source ingest，最终 statement
的 provenance 指向那篇综合稿，远端 `stream_id/event_id` 只以纯文本躺在附录里，机器
无法解析回链。等于把 LLM 二手叙述当一手史料入库。

**(c) 断言主体错位。** 实际产出过这样一条：

```
渤海绿釉柱础护圈 --influenced_by--> 唐代陶瓷技术
```

问题不只是证据不足，而是**主体错了**。"受唐代技术影响"是关于*工艺传统/器物类别*的
断言，不是关于这一个个体的。正确形态是：

```
本地:  柱础护圈#0004 --instantiates--> archeology:concept:<渤海釉陶建筑构件>
远端:  渤海釉陶 --influenced_by--> 唐代釉陶技术      ← 留在 archeology 域，不复制
推理:  沿 instantiates 继承得到
```

所以"引用而非复制"不只是省空间，它**顺带修正了断言的主体**。

### 0.2 可推理性来自标识符对齐

本域的推理能力不来自本地存了多少背景，而来自**锚点边的对象槽位是可解引用的远端
标识符**。挂上一层锚，整个远端图的推理能力就都借到了。

这就是 hyperlink 的真正语义：不是文本链接，是 identifier alignment。

### 0.3 三层的职责边界

```
        L0  登记事实         观测层    确定性生成，无 LLM，无远端访问
            observed         主体 = 文物个体
              │
              │ instantiates / made_of → wwybsj.term.<facet>.<登记值>
              ↓
        L1  锚点边           对齐层    程序化解析 + 可审计的人工裁决
            inferred         主体 = 受控词项（不是文物）
              │
              │ aligned_to → archeology:concept:<同名簇>
              ↓
        远端 archeology 域   只读，按需解引用，一条事实都不复制
              ↑
              │ 引用远端原文段落作为证据
              │
        L2  研究性断言       解释层    槽位填充，九道硬闸门
            attributed       主体 = 文物个体
              │
              ↓
        L3  展品描述段       文本层    生成文字，但作为【数据】存下来
            hypothesized     主体 = 文物个体
              │
              ↓
        wiki 投影层          交付面    L0+L1+L2+L3 的确定性渲染
                                       page_type=entity
                                       authority_kind=compiled_summary
```

投影层不是一层，是**投影**：页面必须是断言的纯函数，`--verify-determinism`
逐字节验证这一点。L3 之所以要把生成的文字存成 statement 而不是渲染时即兴产出，
就是为了保住这条不变式——否则页面每次渲染都会变。

完整推理路径实例（文物 0008「唐残三彩莲纹柱座」）：

```
wwybsj.artifact.0008
  --instantiates--> wwybsj.term.category.陶器 --aligned_to--> archeology 簇（20 个 id）
  --made_of------->  wwybsj.term.material.陶  --aligned_to--> archeology 簇（3 个 id）

远端由此可达（这些事实不在本地库）：
  陶器 -has_property->      坚固耐用 / 硬度大大提高
  陶器 -uses_method->       手制
  陶器 -requires_condition-> 700～960℃
  陶器 -distinguished_from-> 人类蒙昧时代和野蛮时代
  殷墟 -consists_of->       陶器
```

---

## 1. 全域不变式

这几条跨层生效，任何新层都必须遵守。

### 1.1 命名一律前缀化

裸谓词名如 `is_a` 在 `semantic_entity` 里是**全局单例**：`entity_id` 就是主键，而
upsert 带 `ON CONFLICT (entity_id) DO UPDATE SET ... namespace = EXCLUDED.namespace`。

历史事故：wwybsj 的旧构建脚本写了一次裸名 `is_a`/`related_to`/`characterized_by`，
就把这些**其他域 4700+ 条 statement 正在使用**的公共谓词的 `namespace` 标签抢成了
`wwybsj`。`created_at` 停在 7 月（gateway 自己创建时），`updated_at` 变成 8 月（wwybsj
运行时）——证据就在时间戳上。后来按 `namespace='wwybsj'` 清库时，正要把这些公共谓词
删掉，是外键拦住了。

```
文物个体        wwybsj.artifact.<藏品总登记号>          e.g. wwybsj.artifact.0008
谓词            wwybsj.predicate.<name>                 e.g. wwybsj.predicate.dated_to
受控词项        wwybsj.term.<facet>.<登记值>            e.g. wwybsj.term.material.陶
qualifier 属性  wwybsj.qualifier.<key>                  e.g. wwybsj.qualifier.epistemic_mode
reference 属性  wwybsj.ref.<kind>                       e.g. wwybsj.ref.remote_concept
statement_key   wwybsj/<层>/<主体>/<name>[/<disc>]      e.g. wwybsj/L0/0008/made_of/陶
```

`namespace` 字段**不表示所有权，只表示最后一次谁写的**。域隔离绝不能只依赖它。

### 1.2 每条 statement 必带 `metadata_json.domain='wwybsj'`

清库时发现有 18 条 wwybsj statement 藏在 domain 标签之外（旧的 legacy `ontology_fact`
双写产物，metadata 里只有 `legacy_*` 键），只能靠 `created_by` 和实体引用才挖出来。
其中一条是 `该藏品 --has_condition--> 残缺` —— 主语的指代根本没解析。

所以：`domain` 标签 + 可唯一识别写入者的 `created_by` 是硬要求。

### 1.3 幂等性由 `statement_key` 保证

网关把 `statement_key` 映射成 `uuid5` 作为 `statement_id`（见
`tdb/src/rpc/ontology.rs` 的 `semantic_statement_uuid`），所以同一 key 重跑是原地更新。
qualifier / reference 由网关在插入前 `DELETE ... WHERE statement_id = $1`，也不会累积。

**但改了 `statement_key` 形状或 `EXTRACTOR` 版本号后，旧行不会被覆盖，只会停止再生**，
变成孤儿。L1 从 v1 升 v2 时（key 加了 `<relation>:` 前缀）就留下 19 条孤儿。
`wwybsj_l1.py --execute` 现在会检测同层不同 extractor 的残留并告警。

**而 qualifier 与 reference 是先删后插。** 网关在插入前对每个 statement 执行
`DELETE FROM statement_qualifier WHERE statement_id = $1`（reference 同理），
所以**任何重写 statement 的操作都必须带全它的 qualifier 与 reference**，否则会静默
丢掉证据链。实测代价：重算 `stance` 时只提交了 statements 和 `"references": []`，
一次就删掉了 **130 条远端原文引用**。是校验器的 V10 报出来的——也是该校验器第一次
抓到人为回归而不是模型错误。恢复靠的是 L2 留下的 plan 文件。

推论：**能重建的中间产物一定要落盘**。plan 文件当时看着像调试残留，结果是唯一的
恢复来源。

### 1.4 认知状态必须显式建模

`status` 字段承担的是审核流程状态，**不要**用它兼职表达知识来源性质。来源性质放
qualifier：

| `epistemic_mode` | 谁能产生 | 硬要求 |
|---|---|---|
| `observed` | **只有登记簿**。任何 LLM 都不许产生这一类 | 必带 `registry_field` + 登记事件 reference |
| `inferred` | 程序按可审计规则推出 | 必记规则与前提（L1 对齐属此类）|
| `attributed` | 远端原文 | 必带 `stream_id`/`event_id`/`source_span`，缺一个就**拒写** |
| `hypothesized` | 明确的猜测 | 默认不参与推理，除非查询显式要求 |

只有 `observed` 与 `attributed` 之间的冲突才是真冲突——一致性检查靠这个区分才有意义。

### 1.5 不确定性写进数据，不写进散文

覆盖不足、解析失败、簇被截断、对齐待复核——全部作为**可查询的 statement 或 qualifier**
存在，不是日志行、不是注释、不是"综合"段落里的一句限定语。

理由：消费者需要能问"哪些藏品可以做尺寸数值推理"，这必须是一次查询而不是一次阅读。

---

## 2. L0 — 登记事实层（已建成）

### 2.1 职责与边界

L0 是推理基座。它**只包含登记簿字面陈述的内容**，表达为 typed 值。

- 不调用 LLM
- 不访问远端语料
- 不做任何推断
- 全部 `epistemic_mode=observed`，`status=accepted`（登记簿就是权威）

明确**不做**的三件事：

1. **不解析 `ww_chicun`（尺寸）**——见 §2.4
2. **不做词项对齐**——那是 L1
3. **不写 wiki 页**——那是投影，不是层

### 2.2 产出规模

```
9301 条 statement / 465 件文物 / 平均 20.0 条每件
22 个谓词 · 36 个受控词项
29251 条 qualifier · 9301 条 reference（每条 statement 都有登记事件引用，缺失数 0）
```

### 2.3 typed 值——"能推理"和"只能检索"的分水岭

登记簿里 `高210.5`、`渤海（698年—926）` 都是字符串。字符串做不了区间比较和数值筛选。
L0 把它们结构化，同时**保留原始字面**（登记簿是权威，不能被规范化覆盖）：

```json
"dated_to": {
  "era_label": "唐", "start_year": 618, "end_year": 907, "calendar": "CE",
  "parse_status": "range_parsed", "registry_literal": "唐(618~907)"
}
"has_mass": {
  "value": 0.48, "unit": "kg", "unit_source": "registry_column",
  "normalized_g": 480.0, "registry_literal": "0.480"
}
"has_dimension": {
  "dimension": "height", "label_zh": "高", "value": 11.3,
  "unit": null, "unit_source": "unspecified",
  "registry_field": "ww_gao", "registry_literal": "11.3"
}
```

年代解析只在字面**明确写出年份时**才产出年份。`宋`、`北朝`、`渤海` 这种只有标签的，
`start_year` 保持 `null`、`parse_status='label_only'`。给 `宋` 编一个区间会造出一个
后续区间推理会当真的假事实。

覆盖实况：

```
range_parsed   90 / 465    可做时间区间推理
label_only    287 / 465    只有标签
无年代          88 / 465
```

质量归一化只在**单位显式存在于独立列**时才做。`has_mass` 有 `ww_zhiliang_dw` 列写着
`g`/`kg`，所以 `normalized_g` 是安全的（313 件可直接数值比较）。`has_dimension` 的
长/宽/高三列在 schema 和 DDL 注释里**都没有单位**，所以 `unit` 保持 `null`，
`unit_source` 明说 `unspecified`。

### 2.4 为什么 `ww_chicun` 故意不解析

这是本设计里最容易被误解的一个决定，所以讲清楚。

`ww_chicun`（尺寸）是自由文本，实际样本：

```
底厚4 高210.5 口径42 外径62.6
存长:(大)20.2 (小)9 高(大)8(小)5.8 底厚          ← 被截断
存14.8*832*3.4                                    ← 832 明显是错值
厚3.7*18.9*3.9
大:19.5*7*2.1 小:13.2*9.1*1.4                     ← 多块记录
最大块30.5*22.8*3.8 最小块17.3*10.5*
```

465 条里**只有 13 条写了单位**（11 个"厘米" + 2 个 "cm"）。结构化的长/宽/高三列
分别只有 78/50/96 条非零，也就是说**大多数尺寸只存在于这个自由文本里**。

如果用正则去解析它并补一个单位，就会得到"柱础护圈高 210.5 厘米"——一个 2.1 米高的
柱础护圈。这正是旧路线实际产出过的错误（LLM 在综合稿里凭空补了 "cm"）。

所以 L0 的做法是：

- 原文照存为 `has_dimension_note`，标 `parse_status='unparsed_free_text'`
- 结构化列有值时才产出 `has_dimension`，且 `unit_source='unspecified'`
- 发数据质量标记，让"不可用"变成可查询的事实

**解析留给一个独立的、可复核的步骤**，那一步的产出必须是 `inferred` 并记录规则。

### 2.5 数据质量标记是 statement，不是日志

```
751 条 has_data_quality_flag，覆盖全部 465 件：
  335  dimension_only_in_free_text     尺寸仅在自由文本，结构化列全 0，不可数值推理
  287  period_label_without_years      年代仅有标签，无区间，不可时间推理
  129  dimension_unit_unspecified      长/宽/高 无单位来源，跨件比较前须先定单位
    0  mass_unit_missing               有质量数值但无单位列（实际未出现）
```

因为它们是 statement，所以"这个域能支持什么推理"是一次 SQL 查询：

```sql
select value_json->>'code', count(*) from semantic_statement
 where property_id='wwybsj.predicate.has_data_quality_flag' group by 1;
```

### 2.6 受控词项与联合桶

登记簿的类别/材质是受控词汇，L0 为每个取值建一个词项实体
（`wwybsj.term.<facet>.<值>`），文物通过 `instantiates`/`made_of` 指向它。

两个细节：

- **`铜,金` 是两个材质，不是一个。** `ww_zhidi_c` 按 `[,，、/]` 拆分，产出多条
  `made_of`（465 件里 2 件如此，故 `made_of` 是 467 条）。
- **`玉石器、宝石` 是一个登记类别，不拆。** 它是登记簿的一个受控取值，拆开会伪造
  出登记簿没有的分类。它的**成分对齐**在 L1 处理（见 §3.5）。

### 2.7 L0 谓词与登记字段的映射

见 [predicate-registry.md](predicate-registry.md)。

---

## 3. L1 — 锚点层（已建成）

### 3.1 职责

L1 记录：本地每个受控词项**指称哪个远端概念**。它不把任何考古知识复制进来。

产出规模：

```
62 条 statement / 36 个词项
  23 条 aligned_to（锚点边）      exact 18 / broader 4 / narrower 1
   1 条 alignment_candidate（文档锚点，不参与推理）
   2 条 alignment_rejected（同形词否决）
  36 条 alignment_status
24 条 remote reference · 244 个可达远端概念 id
```

### 3.2 关键决定：对齐挂在词项上，不挂在文物上

36 个词项覆盖全部 465 件文物。挂在词项上：

- 是几十条断言而不是几千条
- 每个词项的对齐是**唯一的真相来源**
- 远端语料换版本时只需重解析这 36 个

推理时多跳一步（文物 → 词项 → 远端），换来的是可维护性。

### 3.3 锚点指向同名概念簇，不是单个 id

远端有大量**未消解的同名概念**：

```
铁器 27 个 · 漆器 25 个 · 青铜器 22 个 · 陶器 20 个 · 石刻 17 个
瓷器 13 个 · 金银器 11 个 · 陶瓷器 10 个 · 钱币 9 个 · 玉石器 7 个 · 宝石 7 个 · 砖瓦 8 个
```

而它们的**事实集不同**。取"第一个精确匹配"会静默丢掉大部分可达知识——实测两例：

| 词面 | 旧版选中 | 该成员内容 | 漏掉的成员 |
|---|---|---|---|
| 玉石器 | `3bb894fc` | 只有 `requires_condition/instance_of` | `5266abe7` 带「龙虬庄遗址 associated_with」 |
| 宝石 | `7c16890f` | 只有「巴洛克艺术 characterized_by 宝石」噪声 | `ca5cb86a` 带「宝石 introduced_to 中国」「丝绸之路 consists_of 宝石」 |

旧版两次都挑到了较差的那个。而且 `concept/search` 的结果顺序不保证，这个选择连
**复现**都做不到（实测 `陶器` 在两次运行间从 `2d35c82f` 变成 `fc40e5ed`）。

所以锚点值是整簇：

```json
{
  "matched_surface": "陶器", "match_relation": "exact",
  "concept_ids": ["...", "...", "…20 个…"],
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

**实体消解是远端自己的债，本地不替它猜——推理时 union 整簇。**
`primary_concept_id` 用字典序最小（与搜索顺序无关，可复现），仅用于显示和稳定键。

`cluster_completeness` 如实标注：13 个簇的 `search_result_truncated` 全为 `true`，
**簇大小只是下界**。根因是远端缺一个"按精确名列举概念"的端点，见 §5.1。

### 3.4 三级质量控制

"是个 concept" 不等于"能用"。三个层次的证据都实测过。

**第一级：wiki 兜底不可信。** 远端语料自己有垃圾：

```
完整 → "Has Property [[较完整的国体（the Shan state）]]"
一般 → "Defined As [[艺术的和知识的活动]]"  flags=['invalid_supporting_signal_id']
铜   → "Consists Of [[甜饼]]"
```

ontology 概念过了 promotion 阈值，随手建的 wiki 页没过。所以只有 `xref_kind=concept`
能成为锚点；wiki-only 命中降级为 `alignment_candidate`
（`epistemic_mode=hypothesized`、`review_status=blocked_pending_review`、`confidence=0.3`），
推理时可过滤。

**第二级：同名不等于同义（同形词）。** 这是簇 union 的真实危险：

| 词面 | 簇内实际内容 | 处理 |
|---|---|---|
| `金`(4) | `-occurred_at-> 1234年` / `-produced_by_culture-> 女真族` / `-located_in-> 北方` = **金朝**；另两个是「文/武」「钟镈」 | `reject_exact`，改走 `金属` broader |
| `石`(2) | `-defined_as-> 容量單位` / `-defined_as-> 十斗` = **量词「石」** | `reject_exact`，该类已通过类别 `石器` 有通路 |

照着对齐就会让金器 `-produced_by_culture-> 女真族`。

**第三级：簇内单个成员排除。** `铜` 簇 4 个成员里 `b319e504` 就是那个
`甜饼 -consists_of-> 铜`。用 `exclude_concept_ids` 按 id 前缀剔除，剩 3 个。

### 3.5 SKOS 式关系与联合桶

`match_relation` 取值 `exact | close | broader | narrower`，指**远端目标**相对本地词项
的宽窄。当前用到：

```
exact     18 条    同名且同义
broader    4 条    瓷器→陶瓷器 · 瓷→陶瓷器 · 金→金属 · 铁/铜/其他金属→金属
narrower   1 条    铜器→青铜器（青铜器 ⊂ 铜器）
```

置信度按关系强度分级：整词 exact 0.95、成分 exact 0.8、broader/narrower 0.7、
wiki 候选 0.3。

联合桶按成分对齐，每个锚点标明匹配的是哪个词面：

```
玉石器、宝石       → 玉石器[exact] + 宝石[exact]
石器、石刻、砖瓦    → 石器[exact] + 石刻[exact] + 砖瓦[exact]
铁器、其他金属器    → 铁器[exact]
雕塑、造像         → 雕塑[exact] + 造像[exact]
```

### 3.6 管理类词面不对齐

`级别`(一级/二级/三级/一般/未定级)、`来源`(发掘/征集购买/旧藏…)、`完残程度` 是
**藏品管理词汇**，不是考古概念，L1 根本不去查，直接标 `not_applicable` 并记原因。

`一般` 的远端页面（`Defined As [[艺术的和知识的活动]]`）就是"去查会怎样"的活教材。

覆盖影响：这 16 个词项覆盖 1396 条 statement，全部标为不适用——**这不是缺口，是
正确的边界**。

### 3.7 裁决是数据，不是硬编码

所有人工判断落在 `../alignment_review.json`：

```json
{
  "facet": "material", "label": "金", "surface": "金",
  "decision": "reject_exact",
  "reason": "同形词：4 个同名概念全部不是金属材质——分别指金朝、以及『文/武』『钟镈』语境。簇 union 会把女真族、1234 年等金朝事实挂到金器上。",
  "evidence": "金 -occurred_at-> 1234 年 / 公元 1115 年; 金 -produced_by_culture-> 女真族; 金 -uses_method-> 武; 金 -defined_as-> 钟镈"
}
```

每条带远端原文证据，`reviewer` / `review_status` 如实标注
（当前是 `machine_reviewed_pending_curator`，**没有冒充人工策展**），策展人可逐条推翻。
脚本读这个文件，不内置判断。

`decision` 取值：`confirm_exact` / `reject_exact` / `align`(+relation+target) /
`promote_wiki` / `keep_wiki_candidate` / `reject_wiki` / `not_applicable` /
`leave_unaligned`，另有 `exclude_concept_ids` 作用于成员级。

### 3.8 对齐现状与真实缺口

```
aligned                 6 词项   164 条 statement
aligned_by_components  10 词项   507 条
not_applicable         17 词项  1396 条   （管理类，正确的边界）
unaligned               1 词项     4 条   石（同形词否决，类别层有通路）
leave_unaligned         1 词项   230 条   宝玉石
```

按 facet：

```
category    10/10 词项对齐 → 465/465 件覆盖
material     7/10 词项对齐 → 232/467 条覆盖
```

**藏品级覆盖：465/465 全部有精确概念通路。**

剩下的真缺口只有一个值得记：`宝玉石`（230 件）在远端 `limit=200` 的子串搜索里
返回 **0 条**，确实不存在。对齐到 `玉石器`（器物类）是**类型错误**——材质槽不能填
器物类概念，所以不做。这 229 件已通过类别 `玉石器、宝石` 获得远端通路，材质层的
缺口不阻塞推理。需策展人决定是否在远端引入材质概念。

---

## 4. L2 — 研究性断言层（已建成）

### 4.0 产出规模

```
1394 条 statement / 465 件文物
  typological_parallel        240 件有   （attributed）
  probable_original_context   132 件有   （hypothesized）
  dating_corroboration        130 件有   （attributed，带 stance）
  has_research_gap            892 条     （可查询的缺口，不是日志）
502 / 502 条断言都有远端原文引用，闭环无缺口
证据层级  form_head_level 305 · form_level 178 · class_level 19
```

填充率约 36%（502 / 1395 个槽位）。这不是失败——是闸门把"不敢说的"都推成了缺口。

**一个必须记住的缺陷**：`dating_corroboration` 的 `stance` 130 条**全部是
`supports`，零 `questions`**。抽查找到站不住的例子：登记「唐代」(618–907) 却引用
「不能早于5世纪，晚则不能晚于8世纪前后」判 supports。一个从不说"不"的判据等于没有
判据。正确解法不是调 prompt，而是把 stance 变成**计算值**——L0 已有 90 件的 typed
年代区间，程序化比对即可，见 §8。

### 4.1 L2 要解决什么

L0 说的是登记簿写了什么，L1 说的是这些词指称什么。都没有说**关于这件文物本身的
研究性结论**：它可能出自哪种建筑、它的工艺属于哪个传统、它与哪些同类器可比。

这类结论必然来自远端原文，因此必然是 `attributed`，必然可被推翻。

### 4.2 为什么不能重复旧路线

旧路线（LLM 综合 markdown → pipeline 抽取）失败的四个原因，L2 必须逐条防住：

| 旧问题 | L2 的对策 |
|---|---|
| provenance 指向 LLM 写的稿子 | statement 的 reference **直接**携带远端 `stream_id/event_id/source_span`，不经过中间文本 |
| 两跳 LLM，误差乘法 | 只有一跳，且不是自由抽取 |
| 自由抽取无法约束主体 | **槽位填充**：给定槽位表，LLM 只能填空或答"无支撑" |
| 比较物被当成本地事实 | 槽位本身按主体分类：文物槽 vs 类别槽，类别槽写不进文物 |

### 4.3 槽位填充，不是自由抽取

不要问 LLM"从这段文本里抽三元组"，而是给它固定槽位：

```
槽位:  wwybsj.artifact.0008 的 typological_parallel
候选:  [远端检索到的 N 个候选，每个带 event_id 和原文片段]
指令:  从候选中选择，或回答 insufficient_evidence。不得引入候选之外的对象。
输出:  {slot, chosen_object | null, evidence_event_ids[], confidence, reason}
```

自由抽取无法约束主体（这就是 `该藏品 --has_condition--> 残缺` 的由来），槽位填充可以。

初始槽位表建议（按主体严格分开）：

**文物个体槽位**（主体 = `wwybsj.artifact.*`）

| 槽位 | 含义 | 约束 |
|---|---|---|
| `typological_parallel` | 可比同类器 | 对象必须是远端概念或另一件本馆文物；defeasible |
| `probable_context` | 可能的原始使用语境 | 必须 `hypothesized`，不得 `attributed` |
| `dating_corroboration` | 支持/质疑登记断代的远端证据 | 必须能与 L0 的 `dated_to` 做区间比较 |
| `conservation_mechanism` | 该材质的劣化机理 | 主体其实是材质 → 应写到词项上，见下 |

**词项槽位**（主体 = `wwybsj.term.*`）

| 槽位 | 含义 |
|---|---|
| `technique_tradition` | 该材质/类别所属工艺传统 |
| `deterioration_mechanism` | 该材质的劣化机理 |
| `typical_provenance` | 该类别的典型出土语境 |

**关键**：`conservation_mechanism` 这类断言的真实主体是材质而不是个体。放到词项上，
465 件文物通过 `made_of` 自动继承——这既正确又避免 465 份复制。这与 §0.1(c) 是同一个
道理。

### 4.4 硬闸门（写入前拒绝，不是事后审计）

旧脚本 `wwybsj_write.py` 有一段值得继承的代码，L2 必须保留其精神：

```python
if basis == "source_text":
    missing = [k for k in ("source_stream_id", "source_event_id", "source_span")
               if not fact.get(k)]
    if missing:
        raise SystemExit(
            f"statement {predicate} -> {obj!r} declares basis=source_text "
            f"but is missing {missing}. A researched claim without a citable "
            f"remote passage must not be written.")
```

L2 的完整闸门清单：

1. **`attributed` 必须有可解引用的远端 `stream_id`+`event_id`+`source_span`**，缺一即拒
2. **`evidence_event_ids` 必须真实存在于检索结果里**——校验引用 id 的存在性，防幻觉
3. **同一 `event_id` 在不同 query 下的重复必须去重**——否则 LLM 会把同一段落当成两个
   独立来源写"[search:004, search:007]"造成**伪互证**（旧路线实测发生过：8 条证据里
   3 对是重复 event）
4. **类型检查**：槽位的 subject/object 类型必须符合谓词声明
5. **对象必须来自候选集**，不得引入候选之外的实体
6. **LLM 不可用时拒绝降级写入**——旧脚本捕获所有异常后静默降级到机械 fallback，而
   fallback 用 CJK 2-gram 碎片生成 `related_to`，配合 `--run-pipeline` 会把
   `X related_to 海政` 这类垃圾直接写库
7. **coverage 闸门**：覆盖度 `thin`/`none` 时拒绝写研究性断言（可 `--force` 覆盖但要
   显式）
8. **噪声块不得引用**：目录页、`block_type=footnote`、`extraction_text=false` 标记的
   块——语料里明明带这个标记，旧路线完全无视，引用了整段参考文献著录当"证据"

### 4.4.1 L3（展品描述段）的七道闸门

散文层能撒的谎和 L2 不同，所以闸门要重新枚举，不能沿用：

| 闸门 | 内容 |
|---|---|
| P1 | 专名不得凭空出现——文中的遗址/城址/墓群名必须在素材里 |
| P2 | 长度 40–260 字（说明牌，不是文章）|
| P3 | 记为**缺口**的槽位不得在文中被断言。332 件没有功能推断，散文不许悄悄补一个 |
| P4 | `derived_from` 非空且 id 必须存在 |
| P5 | 无 LLM 则无散文，没有任何 fallback |
| P6 | **不得编造单位** |
| P7 | **不得编造出土语境**——本域零出土数据，任何「出土于…」都是编造 |

P6 和 P7 都是被真实产出逼出来的，不是设计时想到的：

- **P6**：第一段生成的文字写「其口径42**厘米**，外径62.6**厘米**，高210.5**厘米**」。
  登记簿 `unit_source=unspecified`，LLM 凭空补了单位——**又造出一个 2.1 米高的
  柱础护圈**，正是 L0 拒绝解析 `ww_chicun` 所要防的那件事（§2.4）。第一版闸门查了
  年份、专名、缺口、长度，唯独漏了单位。
- **P7**：批量跑完后有 14 条写了「出土于渤海政权后期城址」「出土于发掘」
  「出土于战国时代（前475~前221）」。本域**零出土语境**（§5.6），这类句子按构造
  就是编造。

### 4.4.2 闸门自身必须用真实样本验证

这是本项目代价最大的一条教训。

L3 首轮结果是 **319 通过 / 146 拒绝**，看起来像"闸门很严格"的好消息。抽样一查，
**146 条里 131 条是我自己实现的误杀**：

| 闸门 | 误杀 | bug |
|---|---|---|
| P1 | 56 | 正则用了 lookahead，捕获的是关键词**前面**的任意 2–8 字——`'该政权由我'`（"我**国**"之前）、`'属于肃慎系的地方'`（"**国**家政权"之前）。全是滑动窗口垃圾，不是专名 |
| P6 | 24 | 单位别名里放了 `寸`/`尺`，命中了「**尺寸**」这个词——那是 dimensions，不是单位 |
| P2 | 78 | 下限 60 字太严。`新罗灰陶爵，陶质…高12.7，口径8.5。年代为新罗（618-906），为旧藏。` 56 字，是合格的说明牌文字 |
| P3 | 1 | `作为` 太泛，命中「可**作为**本件的类型学参考」——没断言任何功能 |

修完后 131 条改判通过，剩 15 条是真错（全是 P7 那一类）。

**过严的闸门和过松的闸门一样有害**：它静默压低覆盖率，还把自己伪装成质量证据。

关键点在于**扰动测试不够**。我为每道闸门都写了扰动用例，全部通过——因为我扰动的
正是我想到的那几种失败。只有拿**真实产出**去重判，才暴露出 131 条误杀。所以：

> 每加一层输出，先枚举"这一层能怎样撒谎"并写闸门；然后**用这一层的真实产出反过来
> 检验闸门**，把每一条拒绝都看一遍，判断它是真拦还是误杀。

### 4.7 `stance` 是计算值，不是判断

LLM 对 123 条断代旁证给出 **123 个 `supports`、0 个 `questions`**。一个从不说"不"的
判据等于没有判据，而且抽查确实抓到错判。

现在 `stance` 由区间比对得出（`wwybsj_stance.py`）：

```
undetermined     104   引用表述根本没写年份，无法判定——这是诚实答案
supports          18
partial_overlap    7
questions          1
```

被改判的例子都站得住：

```
0130 [唐]  questions        「唐王城出土遗物多在 5 世纪前后」→ 401~500 与 618~907 完全不重叠
0162 [唐]  partial_overlap  「不能早于5世纪，晚则不能晚于8世纪前后」→ 401~800 仅部分重叠
```

原 LLM 判断保留在 `value_json.llm_stance` 供审计。

**时期区间从登记簿自身推导**（`period_intervals.json`，11/20 个时期可推出）。只有
23/123 件文物自带年份区间，但同一时期总有某些记录写了年份，可以把区间提升到时期词项
复用——这就是 §4.6 说的 `inferred` 回填。两处必须小心：

- **年号跨度不是朝代跨度**。`唐天宝年间`(742–756) 被归并进 `唐`，但唐的跨度是
  618–907。所以优先采用"标签本身即规范形"的记录，把归并进来的子期区间排除并记录。
- **冲突不静默归一**。`东周` 在登记簿里是 -770~-256 / -257 / -258 三个值，取并集为
  跨度并标 `conflict: true`。

一处更正：曾判断"渤海 698–926 对引用 713–926 判 supports 过于宽松"是**错的**。区间
语义下 713–926 包含在 698–926 之内，引用没有否证 698，只是没覆盖到。`supports` 正确，
但解释文字会注明"引用范围窄于登记，其余部分未被旁证覆盖"。

### 4.5 L2 的 statement 形状

```json
{
  "statement_key": "wwybsj/L2/0008/typological_parallel/上京龙泉府建筑构件",
  "subject_id": "wwybsj.artifact.0008",
  "property_id": "wwybsj.predicate.typological_parallel",
  "value_type": "json",
  "value_json": {
    "object_kind": "remote_concept",
    "concept_ids": ["..."],
    "canonical_name": "上京龙泉府",
    "slot": "typological_parallel"
  },
  "status": "extracted",
  "confidence": 0.6,
  "created_by": "wwybsj_l2_v1",
  "metadata_json": {"domain": "wwybsj", "layer": "L2", "slot": "typological_parallel"}
}
```

qualifier：

```
epistemic_mode = attributed
basis          = remote_source_text
defeasible     = true
slot           = typological_parallel
review_status  = unreviewed
retrieval_run  = <检索批次 id，用于复现>
```

reference（`wwybsj.ref.remote_passage`）：

```json
{"gateway": "http://10.124.48.91:8989", "domain": "archeology",
 "stream_id": "archeology.phase1...ch03", "event_id": "092670e9-...",
 "note": "resolves on the remote gateway, not in this database"}
```
`source_span` 存该段落的实际引文。

### 4.6 `inferred` 子层：程序化推导

有一类断言既不是登记事实也不是远端引用，而是**按可审计规则从 L0 推出来的**。它们
应记为 `epistemic_mode=inferred`，必带 `rule` 和 `derived_from`（前提 statement_id）。

现成的两个例子：

**(a) 年代标签回填。** 登记簿里同一个标签 `渤海` 有时带年份（`渤海（698—926）`）
有时不带。可以用登记簿**自身的**自洽规则回填那 287 条 `label_only`：

```
rule: era_label_backfill_from_registry
前提: 存在另一条 dated_to，era_label 相同且 parse_status=range_parsed
产出: {start_year, end_year, parse_status: "inferred_from_same_label"}
```

这是确定性的、可复现的、可撤销的，且完全不依赖外部知识。

**(b) 尺寸解析。** §2.4 拒绝在 L0 做的事，可以在这里做——但必须 `inferred`、必须记
解析规则、必须保留 `registry_literal`，且**不得凭空补单位**（无单位就是无单位）。

**警告**：`东周` 在登记簿里有三个互相矛盾的区间（`-770~-256` / `-257` / `-258`），
回填规则必须先处理冲突，不能随便挑一个。

---

## 5. 已知的上游问题

这些不是本域的 bug，但会直接影响本域的正确性，记在这里以免重复踩。

### 5.1 `concept/search` 是子串搜索，且 `limit` 上限 200

- 精确同名概念可能排在很后面。`铁器` 有 27 个精确同名概念，`limit=10` 的探针一个也
  看不到，于是落到垃圾 wiki 页兜底。**九个词面**（`铁器`/`石刻`/`瓷器`/`铜器`/`雕塑`/
  `铜`/`铁`/`金`/`石`）全因此被误判为"远端没有概念"。
- `limit > 200` 返回 HTTP 400。
- 结果顺序不保证，"取第一个"不可复现。
- 缓存里已知存在的 id，当次搜索可能根本不返回（实测 `陶`/`陶器`/`造像`）。

**正确的修法是远端加一个按精确名列举概念的端点。** 在那之前，`concept_cluster()` 用
`limit=200` 扫全量并把已知 id 折进来，同时标记 `search_result_truncated`。

### 5.2 负结果绝不能缓存

一次超时/400 与"真的不存在"在这一层无法区分，而 `sget` 把错误也报成空结果。旧版
`lookup_source_concept` 把 miss 写成 `null` **永久冻结**——`铁器` 的假阴性就是这么
留下来的。

现在只缓存正结果；miss 每次多花一个请求，仅在进程内报告。幂等性不受影响：
`statement_key` 由 `(登记号, 谓词, 对象)` 推导，**不含 xref**，所以后来解析出结果只会
原地更新，不会分叉。（当年需要缓存负结果是因为旧的 `ontology_fact` 路径按
`qualifier_json` 做键，xref 一飘就多一行 fact——实测过 9 条 fact 来回翻。）

### 5.3 `GET /v2/ontology/fact/list` 没有 `domain` 参数

传 `domain=` 会被 Fastify **静默丢弃**，返回全库事实。必须先 `domain-stream/list` 拿
stream 列表再逐流查。

### 5.4 约束违反被包成裸 500

`semantic_role` 受 CHECK 约束，literal 谓词的正确拼法是 `datatype_property`
（不是 `data_property`）。写错时网关返回 `HTTP 500 INTERNAL_ERROR`，**没有任何细节**。
定位办法是把载荷最小化——连"只发 entities"都 500，就说明问题在实体上。

### 5.6 本域没有任何出土语境（这不是缺陷，是数据源的边界）

```
site / excavation / found_at 谓词        0 条
来源字段 acquired_by                  465 条，但取值只有 发掘/采集/旧藏/征集购买（管理性）
含层位/探方/墓号的 statement           24 条——全部在 L1 引用的远端段落里，
                                        讲的是文献中【别处】的遗址
```

登记簿从设计上就不含发掘语境。因此：

- 自动发掘报告这类任务**不是数据量问题，是结构性缺失**，需要另一个数据源
- L3 的 P7 闸门存在的理由就是它——生成模型会自然而然地补一个出土地点，实测 14 次

### 5.5 `ontology_relation_type` 表达能力有限，且不参与强制

该表有 `is_symmetric` / `is_transitive` / `src_type_id` / `dst_type_id` /
`min_confidence` / `conflict_policy` / `conflict_key`，但：

- **没有 `is_functional` 列**——functional 只能借 `conflict_key='src_predicate'` +
  `conflict_policy` 间接表达，而那管的是 pipeline promotion，不是本写入路径。
- `dst_type_id` 假定对象是实体，21 个字面值/json 值谓词无法描述。
- upsert API 不暴露 `conflict_key`/`conflict_policy`，必须走 SQL。
- **`semantic_statement` 上没有触发器，`upsert-batch` 也不查这张表**——注册本身
  不产生任何强制力。

所以契约的真相来源是 `predicate_contract.json`，强制靠 `wwybsj_predicates.py
--validate` 的 14 项检查。详见 [predicate-registry.md](predicate-registry.md) §3。

---

## 6. 验收：competency questions

本体设计到"能回答这些"就算达标。先写查询，再改 schema——每处 schema 改动都该有一条
具体的失败查询作为理由。

| # | 问题 | 需要的能力 | 现状 |
|---|---|---|---|
| Q1 | 断代早于公元 300 年的藏品 | typed 区间 | ✅ 46 件 |
| Q2 | 哪些藏品共享同一材质/工艺传统 | L1 锚点 + 远端 join | ✅ 按远端概念聚类 |
| Q3 | 登记断代与已知年代范围矛盾的藏品 | 区间推理 + 一致性检查 | ✅ 抓到 `东周` 三个矛盾区间 |
| Q4 | 二级以上、状态不稳定、质量超阈值的藏品 | typed 量值 + 受控词项 | ✅ 3 件（>1kg）|
| Q5 | 每条研究性断言能否解引用回远端原文 | provenance 闭环 | ⏳ 待 L2 |
| Q6 | 某远端概念被本馆哪些藏品实例化 | 反向 join | ✅ 20 个（目标, 关系）组合 |

可执行版本：

```sql
-- Q1
select count(*) from semantic_statement
 where property_id='wwybsj.predicate.dated_to' and (value_json->>'end_year')::int < 300;

-- Q3 一致性检查：同一年代标签被登记成互相矛盾的年份区间
select value_json->>'era_label' era,
       string_agg(distinct (value_json->>'start_year')||'~'||(value_json->>'end_year'), ' | ')
 from semantic_statement where property_id='wwybsj.predicate.dated_to'
   and value_json->>'parse_status'='range_parsed'
 group by 1
having count(distinct (value_json->>'start_year')||'~'||(value_json->>'end_year')) > 1;
-- 实际结果: 东周 | -770~-256 | -770~-257 | -770~-258

-- Q4
select a.metadata_json->>'registry_no' rn, a.metadata_json->>'subject_label' lbl,
       round((m.value_json->>'normalized_g')::numeric/1000, 3) kg
 from semantic_statement a
 join semantic_statement g on g.subject_id=a.subject_id and g.property_id='wwybsj.predicate.has_grade'
 join semantic_statement m on m.subject_id=a.subject_id and m.property_id='wwybsj.predicate.has_mass'
 join semantic_statement c on c.subject_id=a.subject_id and c.property_id='wwybsj.predicate.has_conservation_state'
 where a.property_id='wwybsj.predicate.has_name'
   and g.value_entity_id in ('wwybsj.term.grade.一级','wwybsj.term.grade.二级')
   and (m.value_json->>'normalized_g')::numeric > 1000
   and c.value_json->>'text' not like '%稳定%'
 order by kg desc;

-- Q6 反向 join
select a.value_json->>'remote_canonical_name' target,
       a.value_json->>'match_relation' rel,
       (a.value_json->>'cluster_size')::int cluster,
       count(distinct s.subject_id) artifacts
 from semantic_statement a
 join semantic_statement s on s.value_entity_id=a.subject_id
   and s.property_id in ('wwybsj.predicate.instantiates','wwybsj.predicate.made_of')
 where a.property_id='wwybsj.predicate.aligned_to'
 group by 1,2,3 order by 4 desc;
```

### 6.1 可推理性总账

这是本域最有价值的自我描述——它诚实地说明边界：

```
断代可做区间推理      90 / 465     仅有年代标签  287     无年代  88
质量可比（已归一）    313 / 465
尺寸有结构化数值      129 / 465     单位仍未定 → 跨件比较前必须先定单位
尺寸只在自由文本      335 / 465     不可数值推理
有远端概念通路        465 / 465
```

---

## 7. L3 与 wiki 投影层（已建成）

### 7.1 L3：展品描述段作为数据

```
464 / 465 件有描述段（0266 登记信息太少，写不到 40 字，如实留空）
平均 75 字 · 最短 42 · 最长 177
全部 status=proposed · reviewed=false · extraction_text=false
```

**为什么必须存下来而不是渲染时生成**：投影层的不变式是"页面是断言的纯函数"。
一段描述文字无法从断言推导出来（它是写的），所以只有两条路——每次渲染重新生成
（不变式破了），或者存成数据。存成数据。

**它是什么，不是什么**：`has_exhibit_prose` 是**文本投影产物，不是语义断言**。
值是文本块，标 `extraction_text=false`。所以库里不会出现一份可查询的远端知识副本
——`渤海 influenced_by 唐` 的机器可读形式仍然只在远端，经链接到达页面。没有人会把
这个文本块当事实来查询，也没有任何抽取会读它。

`derived_from` 列出它转述的本地 statement id，可逐条回溯，也便于策展人整段替换成
人工撰写版本（`reviewed` 从 false 改为 true）。

### 7.2 wiki 页是投影，不是层

```
465 页 · 平均 3330 字
page_type = entity · knowledge_level = fact_like
authority_kind = compiled_summary   ← 不是 accepted_ontology
--verify-determinism：逐字节一致 465 · 不同 0 · 仅库中有 0 · 仅新渲染有 0
```

`authority_kind` 用 `compiled_summary` 是特意的。旧路线那 2375 个垃圾页全标成了
`accepted_ontology`，把编译产物伪装成本体权威。

页面结构：

```
## 描述            L3（标 extraction_text=false，注明未经复核）
## 登记信息        L0，每行标注来源登记字段，未记载的如实留空
## 时代与文化背景   L1 锚点 + 白名单过滤的远端事实，全部是链接
## 同类器与研究线索 L2，每条带 attributed/hypothesized 标记与远端原文链接
## 数据说明        数据质量标记 + 研究缺口
```

### 7.3 背景只放链接，且必须按谓词白名单过滤

背景**不复制**。页面里是 `[[archeology:concept:<uuid>|渤海]]`，渲染时解引用。

白名单不是装饰。L1 锚点能控制我们**指向哪些**远端概念，控制不了远端图**对它们说了
什么**。实测：

```
渤海 -instance_of->    地方国家政权            ✓ 出边白名单
渤海 -influenced_by->  唐王朝先进制度和文化      ✓
肃慎系 -consists_of->  渤海                    ✓ 入边白名单（族属）
渤海海面封冻 -associated_with-> 渤海            ✗ 远端图自身的错边
```

最后那条挂在**被保留的**渤海国概念（3f88ffe8）上，L1 的成员排除拦不住它——
**只能在投影层按谓词和方向过滤**。

`wiki_page_link` 只有 `from_page_id`/`to_page_id`，连的是本地页，所以跨域链接
**存不进那张表**，只能活在 markdown 里 + 靠 renderer 解析。这不是缺陷：远端 id 本来
就是"回远端解析的句柄，不是本地外键"。

### 7.4 最容易犯的错：把"不知道"写成"是"

每页末尾必须显示自己的缺口。335 件没有断代旁证、332 件没有功能推断——这些在页面上
明确显示为缺口，而不是被流畅的文字掩盖过去。

尺寸那行特意写成"**登记簿未声明单位**"而不是省略。展品页上出现"高 210.5"而不说单位
是别扭的，但**编一个单位更糟**。

### 7.5 五类应用任务的可行性（实测判定）

| 任务 | 判定 | 依据 |
|---|---|---|
| 展品介绍（国家/文化/朝代背景） | **已交付** | 465 页；period 锚点 20/20 覆盖全部 465 件 |
| 跨文化相似性 | **已解锁** | 标签归并 31→20 消除聚合错误；本馆本身是东北亚多政权样本（高句丽 39 / 渤海 25 / 新罗 18 / 唐 58）|
| 谱系 | 挂靠可行，自建不行 | 远端有分期序列可挂（渤海 166 / 高句丽 101 概念）；本馆 308/365 形制只 1 件，密度不足 |
| 关联性/年代 + 社会形态 | 年代可做，社会层薄 | Q1/Q3 已验证；社会主题断言仅 53 条（建筑 58 / 生活 17 / 丧葬 15 / 礼制 13 / 战争 8）|
| 自动发掘报告 | **结构性不可行** | 本域零出土语境（§5.6）；L3 的 P7 拦下 14 次编造，正是这个缺失的实证 |

远端语料是背景知识的主体，且**恰好补上本地缺的那块**：本地 `archeology_expert`
有 38953 页但偏中原正史，渤海/高句丽**零覆盖**；远端 `archeology` 覆盖东北亚
（渤海 166 概念、高句丽 101、新罗 50，均为下界）。

## 8. 未完成事项

按建议优先级：

1. ~~谓词代数性质注册~~ —— **已完成**（32 个谓词，14 项校验全过）。
2. ~~wiki 投影层~~ —— **已完成**（465 页，确定性验证通过）。
3. ~~L2 实现~~ / ~~L3 实现~~ —— **已完成**。
4. ~~把 `stance` 改成计算值~~ —— **已完成**，见 §4.7。
5. **启用形制受控词表** —— 草案 `out/l2/form_vocab_draft.json`（113 个末字，前 36 个
   覆盖 80% 文物）仍未启用。切词处理不好单字中心词（佩/环/珠/镜）与材质修饰的边界，
   L2 那 259 条 G9 拒绝里应有一部分是切词误拒。
6. **策展人复核流程** —— 464 条 L3 散文 `reviewed=false`；`alignment_review.json`
   与 `period_normalization.json` 均为 `machine_reviewed_pending_curator`。
7. **旧待办（仍未做）**——statement → 页面的确定性渲染 + 远端链接 resolver。
3. **L2 实现**——按 §4 的槽位填充与硬闸门。
4. **`inferred` 子层**——年代标签回填、尺寸解析（§4.6）。
5. **上游修复**——远端 exact-name 概念端点（§5.1）；网关约束违反的错误透传（§5.4）。
