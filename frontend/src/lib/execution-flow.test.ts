import { describe, expect, it } from "vitest"
import {
  buildExecutionTree,
  dedupeExecutionFlowTasks,
  flattenTreeForTable,
  nodeStatusOf,
  parseExecutionFlowTask,
  originAgentOf,
  stageSortKey,
  treeRoleLabel,
  upsertExecutionFlowTask,
  type ExecutionFlowTask,
} from "./execution-flow"

function task(partial: Partial<ExecutionFlowTask> & Pick<ExecutionFlowTask, "execution_id">): ExecutionFlowTask {
  return {
    schema_version: "v1",
    turn: 1,
    stage: "pre_exec",
    agent: "user-agent",
    role: "initiator",
    task: "task",
    result: "ok",
    reason: "",
    parent_execution_id: null,
    delegated_by: null,
    run_id: "run",
    trace_id: "trace",
    user_id: "user",
    ...partial,
  }
}

/** Fixture from the 2026-09-14 15-column snapshot. */
const snapshot: ExecutionFlowTask[] = [
  task({
    execution_id: "own-1-user-agent-t1",
    agent: "user-agent",
    role: "initiator",
    task: "用户名(张三)→lookup→用户ID",
    result: "用户ID为 U001",
  }),
  task({
    execution_id: "pre-2-order-agent-t1",
    agent: "order-agent",
    role: "delegatee",
    task: "查询用户ID为 U001 的商品",
    result: "PROD-001、PROD-003、PROD-016",
    delegated_by: "user-agent",
  }),
  task({
    execution_id: "own-1-order-agent-t1",
    agent: "order-agent",
    role: "initiator",
    task: "用户ID U001→lookup→商品ID列表",
    result: "PROD-001、PROD-003、PROD-016",
    parent_execution_id: "pre-2-order-agent-t1",
    delegated_by: "user-agent",
  }),
  task({
    execution_id: "turn-summary-t1",
    stage: "turn_summary",
    agent: "user-agent",
    task: "Turn 1 评估结果",
    result: "success",
  }),
  task({
    execution_id: "final-answer-t1",
    stage: "final_answer",
    agent: "user-agent",
    task: "最终答案",
    result: "张三购买了3件商品",
  }),
]

describe("parseExecutionFlowTask", () => {
  it("parses a valid v1 payload", () => {
    const parsed = parseExecutionFlowTask({
      schema_version: "v1",
      execution_id: "own-1",
      turn: 1,
      stage: "pre_exec",
      agent: "user-agent",
      role: "initiator",
      task: "lookup",
      result: "U001",
      parent_execution_id: null,
    })
    expect(parsed?.execution_id).toBe("own-1")
    expect(parsed?.turn).toBe(1)
    expect(parsed?.parent_execution_id).toBeNull()
  })

  it("rejects non-v1 schema and missing required fields", () => {
    expect(parseExecutionFlowTask({ schema_version: "v2", execution_id: "x", turn: 1, stage: "pre_exec", agent: "a", role: "initiator", task: "t" })).toBeNull()
    expect(parseExecutionFlowTask({ schema_version: "v1", turn: 1, stage: "pre_exec", agent: "a", role: "initiator", task: "t" })).toBeNull()
  })

  it("treats empty parent_execution_id as null", () => {
    const parsed = parseExecutionFlowTask({
      schema_version: "v1",
      execution_id: "own-1",
      turn: "1",
      stage: "pre_exec",
      agent: "a",
      role: "initiator",
      task: "t",
      parent_execution_id: "",
    })
    expect(parsed?.turn).toBe(1)
    expect(parsed?.parent_execution_id).toBeNull()
  })
})

