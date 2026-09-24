# SG 透传路径上对齐 skill-agent 两阶段能力检查

> **版本**: v0.3  
> **日期**: 2026-09-21  
> **状态**: 设计讨论，**先不定稿实现**  
> **范围**: 现有投递路径保持不变：SG Orchestrator → SG Expert → SD Orchestrator  
> **参考实现**: `dac/skill-agent/agent/skill_agent.py` 的 `handle_capability_check`  
> **本文目标**: 不改投递路径，只改 **SD 侧**判定方案——先领域匹配，匹配成功后再做真正的能力检查。

---

## 0. 先说结论

**路径不变，方案在 SD 对齐 skill-agent。**

routing 打到 SG 的 `capability_check`，仍然走今天的主路径，**中间不加任何 SG 级领域判定**：

```text
SG Orchestrator.handle_capability_check
  → _delegated_member_capability_check
    → SG Expert（message_type=group_member_capability_check）
      → fan-out 每个成员
           SD Orchestrator（message_type=member_capability_check）
             Phase 1 领域匹配（本 SD 完整库存）
             none → 立刻拒绝，不进入 Phase 2
             has / uncertain → Phase 2 能力链打分 → 代码 aggregate()
      → Expert 聚合 member_results
  → SG 签发 CapabilityCheckResponse + execution_hint
```

要改的不是「谁来接这个请求」，也不是「SG 先挡一道再决定打不打 SD」。要改的是 **SD 真正做判定时用的方案**：从旧的一次性 `judge_member_capability`（领域、能否处理、confidence 混在一次 tool-call 里），改成 skill-agent 已经落地的两阶段。

收益：

1. **更准、更稳**：叶子 SD 握有完整能力信息（表结构、字段、文档摘要、descriptor），领域匹配和能力打分都基于这份正文；routing 拿到的分数与 skill-agent 可比。
2. **更省 token**：领域无关的 SD 只付一次轻量领域判定，不再跑重型能力链（也不再跑现在那份很长的旧 judge）。组内多数成员通常与当前问题无关，这是主要的费用差。

**明确拒绝在 SG 做领域闸门。**  
语义组没有完整能力信息，description 上的 `【data_inventory】` 通常只是表名聚合，不足以判断「跟不跟这个问题同域」。在 SG 层提前判 `none` 会误杀只在某个成员库存里才看得见的面；判 `has` 也没有增量信息，检查权本来就要交给 SD。因此 SG 继续只做接收和透传，**所有领域匹配与能力检查都在 SD 完成**。

本期也不把 SG 本层 `_chain_scoring_capability_check` 抬成默认。它继续只当 sidecar 失败 / degraded 时的回退。

---

## 1. 约束与非目标

### 1.1 必须遵守

- SG Orchestrator 继续接收 `capability_check`，然后 **无条件**交给 SG Expert 透传到各 SD。不在透传前做领域匹配、能力打分或短路 fan-out。
- 真正的领域匹配和能力检查都在 SD Orchestrator 完成，依据是该 SD 从 DataServices 拉到的完整库存。
- `member_results` / `execution_strategy` / `collaboration_*` / `execution_hint.selected_members` 继续由这条路径产出。
- SD 判定方法论与 skill-agent 对齐：先领域匹配，成功后再能力检查；结论由代码公式出，不由 LLM 直接报布尔。

### 1.2 明确不做

- **不在 SG 层做领域闸门。** 语义组没有完整能力信息，SG 级 `none`/`has` 不可信，也不节省「该打的 SD」。
- 不把默认主路径改成 SG 本层 `_chain_scoring_capability_check`。
- 不删除 Expert fan-out，不删除 `member_capability_check` 接口。
- 本期不改 routing-agent 广播 / 排序。
- 本期不改 Expert 聚合的大框架（有 handler 取最高分、多 contributor 可升 collaboration）。叶子分数换成公式分之后，聚合输入质量变了，规则本身先不动。若上线后发现聚合把公式结论改坏，再单独立项。

---

## 2. 现状：路径是对的，叶子方案是旧的

### 2.1 现行投递（完整保留，含「总是 fan-out」）

