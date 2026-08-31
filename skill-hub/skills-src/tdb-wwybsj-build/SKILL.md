---
name: tdb-wwybsj-build
description: >
  Use when adding a WWYBSJ artifact from registry JSON, building or rebuilding
  the local `wwybsj` cultural-relic TDB domain, auditing its layered ontology,
  aligning controlled terms to the remote archeology corpus, or verifying the
  generated wwybsj statements and wiki pages through gateway APIs.
---

# tdb-wwybsj-build — 文物登记数据 → 自建 TDB 域

把 `jf_ww_demo` 文物登记表的每一条记录，做成 `wwybsj` 域里一个有证据支撑的知识条目。

**核心纪律：这个 skill 不产生知识，它搬运并标注知识。** 每一条写进 `wwybsj` 的
研究性结论，都必须能指回远端语料的一段原文；指不回去的，就如实写"本域无支撑"，
不许用常识补位。检索纪律沿用 `.codex/skills/tdb-archeology-answering/SKILL.md`。

---

## 1. 两套 TDB，务必分清

物理分离，逻辑可连。**研究读远端，写入只写本地。**

| | SOURCE（研究源） | TARGET（构建目标） |
|---|---|---|
| Gateway | `http://10.124.48.91:8989` | `http://10.124.48.91:8997` |
| domain | **`archeology`** | **`wwybsj`** |
| 权限 | **只读**，一个字节都不许写 | 读写 |
| 环境变量覆盖 | `WWYBSJ_SOURCE_GATEWAY` | `WWYBSJ_TARGET_GATEWAY` |

**两端都只有网关，没有数据库。** 本 skill 不持有任何 Postgres 连接串，脚本里没有
一行 SQL，也不调用 `psql`。读和写走同一个 `10.124.48.91:8997`。这不是洁癖：过去
「网关写、psql 读」的双通道，在网关被指向另一个库的那一刻就把域**静默劈成了两半**
——经网关写进去的 statement 对所有 psql 读者不可见（详见第 6 节第 8 条）。单一通道
意味着这种不一致在结构上不可能发生。

代价要如实知道：网关能表达的读比 SQL 少。所有读取原语集中在
`scripts/wwybsj_common.py` 的 "Gateway reads" 一节，聚合一律在 Python 里做。

开工前先确认两端都活着：

```bash
curl -s http://10.124.48.91:8989/health && echo && curl -s http://10.124.48.91:8997/health
```

两端都应返回 `{"status":"ok","service":"tdb-gateway","version":"v2"}`。
本地网关**无鉴权**，直接裸 HTTP 调用即可。

### 远端语料是什么

全是中文考古/文博专著，正是文物登记数据需要的对照系。

`domain-stream/list` 报 **100 个 active binding**，但 `/search/query` 实际解析出的
`resolved_stream_ids` 是 **331 个**——binding 列表**不等于**可检索范围，别拿它当
语料清单用。以 binding 列出的书目：

| 章节数 | 书目 |
|---|---|
| 24 | 中国博物馆学基础 (fundamentals_of_chinese_museology) |
| 15 | 中国古代金属技术：铜和铁造就的文明 |
| 15 | 文物学 (cultural_relics_studies) |
| 12 | 陶瓷工艺学 (ceramic_technology) |
| 11 | 中国古代简史（至1840） |
| 10 | 考古测量学 (archaeometry) |
| 8  | 中国古代文化常识 |
| 5  | 中国古代建筑史（第二版） ← 繁简混排，见第 7 节 |

检索时还会命中 binding 里没有的书：《考古学导论（第二版）》《中国建筑史》
《新石器时代考古》《民族考古学导论》《田野考古工作规程》《中国艺术考古学导论》
《文化遗产学》等。要知道某次检索到底覆盖了什么，看返回的 `resolved_stream_ids`，
不要看 binding 列表。

### ⚠️ 三个必须避开的域名陷阱

1. **远端只有 `archeology`**。查 `archeology_expert` 或 `Archaeology` 返回空
   binding、空 wiki——不是没数据，是域名不存在。
2. **本地的 `archeology_expert` 是另一套语料**（《世界文明史》《世界古代史》
   教科书，38953 页 wiki）。它对中国地方文物**没有覆盖**：用记录 8（渤海绿釉
   柱础护圈）实测，最高分命中全是 PDF 目录页。**不要拿它做研究源。**
3. 本地还有 `archeology` / `Archaeology` 两个域，页面是 `夸耀`/`部分`/`使得`
   这类词级垃圾页，是历史遗留，忽略。

同一个 query 在两端的差距（记录 8，"绿釉 柱础 建筑构件 陶质 渤海"）：

- 本地 `archeology_expert`：最高 0.188，内容是 `CONTENTS`（目录页）
- 远端 `archeology`：0.148 命中「**綠琉璃蓮花柱礎　寧安渤海國**」——同类器直接证据

---

## 2. 数据源

- 原始 SQL：`/Users/ningwu/eis/a2a/agents/wwybsj/wwybsj.sql`（表 `jf_ww_demo`，文物基础信息表）
- 已转 JSON：`/Users/ningwu/eis/a2a/agents/wwybsj/wwybsj.json` —— **465 条**，34 字段的扁平对象数组
- 转换脚本：`/Users/ningwu/eis/a2a/agents/wwybsj/sql_to_json.py`
- 中间产物：`/Users/ningwu/eis/a2a/agents/wwybsj/out/`