describe("buildExecutionTree + flattenTreeForTable", () => {
  it("hangs own-1-order-agent-t1 under pre-2-order-agent-t1", () => {
    const tree = buildExecutionTree(snapshot)
    expect(tree.map((n) => n.execution_id)).toEqual([
      "own-1-user-agent-t1",
      "pre-2-order-agent-t1",
      "turn-summary-t1",
      "final-answer-t1",
    ])
    const delegate = tree.find((n) => n.execution_id === "pre-2-order-agent-t1")
    expect(delegate?.children.map((c) => c.execution_id)).toEqual(["own-1-order-agent-t1"])
  })

  it("dedupes history duplicates so the parented rewrite replaces the root copy", () => {
    const tree = buildExecutionTree([
      task({ execution_id: "own-1-user-agent-t1", agent: "user-agent", role: "initiator" }),
      task({
        execution_id: "own-1-order-agent-t1",
        agent: "order-agent",
        role: "initiator",
      }),
      task({
        execution_id: "pre-2-order-agent-t1",
        agent: "order-agent",
        role: "delegatee",
        delegated_by: "user-agent",
      }),
      task({
        execution_id: "own-1-order-agent-t1",
        agent: "order-agent",
        role: "initiator",
        parent_execution_id: "pre-2-order-agent-t1",
        delegated_by: "user-agent",
      }),
      task({
        execution_id: "turn-summary-t1",
        stage: "turn_summary",
        agent: "order-agent",
        task: "Turn 1 评估结果",
        result: "success",
      }),
      task({
        execution_id: "turn-summary-t1",
        stage: "turn_summary",
        agent: "order-agent",
        task: "Turn 1 评估结果",
        result: "success",
        parent_execution_id: "pre-2-order-agent-t1",
        delegated_by: "user-agent",
      }),
      task({
        execution_id: "turn-summary-t1-user",
        stage: "turn_summary",
        agent: "user-agent",
        task: "Turn 1 评估结果",
        result: "success",
      }),
    ])
    expect(tree.map((n) => n.execution_id)).toEqual([
      "own-1-user-agent-t1",
      "pre-2-order-agent-t1",
      "turn-summary-t1-user",
    ])
    const wrapper = tree.find((n) => n.execution_id === "pre-2-order-agent-t1")
    expect(wrapper?.children.map((c) => c.execution_id)).toEqual([
      "own-1-order-agent-t1",
      "turn-summary-t1",
    ])
  })

  it("reparents a previously root initiator after parent_execution_id is rewritten", () => {
    const first = [
      task({ execution_id: "own-1-product-agent-t1", agent: "product-agent", role: "initiator" }),
      task({
        execution_id: "pre-2-product-agent-t1",
        agent: "product-agent",
        role: "delegatee",
        delegated_by: "order-agent",
      }),
    ]
    expect(buildExecutionTree(first).map((n) => n.execution_id)).toEqual([
      "own-1-product-agent-t1",
      "pre-2-product-agent-t1",
    ])
    const rewritten = upsertExecutionFlowTask(
      first,
      task({
        execution_id: "own-1-product-agent-t1",
        agent: "product-agent",
        role: "initiator",
        parent_execution_id: "pre-2-product-agent-t1",
        delegated_by: "order-agent",
      }),
    )
    const tree = buildExecutionTree(rewritten)
    expect(tree.map((n) => n.execution_id)).toEqual(["pre-2-product-agent-t1"])
    expect(tree[0]?.children.map((c) => c.execution_id)).toEqual(["own-1-product-agent-t1"])
  })

  it("flattens in DFS pre-order matching the tree", () => {
    const rows = flattenTreeForTable(buildExecutionTree(snapshot))
    expect(rows.map((r) => [r.execution_id, r.indentLevel])).toEqual([
      ["own-1-user-agent-t1", 0],
      ["pre-2-order-agent-t1", 0],
      ["own-1-order-agent-t1", 1],
      ["turn-summary-t1", 0],
      ["final-answer-t1", 0],
    ])
  })

  it("puts turn_summary after all execution roots of that turn and final_answer last", () => {
    const mixed: ExecutionFlowTask[] = [
      task({ execution_id: "own-1-user-agent-t1", agent: "user-agent", role: "initiator" }),
      task({
        execution_id: "turn-summary-t1",
        stage: "turn_summary",
        agent: "user-agent",
        task: "Turn 1 评估结果",
        result: "success",
      }),
      task({
        execution_id: "final-answer-t1",
        stage: "final_answer",
        agent: "user-agent",
        task: "最终答案",
        result: "done",
      }),
      task({
        execution_id: "pre-2-order-agent-t1",
        agent: "order-agent",
        role: "delegatee",
        delegated_by: "user-agent",
      }),
    ]
    const rows = flattenTreeForTable(buildExecutionTree(mixed))
    expect(rows.map((r) => r.execution_id)).toEqual([
      "own-1-user-agent-t1",
      "pre-2-order-agent-t1",
      "turn-summary-t1",
      "final-answer-t1",
    ])
  })

  it("keeps final_answer after later-turn execution even if the final node is turn 1", () => {
    const mixed: ExecutionFlowTask[] = [
      task({ execution_id: "own-t1", turn: 1, agent: "user-agent" }),
      task({
        execution_id: "final-t1",
        turn: 1,
        stage: "final_answer",
        agent: "user-agent",
        task: "最终答案",
        result: "done",
      }),
      task({ execution_id: "own-t2", turn: 2, agent: "order-agent" }),
    ]
    expect(flattenTreeForTable(buildExecutionTree(mixed)).map((r) => r.execution_id)).toEqual([
      "own-t1",
      "own-t2",
      "final-t1",
    ])
  })

  it("treats missing parents as roots", () => {
    const tree = buildExecutionTree([
      task({ execution_id: "child", parent_execution_id: "missing-parent" }),
    ])
    expect(tree).toHaveLength(1)
    expect(tree[0]?.execution_id).toBe("child")
  })

  it("does not sort siblings by execution_id alphabet (product before user)", () => {
    const tree = buildExecutionTree([
      task({ execution_id: "own-2-user-agent-t1", agent: "user-agent" }),
      task({ execution_id: "own-1-product-agent-t1", agent: "product-agent" }),
      task({
        execution_id: "pre-3-order-agent-t1",
        agent: "order-agent",
        role: "delegatee",
        delegated_by: "user-agent",
      }),
    ])
    expect(tree.map((n) => n.agent)).toEqual(["user-agent", "product-agent", "order-agent"])
  })

  it("keeps the delegating agent first even if product was seen first", () => {
    const tree = buildExecutionTree([
      task({ execution_id: "own-1-product-agent-t1", agent: "product-agent" }),
      task({ execution_id: "own-2-user-agent-t1", agent: "user-agent" }),
      task({
        execution_id: "pre-3-order-agent-t1",
        agent: "order-agent",
        role: "delegatee",
        delegated_by: "user-agent",
      }),
    ])
    expect(tree.map((n) => n.agent)).toEqual(["user-agent", "product-agent", "order-agent"])
  })

  it("orders SG t1-pre-{agent}-{id} siblings by planner id not agent name", () => {
    const tree = buildExecutionTree([
      task({ execution_id: "t1-pre-product-agent-2", agent: "product-agent" }),
      task({ execution_id: "t1-pre-user-agent-1", agent: "user-agent" }),
    ])
    expect(tree.map((n) => n.execution_id)).toEqual([
      "t1-pre-user-agent-1",
      "t1-pre-product-agent-2",
    ])
  })
})

