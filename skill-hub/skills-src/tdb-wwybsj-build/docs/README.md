# wwybsj 域设计文档

`wwybsj` 是从馆藏文物登记表建起来的本地 TDB 域。它的目标不是"把远端考古语料抄一份
过来"，而是**建一个能用来推理的本体**，远端知识靠标识符引用。

| 文档 | 内容 |
|---|---|
| [layered-ontology.md](layered-ontology.md) | 分层设计主文档：核心论点、L0/L1/L2/L3 与投影层、全域不变式、十六道闸门、验收查询、五类应用任务的可行性判定 |
| [predicate-registry.md](predicate-registry.md) | 全部谓词清单：类型约束、代数性质、值形状、14 项校验 |

配套实现在 `../scripts/`：

```
wwybsj_ingest.py   登记记录 → provenance 事件（L0 的证据锚点）
wwybsj_l0.py       登记事实 → observed statements（已建成）
wwybsj_l1.py       受控词项 → 远端概念簇锚点（已建成）
wwybsj_research.py 远端四层检索，只读（L2 的检索前端）
wwybsj_l2.py       研究性断言（槽位填充 + 九道闸门）
wwybsj_l3.py       展品描述段（七道闸门，散文作为数据）
wwybsj_wiki.py     wiki 投影层（确定性渲染 + --verify-determinism）
wwybsj_l2_report.py L2 产出与闸门统计
wwybsj_predicates.py 谓词契约注册 + 14 项校验
wwybsj_common.py   共享辅助
```

契约与裁决数据（全部是数据，不是硬编码）：

- `../predicate_contract.json` —— 32 个谓词的契约，校验器的唯一真相来源
- `../alignment_review.json` —— L1 对齐裁决，每条带远端原文证据
- `../period_normalization.json` —— 年代标签归并规则（31 → 20）

操作手册在 `../SKILL.md`。

## 一句话状态

```
L0    9678 条   465 件文物 · 23 谓词 · 全部 observed，全部有登记事件引用
L1     112 条    56 词项（category 10 / material 10 / period 20 + 管理类 16 不对齐）
                 465 / 465 件文物有远端概念通路
L2    1394 条   502 条研究性断言 + 892 条可查询缺口 · 引用闭环 502/502
L3     464 条   展品描述段 · reviewed=false · extraction_text=false
wiki   465 页   compiled_summary · 确定性验证逐字节通过
契约    32 谓词 · 14 项校验全过
```

**已交付的应用**：展品介绍（465 页，含国家/文化/朝代背景，经锚点解引用不复制）。
**结构性不可行**：自动发掘报告——本域零出土语境。