字段含义见 `scripts/wwybsj_common.py` 的 `FIELDS` 字典。注意原 SQL 里数值字段
（`ww_chang`/`ww_zhiliang_jt` 等）本身带引号，JSON 里保留为字符串。

---
## 3. 分层架构

本域是**为推理而建的本体**，不是把远端背景抄过来的文集。远端知识靠标识符引用，
不复制——这既省空间，也修正了断言主体：「受唐代技术影响」是关于*工艺传统*的断言，
不是关于某一件具体器物的。

```
        L0  登记事实        467 件 × ~20 条    确定性生成，无 LLM
            observed        wwybsj_l0.py       typed 值 + 登记事件引用
              │
              │  instantiates / made_of  →  wwybsj.term.<facet>.<值>
              ↓
        L1  锚点边          58 个词项（41 可对齐）  同名概念簇 + SKOS relation
            inferred        wwybsj_l1.py       + 复核裁决（数据，非硬编码）
              │
              │  aligned_to  →  archeology:concept:<uuid 簇>
              ↓
        远端 archeology 域（只读，按需解引用；一条事实都不复制过来）
```

推理路径实例：

```
wwybsj.artifact.0008
  --instantiates--> wwybsj.term.category.陶器 --aligned_to--> archeology 簇(20 个 id)
  --made_of------->  wwybsj.term.material.陶  --aligned_to--> archeology 簇(3 个 id)
远端由此可达：陶器 -uses_method-> 手制 / -requires_condition-> 700～960℃ / 殷墟 -consists_of-> 陶器
```

### 命名规则（血泪换来的，务必遵守）

裸谓词名如 `is_a` 在 `semantic_entity` 里是**全局单例**：`entity_id` 就是主键，而
upsert 带 `ON CONFLICT ... namespace = EXCLUDED.namespace`。曾经 wwybsj 写了一次
裸名 `is_a`，就把其他域 4700+ 条 statement 在用的公共谓词的归属标签抢成了 `wwybsj`。

```
文物个体      wwybsj.artifact.<藏品总登记号>
谓词          wwybsj.predicate.<name>
受控词项      wwybsj.term.<facet>.<登记值>
qualifier     wwybsj.qualifier.<key>
reference     wwybsj.ref.registry / wwybsj.ref.remote_concept
statement_key wwybsj/L0/<登记号>/<name>[/<disc>]   ·   wwybsj/L1/<term>/<name>[/<disc>]
              wwybsj/L2/<登记号>/<name>/<disc>    ·   wwybsj/L3/<登记号>/has_exhibit_prose
```

每条 statement 另外必须带 `metadata_json.domain='wwybsj'`。**域隔离绝不能只依赖
可变的 `namespace` 列**——清库时就是靠 `created_by` 和实体引用才挖出 18 条藏在
domain 标签之外的残留。

### 认知状态

| mode | 谁能产生 | 要求 |
|---|---|---|
| `observed` | **只有登记簿**。任何 LLM 都不许产生这一类 | 必带 `registry_field` + 登记事件 reference |
| `inferred` | 程序按可审计规则推出 | 必记规则与前提（L1 对齐属于此类）|
| `attributed` | 远端原文 | 必带 `stream_id`/`event_id`/`source_span`，缺一个就拒写 |
| `hypothesized` | 明确的猜测 | 默认不参与推理 |

---

## 3.1 接收一段 JSON：新文物入库

**这是本 skill 最常被调用的入口。** 用户给一段 wwybsj 格式的 JSON（一件新文物），
skill 把它跑完整条链路，变成有证据支撑的知识条目。

`wwybsj.json` 是登记表导出的**冻结快照**，不是工作文件。新藏品走**增量覆盖层**
`out/wwybsj_new_items.json`，`load_records()` 自动把 base + overlay 合并（同 `id`
以 overlay 为准），因此 ingest / L0 / L1 / L2 / L3 / wiki **一行代码都不用改**
就能看到新条目。覆盖层路径可用 `WWYBSJ_NEW_ITEMS` 覆盖。

**完成定义：新文物入库不是到 L1 就结束。** 对用户给的一条新 JSON，默认要做完整链路：
写覆盖层 → ingest → L0 → L1 → L2 → stance → L3 → wiki → 回读验证。除非用户明确说只要
登记事实或只到某一层，否则不要在 `wwybsj_new_item.py --execute --build` 后停手；
这个脚本当前只负责基础链路（ingest/L0/L1），后续层必须用下面的命令补跑。

### 直接粘贴 JSON（首选）

```bash
cd /Users/ningwu/eis/.codex/skills/tdb-wwybsj-build/scripts

# 先 dry-run 看解析结果和登记摘要
python3 wwybsj_new_item.py --json '{
  "ww_mingchen": "辽绿釉鸡冠壶",
  "ww_leibie":   "瓷器",
  "ww_zhidi_c":  "瓷",
  "ww_zhidi_b":  "无机质",
  "ww_niandai_jt": "辽(907~1125)",
  "ww_jibie":    "三级",
  "ww_laiyuan":  "征集购买",
  "ww_chicun":   "高23.5 口径5.2",
  "ww_zhiliang_jt": "1.2",
  "ww_zhiliang_dw": "kg"
}'

# 确认无误后写覆盖层并跑基础链路：ingest → L0 → L1
python3 wwybsj_new_item.py --json "$PAYLOAD" --execute --build

# 然后继续补齐研究层、说明文字、wiki 投影和验收（登记号按 dry-run 规范化输出）
python3 wwybsj_l2.py --registry-no <登记号> --execute
python3 wwybsj_stance.py --recompute --execute
python3 wwybsj_l3.py --registry-no <登记号> --execute
python3 wwybsj_wiki.py --registry-no <登记号> --execute
python3 wwybsj_verify.py --check q0
```

