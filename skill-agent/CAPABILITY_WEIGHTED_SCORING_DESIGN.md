# 能力检查维度加权方案设计

> 基于 evidence_strength 的动态维度加权，解决 D/R 维度在能力检查阶段不可评估的问题。

---

## 1. 问题描述

### 1.1 背景

当前能力检查（capability_check）将 5 个维度等权平均，每个维度权重为 1.0：

`step_score = (I + D + O + R + C) / 5`

### 1.2 核心矛盾

5 个维度的**可评估性**并不平等：

| 维度 | 评估依据 | 能力检查阶段可见 | 可评估性 |
|------|---------|-----------------|----------|
| **I** 输入匹配 | query 文本 + 附件 | ✅ 完全可见 | 高 |
| **O** 操作能力 | SKILL.md 声明的命令/工具/流程 | ✅ 完全可见 | 高 |
| **C** 约束满足 | SKILL.md 声明的权限/范围/语言等 | ✅ 完全可见 | 高 |
| **D** 信息覆盖 | 数据库 schema / 外部服务数据 | ❌ 不可见 | **低** |
| **R** 结果匹配 | 数据库输出形态 / 外部服务返回格式 | ❌ 不可见 | **低** |

D 和 R 的真值只有在**实际执行后才能确认**。能力检查阶段 LLM 只能基于 `SKILL.md` 的声明做推测。当声明不完整（没有字段列表、没有主题清单、没有输出格式说明）时，D 和 R 的评分本质上是噪声。

### 1.3 问题影响

- **等权平均下，不可评估的维度占据 40% 的决策权重**（D + R = 2/5）
- D/R 的一个错误评分可以翻转 `can_handle` 的结论（0.8 ↔ 0.6）
- 依赖外部数据/服务的 agent 受害最严重——它们不可能在声明里穷举所有可能的字段/主题

---

## 2. 方案核心思路

**让 LLM 自我标注每个维度评分的证据强度，代码端按证据强度动态分配权重。**

具体来说：

- 在 `RatioCheck` schema 中新增 `evidence_strength` 字段，LLM 为每个维度的评分标注 `solid`（有据）或 `speculative`（推测）
- `solid` 维度保持全权重（1.0），`speculative` 维度降权（0.1）
- O 维度（操作能力）天然 `solid`，不走 RatioCheck 的 evidence_strength 标注流程

### 2.1 加权公式

```
step_score = (I*W_I + D*W_D + O*W_O + R*W_R + C*W_C) / (W_I + W_D + W_O + W_R + W_C)

其中：
  W_dim = 1.0   当 evidence_strength == "solid"
  W_dim = 0.1   当 evidence_strength == "speculative"
  W_O   = 1.0   始终（O 是三档评分，不经过 RatioCheck，依据始终明确）
```

### 2.2 设计原则

1. **LLM 决定权重的分配，代码只执行算术** — 不引入外部 hard-coded 分类规则
2. **粒度是 per-step × per-dimension** — 同一 agent 的不同步骤、同一步骤的不同维度可以有不同权重
3. **speculative 不意味权重为 0** — 保留 0.1 的微小信号，防止 D=0/R=0 的明确否定信号被完全忽略
4. **证据强度不进入任何额外链路** — 不影响 evidence_grade（后者仍是全局 A/B/C/D）、不影响 routing 侧的任何过滤逻辑

---

## 3. Schema 变更

### 3.1 `RatioCheck` 新增字段

在现有的 `required`、`matched`、`ratio` 三个字段之外，新增第四个字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `evidence_strength` | `"solid"` \| `"speculative"` | 该维度评分的证据强度。solid = 依据来自技能正文明确声明（字段列表、主题清单、输出格式、排除项、数据同步周期等）；speculative = 依据来自 Agent 描述或技能短描述推断，正文中无对应具体声明 |

### 3.2 `StepEvaluation` 不变