```text
routing 广播 capability_check
  → SG handle_capability_check
      默认 SG_MEMBER_CAPABILITY_CHECK_ENABLED=true
      → A2A SG Expert sidecar
           metadata.message_type = group_member_capability_check
      → Expert.check_group_member_capability
           对每个成员并发：
             SD  → member_capability_check
             嵌套 SG → capability_check（对方再走自己的透传）
      → _aggregate_member_capabilities
      → SG 填 execution_hint，对外返回
```

这条路径的价值在于：**SG 作为对等路由节点，接单信号来自组内真实成员的完整库存证据**，并且能带回 `selected_members` 给后续执行。SG 自己没有这份证据，所以不能在透传前代替叶子做判断。

### 2.2 为什么领域匹配不能放在 SG

| | SG 看得见的 | SD 看得见的 |
|--|-------------|-------------|
| 描述 | 组级业务域一句话 + 聚合 `tables=[...]` | `semantic_domain` 全文、排除项 |
| 结构 | 通常无字段 | `tables_detail`、列、实体名 |
| 非结构化 | 无 per-file 摘要 | `file_summaries` |
| 代码仓 | 无 | file/symbol/service 摘要 |
| descriptor 类型 | 组内混杂 | 本 DD 的 structured / unstructured / code |

skill-agent 的 Phase 1 之所以可靠，是因为判定依据是 **完整 skill 正文**。SD 的 metadata 才是对应物。SG 的聚合清单不是对应物：

- 组清单里没有的字段，某个 SD 可能有 → SG 判 `none` 会误杀。
- 组清单里有表名，不代表任一 SD 覆盖问题的那一面 → SG 判 `has` 不能代替叶子闸门，fan-out 还是要做。
- 组内只有部分成员相关，这正是要 **每个 SD 自己做 Phase 1** 的原因，不是 SG 先挡一道的原因。

因此「skill-agent 先领域匹配再能力检查」对齐的位置是 **每个 SD**，不是 SG。

### 2.3 现行 SD 判定（要换掉）

`orchestrator_agent_semantic_domain.py` 的 `handle_member_capability_check`：

1. 从 DataServices 拉 signature / semantic_domain / 非结构化 file_summaries。
2. `_build_member_capability_context` 压成 metadata 摘要。
3. `_judge_member_capability_with_llm`：一份长英文 system prompt（D1–D10 anchoring / peer-anchor）+ tool `judge_member_capability`。
4. LLM **一次**输出 `domain_match`、`can_handle`、`can_contribute`、`confidence`、`reason`、`matched_evidence`。
5. `_normalize_member_capability_judgment` 只做 `domain_match=false` 则两个 can 都 false 的一致性修补。

这和 skill-agent **已经淘汰**的旧能力检查是同一代：

| | SD 旧 judge | skill-agent 现行 |
|--|-------------|------------------|
| 领域 vs 能力 | 混在一次调用 | 强制两阶段，领域失败不进能力评估 |
| 结论由谁出 | LLM 直接出布尔和 confidence | LLM 只出清单和比例，代码 `aggregate()` |
| 领域取值 | bool `domain_match` | `has` / `none` / `uncertain` |
| 能力模型 | 主题重合 + 主实体启发式 | 步骤链 I/D/O/R/C + `evidence_strength` 加权 |
| 失败短路 | 无，每个 SD 都跑完整 judge | `none` 立即返回 |
| Prompt | 长英文决策序，按 descriptor 分支 | 中文四步拆面规程 |

旧 judge 的问题：

- 领域无关时仍然要消化整份 metadata + 长 prompt，token 浪费最大的就是这里。
- `confidence` 没有清单，无法和 skill-agent 的公式分横向比。
- 「像这个域」经常被写成 `can_handle=true`；「能贡献 join 键」和「能独立完成」分不清。
- 正文明确不覆盖时，没有 D=0 solid 硬门槛。

SG 本层其实已经有一份 `SG_DOMAIN_CHECK_PROMPT` + `SG_CHAIN_CAPABILITY_CHECK_PROMPT`，仅用于透传失败回退。**本期不把它抬成默认，也不拿来做透传前闸门。** 规程和 `capability_chain.py` 公式下沉到 SD，由握有完整库存的叶子执行。