`--json` 吃四种形状，都是人会真的粘过来的：单个对象 · 对象数组 ·
`{"records": [...]}` · `{"data": [...]}`（`sql_to_json.py` 的输出形状）。
**其余一律报错退出**——解析错的载荷下游会变成 statement，一条半懂的记录进了域之后，
跟真记录就再也分不出来了。

字段可用原始列名（`ww_mingchen`），也可用中文别名（`名称`/`类别`/`质地`/`年代`/
`级别`/`来源`/`尺寸`/`质量`/`质量单位`/`质地大类`）。列名含义见第 2 节。

### 其他入口

```bash
# 行内字段，不写 JSON
python3 wwybsj_new_item.py \
  --set 名称=辽白釉刻花碗 --set 类别=瓷器 --set 质地=瓷 --set 质地大类=无机质 \
  --set "年代=辽(907~1125)" --set 级别=三级 --set 来源=征集 \
  --set "尺寸=口径15.2 高6.4" --set 质量=0.32 --set 质量单位=kg

# 文件或 stdin
python3 wwybsj_new_item.py --file new_items.json --execute --build
cat new_items.json | python3 wwybsj_new_item.py --file - --execute --build

python3 wwybsj_new_item.py --list           # 覆盖层里有什么
python3 wwybsj_new_item.py --remove 470 --execute   # 从覆盖层撤掉（不回滚已写入的 statement）
```

`--json` / `--file` / `--set` 三者互斥，一次只用一种。

`--build` 的实际链路只有：对每一件 `wwybsj_ingest.py --id <id> --execute` →
`wwybsj_l0.py --registry-no <登记号> --execute`，全部做完后 `wwybsj_l1.py --execute`
跑**一次**（词项是共享的；新件可能引入 base 465 里没有的类别/质地，需要重新解析锚点。
已解析的词项走缓存，很快）。只想看 L0 就加 `--no-l1`。

**不要把 `--build` 当成“完整建成”。** 它没有跑 L2/L3/wiki，也不会生成文物页。跑完
`--build` 后，继续逐件运行：

```bash
python3 wwybsj_l2.py --registry-no <登记号> --execute
python3 wwybsj_stance.py --recompute --execute
python3 wwybsj_l3.py --registry-no <登记号> --execute
python3 wwybsj_wiki.py --registry-no <登记号> --execute
```

如果 L2 或 L3 因 LLM、检索后端、超时失败，**不要降级写伪研究结论或伪展签**。报告停在哪一层、
失败原因、可重试命令；已经成功写入的低层事实保留。

脚本替你挡掉的坑：

| 行为 | 为什么 |
|---|---|
| 未知字段直接报错 | 拼错的键静默丢弃 = 半条记录被 L0 照样变成 statement |
| 藏品总登记号冲突就拒写 | 登记号是文物身份（`wwybsj.artifact.<登记号>`），撞号等于两件文物合并成一件 |
| 缺登记号/`id` 时自动取下一个空位 | base + overlay 一起算，不会撞上已有的 |
| 34 列全部补齐（数值列补 `0.00`/`0`） | `record_text()` 和 L0 的 typed 解析器只认 base dump 的形状 |
| 缺 `类别`/`质地`/`年代` 只告警不阻断 | 缺类别 = 没有 `instantiates` 边 = **L1 到远端无通路**，但这是登记事实，不许脑补 |
| 只给 `质地` 时补 `质地a=单一质地` | 与登记表惯例一致，免得多出一个孤立词项 |

写入前一定先看 dry-run 打印的**登记摘要**——那段文本就是进 provenance 流的原文，
后面每一条 L0 statement 都指着它。

---

## 3.2 全量建域的操作流程

### Step 1 — 登记记录入 provenance 流（一次性）

```bash
cd /Users/ningwu/eis/.codex/skills/tdb-wwybsj-build/scripts
python3 wwybsj_ingest.py --status
python3 wwybsj_ingest.py --all --execute      # 465 条，约 4 分钟
```

每条记录渲染成自足中文文本，`POST /v2/event/append` 到 stream `wwybsj.artifacts`，
并 bind 到 domain `wwybsj`。`event_id` 存进 `out/ingest_index.json`。
**没有这一步 L0 就没有证据锚点，脚本会直接拒绝运行。**

### Step 2 — L0 登记事实

```bash
python3 wwybsj_l0.py --registry-no 8          # 预览单条
python3 wwybsj_l0.py --all                    # 预览全量 + 写 plan JSON
python3 wwybsj_l0.py --all --execute          # 写入（幂等，重跑原地更新）
python3 wwybsj_l0.py --verify
```

22 个谓词，全部 `observed`。typed 值形如：