`StepEvaluation` 已有 `input_match: RatioCheck`、`data_coverage: RatioCheck`、`result_match: RatioCheck`、`constraint_satisfaction: RatioCheck` 四个字段，新增的属性自动继承。

### 3.3 输出协议变更

在 capability_check 响应的 `steps[].checklists` 中，每个维度（I/D/R/C）的子结构新增 `evidence_strength` 字段。示例：

```json
{
  "step_id": 1,
  "checklists": {
    "D": {
      "required": ["商品名", "下单时间"],
      "matched": ["商品名", "下单时间"],
      "evidence_strength": "solid"
    },
    "R": {
      "required": ["商品列表"],
      "matched": [],
      "evidence_strength": "speculative"
    }
  }
}
```

### 3.4 与 `evidence_grade` 的关系（共存，非替代）

两者是**共存关系**，在粒度、用途、消费方三个维度上完全不同：

| | `evidence_grade`（已有） | `evidence_strength`（新增） |
|---|---|---|
| **粒度** | **全局** — 整个 `CapabilityCheckResult` 只有一个 | **维度级** — 每个步骤的每个维度（I/D/R/C）各一个 |
| **取值** | A / B / C / D | solid / speculative |
| **用途** | 告诉 routing 侧"这个 agent 的整体自评有多可信" | 告诉代码端"这个维度的评分该不该参与加权" |
| **消费方** | routing 侧：排序（第二优先级）、快速路径信任门槛、LLM planner 引导 | 代码端：`step_score()` 加权计算 |
| **影响** | 不影响分数，只影响 ranking 和路径决策 | **直接影响分数**（决定维度权重是 1.0 还是 0.1） |
| **现有/新增** | **现有**，保持不变 | **新增**，本方案引入 |

两者在输出 JSON 中的位置关系：

```
CapabilityCheckResponse
├── evidence_grade: "A"              ← 已有，不变：全局 A/B/C/D
├── handle_score: 0.85
└── steps:
    └── [0]:
        ├── step_id: 1
        ├── checklists:
        │   ├── I: { required:[], matched:[], evidence_strength:"solid" }
        │   ├── D: { required:[], matched:[], evidence_strength:"solid" }
        │   ├── R: { required:[], matched:[], evidence_strength:"speculative" }
        │   └── C: { required:[], matched:[], evidence_strength:"solid" }
        └── evidence: ["技能正文：字段 订单ID|商品名|...", ...]
```

**一个具体例子**：

agent 的全局 `evidence_grade = "C"`（routing 侧看到后：排序降级 + 不让他走快速路径），但在步骤 1 的 I 维度 `evidence_strength = "solid"`（代码端：这个维度的 ratio 权重 1.0，正常参与加权），D 维度 `evidence_strength = "speculative"`（代码端：这个维度的 ratio 权重 0.1，降权）。

两者各自解决各自的问题，互不冲突。

### 3.5 向后兼容

新增字段为可选，旧版消费者（routing 侧）仅解析已有字段，不受影响。`score_version` 保持不变（`"capability-chain-v1"`），不升级版本号。

---

## 4. Prompt 变更

在 `SKILL_CAPABILITY_CHECK_PROMPT` 中，为每个比例维度的打分指令新增 `evidence_strength` 标注要求。

### 4.1 I — 输入匹配

```
### I 输入匹配
- 定义：该步骤所需输入，问题或上一步给了多少。
- 打分：列出所需输入项；逐项判断是否已提供且类型 / 模态可用；I = 可用项 / 所需项。
- evidence_strength：
  · solid：依据来自问题原文中的具体值（如"张三"）、用户附件中的具体文件、
          或技能正文中明确声明的输入条件与支持的输入格式
  · speculative：仅能根据 Agent 描述或问题上下文推断输入是否可用
```

### 4.2 D — 信息覆盖