---

## 3. 参考：skill-agent 必须对齐的部分（在 SD 落地）

代码：`skill-agent/agent/skill_agent.py` → `handle_capability_check`。  
公式：`skill-agent/agent/capability_chain.py`（仓库里已有同构拷贝 `orchestrator_agent/capability_chain.py`）。

skill-agent 是单 Agent：一份完整 skill 正文，一次两阶段。  
SG 是组：没有一份完整正文，所以 **每个 SD 各做一次与 skill-agent 同构的两阶段**，再由 Expert 聚合。这是「方案一致」而不是「在 SG 再演一遍 skill-agent」。

### 3.1 流程（每个 SD）

```text
Phase 1  DOMAIN_CHECK_PROMPT
         只问：本 SD 库存跟这个问题有没有关系，值不值得进入后续能力评估
         输出 domain_verdict + reason
              │
     none ───► 立刻 cannot_handle，不调 Phase 2
     has / uncertain
              │
              ▼
Phase 2  CAPABILITY_CHECK_PROMPT
         注入 domain_info（Phase 1 结论）
         拆步骤，打 I/D/O/R/C
         禁止再判领域，禁止输出结论布尔
              │
              ▼
         capability_chain.aggregate()
```

### 3.2 Phase 1 闸门语义（SD 必须原样遵守）

- **相关 (`has`)**：能独立处理整题，**或**只能处理其中一面 / 解析 join 键 / 作为相邻环节参与。单领域和跨领域同一条规则。
- **无关 (`none`)**：问题里每一面都落在本 SD 声明之外，也不是解题所需的身份或键解析环节。
- **不确定 (`uncertain`)**：声明模糊，既不能确认也不能否认能否参与 → **进入 Phase 2**，不要在 Phase 1 当拒绝。
- **明确不问**：能不能一个人做完、是不是「主域」、过滤键齐不齐、正文有没有「交给别人」。

四步规程：拆面 → 逐面只问「能处理或能参与」→ 排除项只作用于被点名的那一面 → 命中面非空则只能是 `has`。

### 3.3 Phase 2 职责边界

- 领域交集已经判过，只负责拆步骤和打分。
- 不输出 `can_handle` / `can_contribute` / `confidence` / `domain_verdict`。
- 注入 Phase 1 的 `domain_info`。
- 禁止因为本 SD 只覆盖某类表就把问题改写成自己能做的题。

### 3.4 代码公式（直接复用，不新发明）

```text
step_score     = weighted-arithmetic-mean(I, D, O, R, C)
                 solid=1.0，speculative=0.1；O 始终 solid
can_handle     = 每个步骤 step_score ≥ 阈值
                 且没有本 Agent 无法自行产出的 upstream / missing
can_contribute = can_handle，或存在某步 ≥ 阈值
confidence     = 能独立完成 → handle_score
                 只能贡献   → 贡献步骤最大值
                 都不能     → 0
硬门槛         = 所有步骤 D=0 且 solid → 直接 cannot_handle
```

---

## 4. 推荐方案：路径保持，两阶段只在 SD

### 4.1 目标时序

```text
routing → SG.handle_capability_check
            │
            │  不做领域匹配、不做能力打分、不短路
            ▼
          SG Expert fan-out（现行路径，原样保留）
            │
            ├─ SD-A  handle_member_capability_check
            │     拉本 SD 完整 metadata
            │     Phase 1 领域匹配
            │       none → 返回 cannot_handle，跳过 Phase 2
            │       has / uncertain → Phase 2 链打分 → aggregate()
            │
            ├─ SD-B  同上
            ├─ SD-C  同上
            │
            ▼
          Expert 按现行规则聚合
            → SG 签发 execution_hint
            → 对外 CapabilityCheckResponse
```

「先领域匹配再能力检查」只发生在 SD。SG 不扮演判定器。

### 4.2 Token 账（省的是 SD 的 Phase 2，不是少打 SD）

假设某 SG 有 6 个 SD，routing 广播打到该 SG：