```json
"dated_to":      {"era_label":"唐","start_year":618,"end_year":907,"parse_status":"range_parsed","registry_literal":"唐(618~907)"}
"has_mass":      {"value":0.48,"unit":"kg","unit_source":"registry_column","normalized_g":480.0}
"has_dimension": {"dimension":"height","value":11.3,"unit":null,"unit_source":"unspecified"}
```

**`ww_chicun`（尺寸）故意不解析。** 它是自由文本（`存14.8*832*3.4`，832 明显是错值；
`存长:(大)20.2 (小)9 高(大)8(小)5.8 底厚` 还被截断），465 条里只有 13 条写了单位。
猜单位就是「柱础护圈高 2.1 米」的由来。原文照存 + 标 `unparsed_free_text` + 发数据
质量标记，解析留给可复核的独立步骤。

数据质量标记本身是**可查询的 statement**，不是日志：

```
335  dimension_only_in_free_text     287  period_label_without_years     129  dimension_unit_unspecified
```

### Step 3 — L1 锚点边

```bash
python3 wwybsj_l1.py                          # 解析 + 预览
python3 wwybsj_l1.py --execute
python3 wwybsj_l1.py --refresh                # 忽略 xref 缓存重解析
python3 wwybsj_l1.py --report
```

对齐挂在**词项**上不挂在文物上：58 个词项（`period`/`material`/`category` 三个
facet 共 41 个进入对齐）覆盖 467 件，所以是几十条断言而不是几千条，远端换版本时
只重解析这几十个。词项清单本身是从引用它们的 statement 反查出来的
（`load_term_usage()`），不再需要扫 `semantic_entity`。

裁决写在 `alignment_review.json`（**数据，不是硬编码**），每条带远端原文证据，
`reviewer` / `review_status` 如实标注，策展人可逐条推翻。三级控制：

| 机制 | 用途 |
|---|---|
| `confirm_exact` | 确认同名对齐 |
| `reject_exact` | **同形词否决**：`金` 的 4 个同名概念全是金朝（`-produced_by_culture-> 女真族`），`石` 的 2 个是容量单位（`十斗`）|
| `exclude_concept_ids` | 簇内单个垃圾成员排除：`铜` 簇里有一个 `甜饼 -consists_of-> 铜` |
| `align` + `relation` | SKOS 式 broader/narrower 映射：`铜器`→`青铜器`(narrower)、`金`→`金属`(broader) |

---

## 4. 物理分离、逻辑可连：簇锚点

概念**不共享存储**。L1 记的是远端**同名概念簇**，不是单个 id：

```json
{"matched_surface":"陶器","match_relation":"exact","concept_ids":[...20 个...],
 "primary_concept_id":"<字典序最小>","cluster_size":20,
 "cluster_completeness":"unknown_search_is_not_stable","search_result_truncated":true}
```

**为什么是簇而不是单个 id**：远端有大量未消解的同名概念——`漆器` 25 个、`铁器` 27 个、
`陶器` 20 个、`金银器` 11 个，而它们的事实集**不同**。取"第一个精确匹配"会静默丢掉
大部分可达知识（实测：`玉石器` 选中的成员没有「龙虬庄遗址」关联，`宝石` 选中的只有
巴洛克艺术噪声），而且 `concept/search` 结果顺序不保证，这个选择连复现都做不到。
实体消解是远端自己的债，本地不替它猜——**推理时 union 整簇**。

`primary_concept_id` 用字典序最小（与搜索顺序无关），仅用于显示和稳定键。

远端 `stream_id`/`event_id`/`concept_id` 在本地库没有对应行，**这是故意的**：
它们是回远端解析的句柄，不是本地外键。

---

## 5. Gateway API 速查（已实测确认）

### 研究用（远端，只读）

```
GET  /v2/wiki/search?domain=archeology&q=<term>&limit=N
GET  /v2/wiki/page?domain=archeology&slug=<slug>
GET  /v2/wiki/page/evidence?domain=archeology&slug=<slug>
GET  /v2/ontology/concept/search?q=<term>&limit=N
GET  /v2/ontology/relation-candidate/list?domain=archeology&subject_label=<t>&limit=N
GET  /v2/ontology/fact/list?stream_id=<sid>&limit=300&offset=N
GET  /v2/ontology/statement/get?statement_id=<sid>
GET  /v2/ontology/statement/provenance?statement_id=<sid>
GET  /v2/search/domain-stream/list?domain=archeology
POST /v2/search/query   {"domain":"archeology","query":"...","limit":N}
```

### 构建用（本地，读写）

**读回本域的全部原语**（`scripts/wwybsj_common.py` 已封装，不要另起一套）：

| 网关调用 | 封装 | 用途 |
|---|---|---|
| `GET /ontology/statement/list` | `list_statements()` | 按 subject / property / value_entity 分页拉全（`limit` 上限 **500**，`offset` 上限 **10000**）|
| 同上，按谓词遍历契约 | `load_domain()` | 全域快照，~40 次请求 / 12k 条 / **约 5 秒** |
| `GET /ontology/statement/get` | `get_statement()` | 单条 + qualifier |
| `GET /ontology/statement/provenance` | `statement_references()` | 单条的 reference 与 `source_span` |
| `GET /wiki/pages` · `/wiki/page` | `wiki_page_slugs()` · `wiki_page()` | 列页（只有摘要）· 取正文 |
| `GET /ontology/object-type/list` | `object_type_ids()` | `--register` 的前置 FK 检查 |
| `GET /ontology/relation-type/list` | `relation_types()` | `--report` |
| 由 `TERM_PREDICATES` 反查 | `load_term_usage()` | 词项清单 + 覆盖数 |
| `list_statements(has_registry_no)` | `all_registry_nos()` | 全部藏品登记号 |