```
### D 信息覆盖
- 定义：该步骤要读写的信息需求项，技能的数据源 / 知识源里有多少。
- 打分：列出所需信息项；逐项在技能正文声明的覆盖范围中核对；D = 命中项 / 所需项。
- evidence_strength：
  · solid：依据来自技能正文中的明确字段列表、数据格式说明、覆盖主题清单
          及明确的排除项声明；如果正文明确写"不包含 X"，X 记未命中的依据也是 solid
  · speculative：正文仅有概括描述（如"可查询订单信息"、"公司内部文档问答"）
                而无具体字段/主题清单；或完全依赖 Agent 描述做推断
- 注意：D 的 evidence_strength=solid 仅代表"核对依据清晰"，
       不代表答案一定存在（数据实例问题仍写入 risks）
```

### 4.3 R — 结果匹配

```
### R 结果匹配
- 定义：该步骤要产出的项 / 形态，技能的输出能满足多少。
- 打分：列出期望产出项（含形态要求）；逐项判断技能能否输出该项及该形态；
       R = 可产出项 / 期望项。
- evidence_strength：
  · solid：依据来自技能正文中明确的输出字段、返回格式、输出形态说明
  · speculative：正文仅有概括描述（如"返回查询结果"）而无具体输出格式；
                或完全依赖 Agent 描述
```

### 4.4 C — 约束满足

```
### C 约束满足
- 定义：问题里显式或隐含的限定条件，技能能满足多少。
- 打分：列出该步骤的约束项；逐项对照技能正文；C = 满足项 / 约束项。
       没有约束时 required 为空、ratio = 1.0。
- evidence_strength：
  · solid：依据来自技能正文明确声明的数据同步周期、读写权限、数据范围、
          支持的语言/版本等
  · speculative：未找到对应声明的约束判断（如正文未声明支持英文，
                仅因工具可处理文本就推测"英文可处理"）
- 正文没有声明能满足的约束记为不满足，evidence_strength 仍可标 solid
  （不满足的依据是"正文未声明"这一事实，不是推测）
```

### 4.5 打分总则新增一条

```
- evidence_strength 强制要求：每个 RatioCheck 必须标注 evidence_strength = solid 或 speculative。
  不能所有维度都标 solid 或都标 speculative，必须逐个维度独立判断。
```

---

## 5. 效果分析

### 5.1 全 solid 场景：不受影响

设计文档 case 12.1 "张三买了哪些东西 — user-agent"，SKILL.md 有完整字段列表。

| 维度 | 分值 | evidence_strength | 当前权重(1.0) | 新权重 |
|------|------|-------------------|--------------|--------|
| I | 1.0 | solid | 1.0 | 1.0 |
| D | 1.0 | solid | 1.0 | 1.0 |
| O | 1.0 | — | 1.0 | 1.0 |
| R | 1.0 | solid | 1.0 | 1.0 |
| C | 1.0 | solid | 1.0 | 1.0 |

**结论**：全 solid，权重完全不变，step_score 不受影响 = **1.0**。

### 5.2 依赖外部数据的编排型 Agent

agent 描述仅有概括声明（"转发到下游服务，聚合结果返回"），无具体字段列表和输出格式。

| 维度 | 分值 | evidence_strength | 新权重 |
|------|------|-------------------|--------|
| I | 1.0 | solid（问题文本已给） | 1.0 |
| D | 1.0 | **speculative**（无字段列表） | **0.1** |
| O | 1.0 | solid（转发+聚合在正文有描述） | 1.0 |
| R | 1.0 | **speculative**（无输出格式声明） | **0.1** |
| C | 1.0 | solid（无约束） | 1.0 |

**效果**：

- 当前公式：`(1.0+1.0+1.0+1.0+1.0)/5 = 1.0`
- 新公式：`(1.0×1.0 + 1.0×0.1 + 1.0×1.0 + 1.0×0.1 + 1.0×1.0) / (1.0+0.1+1.0+0.1+1.0) = 3.2/3.2 = 1.0`

得分 1.0 仍然合理，因为 I/O/C 全是满分——声明里能判断的部分确实没问题。关键是：**LLM 的乱猜不会再颠覆结果。**