| 场景 | 现状 | 本期（SD 两阶段） |
|------|------|-------------------|
| 6 个 SD 均无关 | 6 × 旧 judge（长 prompt + 全量 metadata，领域和能力缠在一起） | 6 × Phase 1（短 JSON：`domain_verdict`+`reason`），**0 × Phase 2** |
| 其中 1 个 SD 同域 | 6 × 旧 judge | 6 × Phase 1 + **1 × Phase 2** |
| 单次成本 | 几乎总是满额 | 无关叶子在 Phase 1 停；只有同域叶子付链打分 |

省 token 的主因：不相干的叶子 **不再进入能力链**。调用次数仍是 N（路径要求每个 SD 用自己的完整库存说话），但 N 次里大部分从「旧满额 judge」变成「轻量领域 JSON」。这和 skill-agent 把 DOMAIN_CHECK 拆出去的原因相同，位置在叶子。

---

## 5. SD Orchestrator 两阶段设计（本期全部范围）

改造入口：`handle_member_capability_check`。前面拉 metadata 的逻辑保留；从 `_judge_member_capability_with_llm` 起替换。

### 5.1 仍由 DataServices 准备评估文本

继续用现有：

- `search_signatures_by_dd` / `search_semantic_domains_by_dd`
- 非结构化再拉 `list_unstructured_files_by_dd` → `file_summaries`
- `_build_member_capability_context` 作为 Phase 1 / Phase 2 的「技能正文」等价物

这是 SD 能做领域匹配的前提：正文完整。metadata 拉失败、完全无签名时的空响应逻辑保持。

评估依据优先级（写入 prompt，对齐 skill-agent「正文 > 短描述 > Agent 描述」）：

1. 库存正文：`tables_detail` / 字段、`file_summaries`、代码仓 file/symbol 摘要
2. `semantic_domain` 声明与排除项
3. AgentCard description / skills
4. 用户问题原文与历史
5. Phase 2 额外注入的 `domain_info`

禁止靠 Agent 名称或「同行业应该有」补字段。descriptor 类型（structured / unstructured / code）只影响 D/R 清单里「项」是什么，**不**再分成三套互斥的英文决策序。

### 5.2 Phase 1：`SD_DOMAIN_CHECK_PROMPT`

从 skill-agent `DOMAIN_CHECK_PROMPT` 改编，角色换成「SD 领域相关判定员」。评估对象是 **本 SD 的完整库存**，不是组级描述。

输出：

```json
{ "domain_verdict": "has", "reason": "领域交集：明确有 — …" }
```

取值：`has` | `none` | `uncertain`。  
解析用现成 `capability_chain.DomainCheckResult`。

代码：

- `none` → 立刻构造成员响应：`can_handle=false`，`can_contribute=false`，`confidence=0`，`domain_match=false`，`domain_verdict=none`，`steps=[]`，不调 Phase 2。
- `has` / `uncertain` → 进入 Phase 2，并把 verdict+reason 填进 `domain_info`。
- JSON 无效则 nudge 重试，次数与 skill-agent 相同（`CAPABILITY_CHECK_MAX_ATTEMPTS`，默认 3）。耗尽则该成员 `cannot_handle`，reason 标明 `domain_check_failed`，**不要**掉回旧 `judge_member_capability`。

闸门示例（写进 prompt 的判例方向，不是 few-shot 业务题）：

- 问题要订单状态，本 SD 库存是订单表 → `has`（能独立给这一面）。
- 问题要「张三买了什么」，本 SD 只有用户表 → `has`（能参与：用户名 → user_id），不要因为走不完购买链就 `none`。
- 问题是工伤认定，本 SD 是商品域 → `none`。
- 文档 SD 对「某字段业务含义」且 file_summaries 能对上 → `has`；对「查一条线上订单记录」→ `none`（live record 不是文档域的面）。

### 5.3 Phase 2：`SD_CHAIN_CAPABILITY_CHECK_PROMPT`

从 skill-agent `SKILL_CAPABILITY_CHECK_PROMPT` 改编，对象换成「本语义域的数据/文档/代码库存」。

必须写上、且代码要注入 `{domain_info}`：

```text
领域交集前置检查已由另一模块完成，你只需负责步骤拆分与逐维度打分。
你不负责：判定 can_handle / can_contribute / confidence。
你不负责：判定领域交不交叠。
```