三条要记住的边界：

1. **`statement/list` 没有 domain 过滤，也没有前缀过滤。** 全域扫描只能表达成
   「契约里声明的每一个谓词」——所以 `predicate_contract.json` 是**可执行的枚举依据**，
   不是装饰。库里有、契约里没有的谓词，按谓词扫是**看不见的**；这正是
   `wwybsj_predicates.py` 的 V1 检查改成**按 subject 扫**的原因。
2. **`statement/list` 默认隐藏 `rejected`/`deprecated`。** 本 skill 的封装统一传
   `status=all`：审计读不到被否决的行，就报不出它。
3. **没有批量读 reference 的端点。** 每条 statement 一次 `/statement/provenance`
   （实测 ~13 ms）。L0 的 9696 条全查约 2 分钟——`--validate` 的 V10 **不抽样**，
   因为抽样过的 provenance 检查会在一个并不闭环的域上报「闭环」。

写入路径：

```
POST /v2/ontology/semantic/upsert-batch      // 主写入路径
     {entities:[{entity_id, entity_kind(item|property), semantic_role,
                 namespace, status, property_datatype?, metadata_json}],
      statements:[{statement_key, subject_id, property_id, value_type,
                   value_entity_id?, value_json, status, confidence,
                   created_by, metadata_json}],
      qualifiers:[{statement_key, property_id, value_type, value_json, ordinal}],
      references:[{statement_key, property_id, value_type, value_json,
                   source_span?, ordinal}]}
     // 只返回计数，不返回 statement_id —— 自己按 key 推导
GET  /v2/ontology/statement/list?subject_id=&property_id=&status=&limit=
     // 默认排除 rejected/deprecated；status=all 看全部
GET  /v2/ontology/statement/get?statement_id=
GET  /v2/ontology/statement/provenance?statement_id=
POST /v2/ontology/statement/status  {statement_id, status, note?}
     // 按 id 改状态；upsert-batch 只能按 key 定位，够不到无 key 的行
POST /v2/ontology/concept/upsert
     {concept_id, canonical_name, concept_type, aliases?}   // wiki/搜索仍需要
POST /v2/event/append
     {stream_id, event_type, event_text, payload, valid_time}
POST /v2/search/domain-stream/bind   {domain, stream_id}
POST /v2/wiki/page
     {domain, slug, title, content, page_type, knowledge_level?,
      authority_kind?, tags?, confidence?, source_ref?, supersede?}
GET  /v2/wiki/page?domain=wwybsj&slug=<slug>
```

### 枚举取值（DB CHECK 约束，写错就 400/500）

- `page_type`: `entity` `concept` `source_summary` `comparison` `index` `log`
- `knowledge_level`: `fact_like` `topic_like` `concept_like` `generalization_like` `principle_like` `theory_like`
- `authority_kind`: `accepted_ontology` `compiled_summary` `methodology` `candidate_derived`
- `concept_type`: `entity` `event` `session` `time` `topic` `phrase` `location` `activity`
- fact `status`: `accepted` `candidate` `rejected` `needs_review` —— 没有 `proposed`

文物页用 `page_type=entity` + `knowledge_level=fact_like` +
`authority_kind=candidate_derived`。

### 本域使用的谓词

登记类（`basis: registry`，置信度高）：
`is_a`（类别）· `made_of`（质地）· `dated_to`（年代，qualifier 带 time）·
`has_property`（级别/数量）· `obtained_by`（来源）· `characterized_by`（完残/保存）

研究类（`basis: source_text`，须有远端原文）：
`related_to` · `distinguished_from` · `attributed_to_culture` · `found_at` ·
`excavated_at` · `has_feature` · `part_of` · `uses_method`

全部已在远端 `ontology_fact` 中在用，语义对得上。

---
## 6. 已知的坑（都踩过，别再踩）

1. **`GET /v2/ontology/fact/list` 不接受 `domain` 参数**。它的 querystring schema
   只有 `status/stream_id/stream_prefix/predicate/extractor/src_concept_id/
   dst_concept_id/limit/offset`。传 `domain=` 会被 Fastify **静默丢弃**，返回的是
   **全库事实**而不是域内事实。正确做法：先 `domain-stream/list` 拿到该域的
   stream 列表，再逐流 `fact/list?stream_id=`。`wwybsj_research.py` 已这么做。

2. **statement 层的 status 值域是** `proposed|extracted|reviewed|accepted|deprecated|rejected`，
   **没有 `retracted`**。用错名字不会报错，只会让过滤条件恒真而静默失效。
   （legacy `ontology_fact.predicate` 对 `ontology_relation_type` 有外键、必须先注册
   谓词——走 statement 后不再适用。）