### 5.3 LLM 打分不一致时的稳定性对比

同一个编排型 agent，LLM 一轮乐观猜 D=1.0/R=1.0，另一轮悲观猜 D=0.0/R=0.0：

| | D/R 全满分 | D/R 全零分 | 波动幅度 | 是否被 D/R 主导 |
|---|---|---|---|---|
| 当前（等权） | 1.0 | 0.6 | ±0.20 | ✅ 是 |
| 新方案（降权） | 1.0 | 0.9375 | ±0.03 | ❌ 否 |

**D/R 的猜测从 ±0.20 的波动缩窄到 ±0.03，不再主导最终分数。**

---

## 6. 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| LLM 倾向于标 solid，导致降权失效 | Prompt 中明确"不能所有维度都标 solid 或都标 speculative，必须逐个维度独立判断"；通过测试回放验证 |
| LLM 未输出 evidence_strength（字段缺失） | 防御代码降权为 speculative(0.1)，不崩溃；日志记录 warning 用于监控 |
| evidence_strength 输出不一致（同一 case 多次评估不同） | speculative 权重 0.1 已是较小值，solid/speculative 的翻转只影响 0.1 ↔ 1.0，比当前 1.0 ↔ 1.0（无差异）要好 |
| 全 speculative 的 agent 得分虚高 | I/O/C 通常有明确的声明或工具列表，极少全部 speculative。实际运行中监控全 speculative 的 case 占比 |

---

## 7. 与现有机制的关系

| 现有机制 | 是否受影响 | 说明 |
|---------|-----------|------|
| `evidence_grade`（A/B/C/D） | 不改变 | evidence_grade 是**全局**可信度（整个 agent 的评分整体有多可靠），evidence_strength 是**维度级**可信度。两者正交互补 |
| `handle_score` 阈值 0.7 | 语义可能变化 | 新公式下 speculative 维度多的 agent 得分更稳定，handle_score 的分布发生变化。阈值 0.7 需在实际运行中验证是否需要微调，但每个 speculative 维度的降权幅度（0.1→1.0 权重差）足够小，预期仍适用 |
| routing 侧过滤（0.5/0.6/0.78） | 不直接受影响 | confidence 是 handle_score 或 max(step_score)，新公式只改变了这些值的计算方式，不影响 routing 侧的使用方式 |
| `can_handle` 判定 | 可能受益 | 外部依赖 agent 的 D/R speculative，分数更稳定，减少了因 LLM 猜测波动导致的 can_handle 翻转 |
| `can_contribute` 判定 | 同上 | contributing_steps 中如果 D/R 是 speculative，step_score 更稳定 |
| `score_version` | 不变 | 仍为 `"capability-chain-v1"`，向下兼容 |
| 输出协议 | 新增可选字段 | 旧版消费者忽略新增字段，不报错 |

---

## 8. 改动文件清单

| 文件 | 改动内容 | 改动范围 |
|------|---------|---------|
| `agent/capability_chain.py` | `RatioCheck` 新增 `evidence_strength` 字段；`step_score()` 从等权平均改为加权平均 | Schema + 一个函数 |
| `agent/skill_agent.py` | `SKILL_CAPABILITY_CHECK_PROMPT` 中 I/D/R/C 的打分指令各加一段 `evidence_strength` 标注标准；打分总则中新增一条强制要求 | Prompt 文本 |
| routing-agent 侧 | 无需改动 | 新增字段为 JSON 可选字段，向下兼容 |

---

## 9. 后续可扩展点

- **speculative 权重可环境变量化**：如果 0.1 在线上表现偏激进或偏保守，可通过环境变量调整
- **evidence_strength 可反馈到 evidence_grade**：如果大部分维度都是 speculative，evidence_grade 可自动降低（目前由 LLM 独立判断，不做强关联）
- **路由侧可消费 evidence_strength**：steps JSON 中已包含该字段，如果 future routing 需要"这个贡献步骤的能力评分是否有据"这一信息，已有可用数据