describe("dedupe / upsert", () => {
  it("keeps last payload per execution_id in first-seen order", () => {
    const deduped = dedupeExecutionFlowTasks([
      task({ execution_id: "a", result: "1" }),
      task({ execution_id: "b", result: "2" }),
      task({ execution_id: "a", result: "3" }),
    ])
    expect(deduped.map((t) => [t.execution_id, t.result])).toEqual([
      ["a", "3"],
      ["b", "2"],
    ])
  })

  it("replaces in place on upsert", () => {
    const next = upsertExecutionFlowTask(
      [task({ execution_id: "a", result: "old" })],
      task({ execution_id: "a", result: "new" }),
    )
    expect(next).toHaveLength(1)
    expect(next[0]?.result).toBe("new")
  })
})

describe("nodeStatusOf / stageSortKey", () => {
  it("derives status from agent/result/stage", () => {
    expect(nodeStatusOf(task({ execution_id: "x", agent: "NONE" }))).toBe("unassigned")
    expect(nodeStatusOf(task({ execution_id: "x", stage: "turn_summary", result: "fail" }))).toBe("failed")
    expect(nodeStatusOf(task({ execution_id: "x", stage: "turn_summary", result: "success" }))).toBe("success")
    expect(nodeStatusOf(task({ execution_id: "x", result: "" }))).toBe("unfinished")
    expect(nodeStatusOf(task({ execution_id: "x", result: "ok" }))).toBe("done")
  })

  it("orders stages pre → mid → summary → final", () => {
    expect(stageSortKey("pre_exec")).toBeLessThan(stageSortKey("mid_exec_round_1"))
    expect(stageSortKey("mid_exec_round_1")).toBeLessThan(stageSortKey("mid_exec_round_2"))
    expect(stageSortKey("mid_exec_round_2")).toBeLessThan(stageSortKey("turn_summary"))
    expect(stageSortKey("turn_summary")).toBeLessThan(stageSortKey("final_answer"))
  })
})

describe("treeRoleLabel", () => {
  it("keeps a single 发起者 on the originating root", () => {
    expect(treeRoleLabel(task({ execution_id: "own-1-user-agent-t1", role: "initiator" }))).toBe("发起者")
  })

  it("labels the delegation wrapper as 被委派", () => {
    expect(
      treeRoleLabel(
        task({
          execution_id: "pre-2-order-agent-t1",
          agent: "order-agent",
          role: "delegatee",
          delegated_by: "user-agent",
        }),
      ),
    ).toBe("被委派")
  })

  it("does not call nested own-tasks 发起者", () => {
    expect(
      treeRoleLabel(
        task({
          execution_id: "own-1-order-agent-t1",
          agent: "order-agent",
          role: "initiator",
          parent_execution_id: "pre-2-order-agent-t1",
          delegated_by: "user-agent",
        }),
      ),
    ).toBe("内部执行")
  })

  it("does not label a live unparented peer root as 发起者", () => {
    const origin = originAgentOf([
      task({ execution_id: "own-1-user-agent-t1", agent: "user-agent", role: "initiator" }),
      task({ execution_id: "own-1-order-agent-t1", agent: "order-agent", role: "initiator" }),
    ])
    expect(origin).toBe("user-agent")
    expect(
      treeRoleLabel(
        task({ execution_id: "own-1-order-agent-t1", agent: "order-agent", role: "initiator" }),
        origin,
      ),
    ).toBe("内部执行")
    expect(
      treeRoleLabel(
        task({ execution_id: "own-1-user-agent-t1", agent: "user-agent", role: "initiator" }),
        origin,
      ),
    ).toBe("发起者")
  })
})