3. **`concept/upsert` 要调用方自己提供 `concept_id`**，不会自动生成。L0/L1 已不再
   写 `ontology_concept`——本域是 statement-native 的，词项就是 `semantic_entity`
   里可读的前缀 id（`wwybsj.term.material.陶`），幂等性由 `statement_key` 保证。

4. **`ontology_concept` 表没有 domain 列**，概念全库共享。这正是要做 xref 而不是
   直接复用远端 UUID 的原因——本地库根本没有那些行。

5. **`relation-candidate/upsert` 不要传 `source_cluster_id`**，它要真正的 pipeline
   cluster UUID；传 RAG 的 `doc_id` 会触发外键违例 500。

6. **`wiki/search` 是子串匹配**，不是语义匹配。单个汉字探针（`陶`）会命中
   `立陶宛`/`熏陶`。`wwybsj_common.probes_for` 已过滤长度 < 2 的探针。

7. **RAG 会把 PDF 目录页排到最前**。`CONTENTS`/`目录` 那种块对任何 query 都高分，
   却不含任何论断。`wwybsj_research.is_noise` 会滤掉，被滤掉的**不许引用**。

8. **双通道（网关写、psql 读）已彻底删除——这一条是它留下的教训，不是现状。**

   曾经 L1 的词项清单、L2/L3 的输入、review、wiki 全是绕过网关直连 psql 读的，
   写入却全走网关。两者一旦不指向同一个库，域就**静默劈成两半**：经网关写进去的
   statement 对所有 psql 读者不可见，L1 以为词项不存在，覆盖度统计凭空少掉几千条。

   实际发生过两次。一次是网关从本地迁到 `10.124.48.92:5440/tdb` 后，脚本里硬编码的
   `127.0.0.1:5432/DataV2` 没跟着改（8 个文件各抄了一份）。另一次是迁库**按表拷、
   漏了 `semantic_*` 一组**——`wiki_page`(465)、`case_event_ledger`(930 事件)、
   `search_document` 都过去了，`semantic_entity` / `semantic_statement` /
   `statement_qualifier` / `statement_reference` 一行没过；现象是 wiki 页查得到、
   statement 全空。

   **现在不可能再发生**：只有一个 `TARGET_BASE`，读写同源，没有第二个坐标可以对不上。
   拷库或换网关后仍要校验一句，但它现在也走网关：

   ```bash
   python3 wwybsj_verify.py --check q0
   ```

   只看 wiki 页数会被骗过去——Q0 同时清点 L0/L1/L2/L3、文物数、词项数和 wiki 页数。

9. `/v2/search/query` 返回的正文字段是 **`content`**；但 `archeology_tdb` skill 的
   封装把它改名成 `chunk`。看清楚在用哪层。

10. **`concept/search` 是子串搜索，`limit` 不够就等于"不存在"**。
    `_resolve_source_concept` 曾用 `limit=10`：`铁器` 有 **27** 个精确同名概念，但在
    200 条子串匹配里排不进前 10，于是被判"远端没有铁器概念"，落到垃圾 wiki 页兜底。
    `铁器`/`石刻`/`瓷器`/`铜器`/`雕塑`/`铜`/`铁`/`金`/`石` 九个词面全因此误判。
    **`limit` 上限 200，超过返回 HTTP 400。** 下结论前先用 200 解析整簇。

11. **负结果绝不能缓存**。一次超时/400 与"真的不存在"在这一层无法区分，而 `sget`
    把错误也报成空结果。旧版 `lookup_source_concept` 把 miss 写成 `null` 永久冻结，
    `铁器` 的假阴性就是这么留下的。现在只缓存正结果，miss 每次多花一个请求且仅在
    进程内报告。幂等性不受影响：`statement_key` 由 `(登记号, 谓词, 对象)` 推导，
    **不含 xref**。

12. **同名不等于同义**。簇 union 会把同形词的事实一起拽进来——`金` 的四个同名概念
    全是金朝，照着对齐就会让金器 `-produced_by_culture-> 女真族`；`石` 的两个是
    容量单位（`十斗`）。必须逐簇看实际事实，用 `reject_exact` 否决。

13. **`semantic_role` 拼错只会得到裸 500**。该列受 CHECK 约束，literal 谓词的正确
    拼法是 **`datatype_property`**，不是 `data_property`。写错时网关返回
    `HTTP 500 INTERNAL_ERROR` 且无任何细节——约束违反被吞掉了。定位办法是把载荷
    最小化（连"只发 entities"都 500，就说明问题在实体上）。

---

## 7. 性能特征与排障

### 一条记录要跑多久

记录 8（9 个探针，`--rag-queries 4`，83 次 HTTP 调用）两次实测：**70 秒 / 118 秒**。

| 端点 | 单次耗时 | 说明 |
|---|---|---|
| `POST /search/query` | **3.5 – 24 秒** | 波动极大，见下 |
| `GET /wiki/search` | ~6 秒 | |
| `GET /wiki/page` | < 1 秒 | |
| `GET /ontology/*` | < 1 秒 | |

**`/search/query` 的耗时不是固定成本**：同样的查询实测在 3.5 秒和 24 秒之间波动，
取决于远端缓存和负载。所以不要按固定单价估算批量耗时，**按实测重估**。

即便如此它仍是唯一的瓶颈，`--rag-queries` 是**唯一值得调的旋钮**。默认 4 已经够用
（一条组合自然语言查询 + 三个最具体的探针）。曾经默认发全部 10 个探针，赶上慢的
时候单条记录要 4 分 46 秒，屏幕上又没有任何输出，看起来就像卡死了。