不要带 SG 回退 prompt 里的「§〇 领域交集复查」。每个 SD 的领域只判一次。

维度在 SD 上的读法：

| 维 | SD 怎么核 |
|----|-----------|
| I | 问题或上一步是否给了本步输入（时间表达式自包含） |
| D | 本步信息项在 `tables_detail` / file_summaries / 代码摘要里命中多少 |
| O | 本 SD 声明的查询/检索/抽取能力是否覆盖该操作；只读域遇到 modify → 0 |
| R | 能否产出该步所需形态（行、列表、摘要、条款列表等） |
| C | 时效、权限、范围等；正文没声明则不满足 |

结构化 / 非结构化 / 代码用同一套维度，清单里的「项」不同：字段 vs 主题/文档 vs 文件/符号。不要再维护三套 D1–D10 英文规则。

LLM 输出 `CapabilityChainResult`（steps、evidence_grade、contribution、missing_requirements、risks、reason）。  
代码 `capability_chain.aggregate()` 得到 `can_handle` / `can_contribute` / `confidence`。  
若模型仍夹带 `domain_verdict`，`pop` 掉。

Phase 2 失败：该成员 cannot_handle，保留 Phase 1 `domain_verdict`，reason 标明 `chain_check_failed`。同样禁止回退旧 judge。

### 5.4 成员响应：新旧字段怎么接

Expert 今天认的是旧成员 JSON。两阶段结果 **映射进旧字段，同时带上新字段**，避免先改 Expert。

| 成员 JSON 字段 | 来源 |
|----------------|------|
| `can_handle` / `can_contribute` / `confidence` | `aggregate()` |
| `reason` | Phase 2 reason；Phase 1 即停则用领域 reason |
| `domain_match` | `domain_verdict in ("has", "uncertain")`（旧布尔兼容） |
| `domain_verdict` | Phase 1，新增 |
| `matched_evidence` / `matched_entities` | Phase 2 各步 D.matched 去重截断；领域即停则为空 |
| `matched_tables` | 能从 matched 里识别出的表名则填，否则空列表 |
| `missing_requirements` | aggregate |
| `score_version` | `capability-chain-v1` |
| `evidence_grade` / `handle_score` / `threshold` / `steps` / `contributing_steps` / `risks` | 链打分 |
| `has_external_dependency` | aggregate |
| `evidence_mode` | `"capability_chain"`（旧值 `"llm"` 表示旧 judge） |
| `descriptor_type` / `agent_name` / `agent_url` | 现行 |

`_normalize_member_capability_judgment` 不再做「LLM 漏了 can_handle 就用 domain_match 顶上」——公式已经给出 can_handle。`uncertain` 只表示领域闸门放行，**不**等于 can_handle。

Expert `_normalize_member_capability` 对未知字段忽略即可；`domain_match`、`can_handle` 仍按现逻辑读。`steps` 可以原样留在 `member_results` 里给日志和 `execution_hint` 用，Expert 聚合可以暂时不读。

### 5.5 删除或降级的 SD 旧代码

实现时：

- `_capability_judge_system_template` / `MemberCapabilityJudgeResult` / `_judge_member_capability_with_llm` / `_normalize_member_capability_judgment` 不再出现在主路径。
- 可暂时留文件，用开关 `SD_MEMBER_CAPABILITY_LEGACY_JUDGE=true` 紧急回滚；默认 false。稳定后删除。
- **不要** Phase 失败时静默调用旧 judge，否则两阶段没有意义。

---

## 6. SG Orchestrator / Expert：投递与聚合，不做判定

### 6.1 SG `handle_capability_check`

保持现行默认：`SG_MEMBER_CAPABILITY_CHECK_ENABLED=true` → `_delegated_member_capability_check`。

- 调用 Expert 之前 **不加** 本层 `SG_DOMAIN_CHECK_PROMPT`。
- 不加 `SG_CAPABILITY_DOMAIN_GATE` 之类开关。
- sidecar 不可用 / `degraded=true` → 仍回退 `_chain_scoring_capability_check`（现行行为）。回退不是主路径，见 §8。

### 6.2 Expert 聚合：先不改规则，只吃更好的叶子

现行 `_aggregate_member_capabilities`：