按 465 条估算，串行 **9 – 15 小时**（取决于远端状态）。批量前先想清楚要不要并发。

### 日志开关

脚本的进度和计时全部走 **stderr**，正常输出走 stdout，可以分开重定向：

```bash
python3 wwybsj_research.py --id 8 --save 2> research_8.log
```

| 环境变量 | 默认 | 作用 |
|---|---|---|
| `WWYBSJ_DEBUG=1` | 关 | 打印**每一次**调用的耗时 |
| `WWYBSJ_SLOW_SECS` | 3 | 超过多少秒算慢调用，实时打印 |
| `WWYBSJ_HTTP_TIMEOUT` | 25 | 单次请求超时。远端 search 常态 24 秒，**贴着默认值**，网络稍差就会触发重试让耗时翻倍。跑远端建议设 45 |

每次运行结束（**包括崩溃时**，走 `finally`）都会打印汇总：

```
elapsed 117.9s
HTTP: 83 calls, 117.9s total, 0 retries, 0 errors, 0 suspect timeouts
  slowest: 23.8s remote /search/query; 6.5s remote /wiki/search; ...
```

### ⚠️ 静默超时：最危险的失败模式

远端后端 gRPC deadline 是 30 秒。**超时后网关返回 HTTP 200 + 空结果集，而不是错误**。
这跟"这个概念确实没有数据"在响应上**完全无法区分**。

后果很严重：一次卡顿会被当成"该概念无覆盖"，进而把覆盖度评级压低，最后在 wiki 页
上写出"TDB 无支撑"——而实际上有。

脚本会检测这个形态（耗时 ≥28 秒 且 结果集为空），打印：

```
[SUSPECT TIMEOUT 30.1s] remote /ontology/fact/list — empty result after ~30s
backend deadline; treat as UNKNOWN, not as empty
```

并在响应里打上 `_suspect_timeout: true`。**看到这个就重跑，不要拿这次结果下结论。**

实测记录：`fact/list?stream_id=...&limit=300` 出现过一次 30.08 秒返回 0 条，同一查询
重跑三次均为 0.2–0.4 秒返回 5 条。是偶发后端卡顿，不是查询本身的问题。

### 常见现象 → 原因

| 现象 | 原因 |
|---|---|
| 看起来卡住不动 | 正在跑 `/search/query`，单次 24 秒。看 stderr 的 `[search i/N]` 行确认进度 |
| 覆盖度意外评成 `thin`/`none` | 先查有没有 suspect timeout；再看 `matched_terms` 是不是简繁不匹配漏配了 |
| `rag_hits_on_topic: 0` 但手工 curl 明明有命中 | 切题判定问题。检查 `match_ratio`/`matched_terms` 字段 |
| 大量 `dropped_as_toc_noise` | 正常。目录页对任何 query 都高分，本来就该丢 |

### 简繁混排：已解决

**问题范围**：实测广撒 40 块，繁体只集中在
`history_of_ancient_chinese_architecture_2nd_ed`（《中国古代建筑史（第二版）》，
7 块中 3 块），是该书转录自旧版的图版说明文字；其余书目全部简体。登记表则完全是
简体。所以繁简不匹配只在**建筑构件类文物**上致命——而柱础、瓦当、砖这些恰恰是
文物登记里的大类。

**解法**：切题判定前把文本折叠成简体。字表是 OpenCC 官方的 `TSCharacters`，
已内联为 `scripts/t2s_chars.json`（4105 条），**没有运行时依赖**。

方向很关键：**繁 → 简是多对一，可以无脑套用**；反方向（简 → 繁）是一对多有歧义的
（`发` → `發`/`髮`），本 skill 任何地方都**不做**反向转换。

```
折叠前：柱础 vs 柱礎  →  不匹配，证据被丢弃，覆盖度误判为 thin
折叠后：柱础 vs 柱础  →  匹配，ratio 1.00
```

字表缺失时会在 stderr 告警并降级（而不是静默按不匹配处理）：

```
WARNING: t2s_chars.json missing — traditional text will not match simplified
probes, so coverage will be UNDER-reported.
```

字表若需重建（OpenCC 升级时）：

```bash
pip3 download --no-deps -d /tmp/occ opencc-python-reimplemented
cd /tmp/occ && unzip -o -q *.whl -d occ_x
# 取 occ_x/opencc/dictionary/TSCharacters.txt，制表符分隔，多值行取首项
```

### ⚠️ 仍未解决：术语差异（与繁简无关）

字表是**字级**的，修不了**词级**的术语差异。实例：

| 登记表用词 | 语料用词 | 性质 |
|---|---|---|
| 绿釉 | 綠琉璃 | 琉璃=铅釉建筑陶，绿釉=绿色釉层，是同物异名 |
| 柱础护圈 | 柱礎 / 覆盆柱础 / 莲花柱础 | 登记名更细，语料用通名 |

这类要靠**第二轮人工补探针**，这也正是 Step 2 的第二轮不是可选项的原因：

```bash
python3 wwybsj_research.py --id 8 --probe "琉璃" --probe "覆盆柱础" --probe "上京龙泉府" --save
```