- 有 `can_handle` 成员 → 取 confidence 最高者，SG `can_handle=true`，`strategy=single`。
- 否则多个有证据的 contributor 且缺口能对上 → `collaboration` 且 SG `can_handle=true`。
- 否则只有部分贡献 → SG `can_contribute=true`，`can_handle=false`。

叶子改成公式分之后：

- `confidence` 是 handle_score 或贡献步最大值，排序比旧 LLM 自报分更稳。
- 领域 `none` 的成员是干净的 unsupported，不再带着 0.3～0.5 的噪声分挤进 contributor。
- `matched_evidence` 来自 D.matched，collaboration 的证据对齐会更真。

本期不改聚合启发式。需要观察的点：公式 `can_handle=true` 但 `has_external_dependency=true` 按设计应为 false；若模型乱标 source，仍可能出现假 handler。靠 Phase 2 prompt 和 aggregate 硬规则约束，不在 Expert 再写一套。

`execution_hint` 继续由 SG `_build_execution_hint` 从 `member_results` 生成。领域即停的成员 `role=unsupported`，不会进 `selected_members`。

---

## 7. 回退路径（非主路径，仅 sidecar 失败时）

`_chain_scoring_capability_check` 只在透传失败时出现，用的是组级粗清单，准确度低于 SD 两阶段。这是可用性回退，不是等价实现。

若顺手修，避免回退比主路径还旧：

- Phase 2 注入 `domain_info`。
- 删掉 `SG_CHAIN_CAPABILITY_CHECK_PROMPT` 的「§〇 领域交集复查」。
- Phase 失败不要再掉进 `CAPABILITY_CHECK_PROMPT` 那套名称匹配 tool-call。

这些 **不是** 把判定搬回 SG，可以和 SD 两阶段同一个 PR，也可以拆。不做也不阻塞本期：主路径不经过这里。

---

## 8. 例子

### 8.1 整组无关

问题：「工伤认定流程」  
SG：订单域，6 个订单相关 SD

- **现状**：6 次旧 judge。
- **本期**：仍 fan-out 6 个 SD；每个 Phase 1 用自己的订单库存判 `none`；**0 次 Phase 2**。
- SG 不提前判。避免「组描述像电商、某个成员其实有 HR 文档」这类误杀；本例里即使组描述像订单，也由每个 SD 的正文说了算。

### 8.2 组内一主一辅

问题：「张三买了哪些东西」  
SD-user：用户表；SD-order：订单表；SD-payment：支付表；另 3 个无关 SD

- SG：直接透传，不做 has/none。
- SD-user：Phase 1 `has`（用户名面）→ Phase 2 两步，只能贡献 user_id → `can_handle=false`，`can_contribute=true`。
- SD-order：Phase 1 `has`（购买面）→ Phase 2 在缺 user_id 时暴露外部依赖或只覆盖订单侧 → 多为 contribute；若问题已带订单号则可能 handle。
- SD-payment 及无关 SD：Phase 1 `none`，跳过 Phase 2。
- Expert：按 handler/contributor 聚合，`selected_members` 只留下真正相关的叶子。

### 8.3 文档 SD vs 线上记录

问题：「订单 ORD-001 当前状态」  
文档 SD 的 corpus 有字段说明；结构化订单 SD 有订单表。

- 文档 SD：Phase 1 对 live record 判 `none`（或进入 Phase 2 但 O/D 为 0）。活记录不是文档域的面时，应在 Phase 1 就 `none`。
- 订单 SD：Phase 1 `has` → Phase 2 lookup 高分 → handle。

旧 judge 靠大段英文「live record lookups belong to structured agents」约束，容易和领域判定缠在一起。两阶段里这只是拆面后的「该面是否在本 SD 声明内」。

---

## 9. 开关、兼容、发布

| 变量 | 建议默认 | 含义 |
|------|----------|------|
| `SG_MEMBER_CAPABILITY_CHECK_ENABLED` | **true（保持）** | 主路径仍透传，不在 SG 做领域判定 |
| `SD_MEMBER_CAPABILITY_LEGACY_JUDGE` | false | true 时 SD 走旧 judge，紧急回滚 |
| `CAPABILITY_CHECK_MAX_ATTEMPTS` | 3 | SD 各 Phase 的 JSON 重试 |
| `CAPABILITY_CHAIN_THRESHOLD` | 0.7 | 与 skill-agent 共用 |

**不增加** `SG_CAPABILITY_DOMAIN_GATE`。

对外：

- SG 仍回答 `capability_check`，schema 不删字段。
- SD 仍回答 `member_capability_check`；新增 `domain_verdict` / `steps` / `score_version` 等，旧消费者可忽略。
- `domain_match` 继续存在，由 `domain_verdict` 推导。

发布建议：

1. SD 两阶段替换旧 judge，默认关闭 legacy。
2. 用现有 `test_sd_member_capability_llm_live*` 的题库对照：领域无关应稳定 `none` 且无 Phase 2 日志；同域接单方向与旧 judge 大体同向，confidence 改为公式分。
3. 观察 Expert 聚合后的 `selected_members` 是否仍合理。
4. 旧 judge 代码稳定后删除。

---

## 10. 代码落点（实现时，本文不改代码）

| 位置 | 改动 |
|------|------|
| `orchestrator_agent_semantic_domain.py` | **主改动**：`handle_member_capability_check` 改为 Phase1+Phase2；新增 SD 两份 prompt；主路径不再调旧 judge |
| `orchestrator_agent/capability_chain.py` | SD 直接 import 复用，公式不动 |
| `orchestrator_agent_semantic_group.py` `handle_capability_check` | **不改控制流**；继续默认透传 |
| `expert_agent_semantic_group.py` | 聚合规则先不动；日志可打印 `domain_verdict` / `score_version` |
| `broadcast_capability_check.py` | 不改 |
| `tests/test_sd_member_capability_check.py` 及 live 题库 | 断言两阶段、none 不进 Phase 2 |
| `tests/test_member_capability_check.py` | 默认仍透传；不增加「SG 闸门跳过 sidecar」用例 |

---

## 11. 测试计划

1. **SD 领域 none 短路**：Phase 1 `none` 时 Phase 2 LLM 零调用；`domain_match=false`，`can_handle=false`，`can_contribute=false`。
2. **SD uncertain 放行**：必须进 Phase 2，prompt 含 `domain_verdict: uncertain`；can_handle 由公式决定，不得仅因 uncertain 变 true。
3. **SD 跨域贡献**：用户域 SD + 「张三买了什么」→ contribute 而非 handle。
4. **SD 同域独立完成**：订单 SD + 「订单状态」→ handle，且 `steps` 非空、`score_version=capability-chain-v1`。
5. **禁止回退旧 judge**：人为让 Phase 2 JSON 失败，不得出现 `judge_member_capability` tool-call。
6. **SG 仍总是透传**：`handle_capability_check` 在 ENABLED 默认下必然调用 `_delegated_member_capability_check`，不因 query 领域看起来无关而跳过。
7. **透传失败回退**：sidecar 挂时仍走 `_chain_scoring_capability_check`。
8. **Expert 聚合回归**：一 handler + 若干 none → `selected_members` 只有 handler；全 none → SG cannot_handle。
9. **execution_hint**：仍能从新 `member_results` 签发。

---

## 12. 待评审拍板

1. **旧 judge 是否留紧急开关？** 推荐留一个版本周期。
2. **Expert 聚合是否跟手改？** 推荐本期不动。若公式分 + 旧 collaboration 升级规则打架，再单独立项。
3. **嵌套 SG 成员**：Expert 对嵌套 SG 发的是 `capability_check`。对方 SG 同样只透传、由对方的 SD 做两阶段。不必给 Expert 开特例，也不在中间 SG 做领域闸门。
4. **回退路径 prompt 是否同期修？** 可选，不阻塞 P0。

不再把「SG 闸门要不要同期做」列为选项。

---

## 13. 一句话

SG 只负责收请求并经 Expert 传到每个 SD；SD 用自己的完整库存做 skill-agent 同款两阶段——先领域匹配，匹配成功后再链打分。组级不做领域判断，因为语义组没有完整能力信息。省 token 来自无关 SD 跳过 Phase 2，不是来自少打 SD。