如果发现某类术语反复出现，考虑在 `wwybsj_common.ZH_EN_PROBES` 旁边加一张文物领域
同义词表。**但那是一份需要人工策划的领域资源，不要用机械映射糊弄。**

---
## 8. 全量重建

全量重建分两段：基础层较快，研究与展签层受远端检索和 LLM 影响，耗时不可按固定分钟数承诺。
完整重建要跑到 wiki 投影和验收，不要只跑前三步就报告完成。

```bash
cd /Users/ningwu/eis/.codex/skills/tdb-wwybsj-build/scripts
python3 wwybsj_ingest.py --all --execute
python3 wwybsj_l0.py --all --execute
python3 wwybsj_l1.py --execute
python3 wwybsj_l2.py --all --execute --resume
python3 wwybsj_stance.py --recompute --execute
python3 wwybsj_l3.py --all --execute --resume
python3 wwybsj_wiki.py --all --execute
python3 wwybsj_verify.py
python3 wwybsj_predicates.py --validate
python3 wwybsj_l2_report.py
```

增量（只新增几件，不重建）见第 3.1 节：先用 `wwybsj_new_item.py --execute --build`
完成 ingest/L0/L1，再按登记号跑 L2、stance、L3、wiki、verify。`--build` 名字历史包袱很重，
它不是全链路完成信号。

L0/L1/L2/L3 都幂等（`statement_key` 确定性 → uuid5 → 原地更新）。但**改了
`statement_key` 形状或 `EXTRACTOR` 版本号后，旧行不会被覆盖，只会停止再生**，
变成孤儿。两道防线：`wwybsj_l1.py --execute` 写完自检，
`wwybsj_verify.py --check q7` 按层清点 `created_by`（预期名单是脚本里的
`EXPECTED_EXTRACTORS`；L2 有两个写入者是正常的——`wwybsj_stance_v1` 会重写
`dating_corroboration`）。

**孤儿行没法用网关删。** v2 只有 `POST /v2/ontology/statement/status`，能把一条标成
`rejected` / `deprecated`（按 `statement_id`，不是 `statement_key`）：

```bash
curl -s -X POST http://10.124.48.91:8997/v2/ontology/statement/status -H 'Content-Type: application/json' -d '{"statement_id":"<uuid>","status":"deprecated","note":"orphaned by extractor bump"}'
```

真要物理删除，那是 DBA 动作，不在本 skill 权限内——**不要为此在脚本里加回数据库连接。**

### 验收查询（competency questions）

本体设计到「能回答这些」就算达标。查询已经从文档搬进脚本，因为写在 prose 里的
competency question 会被抄错，写进脚本的会被真的跑：

```bash
python3 wwybsj_verify.py                      # Q0/Q1/Q3/Q6/Q7 全跑，约 12 秒
python3 wwybsj_verify.py --check q3            # 只跑一项
python3 wwybsj_predicates.py --validate        # 契约 V1-V14，含逐条 provenance
python3 wwybsj_l2_report.py                    # L2 写了什么、拒绝写什么
```

| 检查 | 问的是什么 |
|---|---|
| Q0 | 分层清点：L0/L1/L2/L3 条数、文物数、词项数、wiki 页数。**拷库/换网关后必跑** |
| Q1 | 断代早于公元 300 年——需要 typed 区间，光有年代标签答不了 |
| Q3 | 一致性：同一年代标签被登记成互相矛盾的年份区间 |
| Q6 | 反向 join：远端概念 ← 本馆哪些藏品实例化了它 |
| Q7 | 孤儿 extractor 行 |

当前状态（网关 `10.124.48.91:8997`，按契约 32 个谓词扫得）：
L0 **9713** / L1 **120** / L2 **1394** / L3 **465**，共 **11692** 条；
**467 件**文物（465 + 2 件从 JSON 增量入库的 demo 件）· 词项 **58** 个 · wiki 页 **466**
（0466 那件的 wiki 页尚未渲染）；
锚点覆盖远端 concept id **341** 个，其中 **145** 个可从藏品经
`instantiates` / `made_of` 到达。契约 V1-V14 **全部通过**（含 L0 9696 条
provenance 逐条闭环）。

Q3 实际抓到的登记缺陷：**东周** 被登记成 `-770~-256` / `-257` / `-258` 三种区间。

---

## 9. 输出给用户时

报告要包含：

1. **这件文物是什么** —— 登记信息的可读版
2. **远端 TDB 说了什么** —— 分层引用，标明哪层给的
3. **覆盖度实话** —— 评级是什么，哪些结论弱支撑，什么没查到
4. **写了什么进 wwybsj** —— wiki slug、事实条数、复用了哪些远端概念（带 UUID）
5. **回读验证结果** —— 一律用网关读回来的实际状态，不要用 plan 文件里的意图：
   `wwybsj_verify.py` · `wwybsj_predicates.py --validate` · `wwybsj_l2_report.py`

不要把「检索到了」说成「证实了」。provenance 调用成功 ≠ 返回的原文支持这个论断。

同样地，**不要在这个 skill 里写 SQL**，也不要为了「就查一下」临时接一次 psql。
需要的读法要么已经封装在 `wwybsj_common.py` 的 Gateway reads 里，要么就该在那里加一个
——绕过去一次，第 6 节第 8 条那种静默劈裂就又有了入口。
