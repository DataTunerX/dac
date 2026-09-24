import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn(),
    put: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}))

import { api } from "@/lib/api"
import {
  addSemanticGroupMember,
  createDDGroupRelation,
  deleteDDGroupRelation,
  removeSemanticGroupMember,
  submitAddSemanticGroupMember,
  submitRemoveSemanticGroupMember,
  updateSemanticGroup,
} from "./semantic-groups-api"

describe("semantic-groups-api", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset()
    vi.mocked(api.put).mockReset()
    vi.mocked(api.post).mockReset()
    vi.mocked(api.delete).mockReset()
  })

  it("updateSemanticGroup PUTs description and agent_card", async () => {
    vi.mocked(api.put).mockResolvedValue({
      data: { id: "sg-1", group_name: "g", description: "d", agent_card: "{}" },
    })
    const body = {
      description: "updated desc",
      agent_card: JSON.stringify({
        name: "BankAgent",
        description: "updated desc",
        skills: [{ id: "deposit", name: "存款", description: "存款分析" }],
      }),
    }
    const out = await updateSemanticGroup("sg-1", body)
    expect(api.put).toHaveBeenCalledWith("/semantic-groups/sg-1", body)
    expect(out.id).toBe("sg-1")
  })

  it("createDDGroupRelation POSTs membership row", async () => {
    vi.mocked(api.post).mockResolvedValue({
      data: { id: 9, sd_id: "sd-1", group_id: "sg-1", association_reason: "手动添加" },
    })
    const out = await createDDGroupRelation({
      sd_id: "sd-1",
      group_id: "sg-1",
      association_reason: "手动添加",
    })
    expect(api.post).toHaveBeenCalledWith("/dd-group-relations", {
      sd_id: "sd-1",
      group_id: "sg-1",
      association_reason: "手动添加",
    })
    expect(out.id).toBe(9)
  })

  it("deleteDDGroupRelation hits relation id", async () => {
    vi.mocked(api.delete).mockResolvedValue({ data: undefined })
    await deleteDDGroupRelation(42)
    expect(api.delete).toHaveBeenCalledWith("/dd-group-relations/42")
  })

  it("addSemanticGroupMember posts then polls until SUCCESS", async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { task_id: "t-add" } })
    vi.mocked(api.get)
      .mockResolvedValueOnce({ data: { task_id: "t-add", status: "PENDING" } })
      .mockResolvedValueOnce({
        data: {
          task_id: "t-add",
          status: "SUCCESS",
          result: { action: "ADDED", added_count: 1 },
        },
      })

    const out = await addSemanticGroupMember(
      "sg-1",
      { dd_namespace: "ns", dd_name: "orders", association_reason: "手动添加" },
      { intervalMs: 0, timeoutMs: 1_000 }
    )

    expect(api.post).toHaveBeenCalledWith("/semantic-groups/sg-1/members", {
      dd_namespace: "ns",
      dd_name: "orders",
      association_reason: "手动添加",
    })
    expect(api.get).toHaveBeenCalledWith("/semantic-groups/member-tasks/t-add")
    expect(out.result?.action).toBe("ADDED")
  })

  it("addSemanticGroupMember treats SKIPPED as already a member", async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { task_id: "t-skip" } })
    vi.mocked(api.get).mockResolvedValue({
      data: {
        task_id: "t-skip",
        status: "SUCCESS",
        result: { action: "SKIPPED", message: "所选数据源已是该语义组成员" },
      },
    })

    await expect(
      addSemanticGroupMember(
        "sg-1",
        { dd_namespace: "ns", dd_name: "orders" },
        { intervalMs: 0, timeoutMs: 1_000 }
      )
    ).rejects.toThrow("所选数据源已是该语义组成员")
  })

  it("submitAddSemanticGroupMember posts and returns task_id only (no poll)", async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { task_id: "t-submit-add" } })

    const taskId = await submitAddSemanticGroupMember("sg-1", {
      dd_namespace: "ns",
      dd_name: "orders",
      association_reason: "手动添加",
    })

    expect(api.post).toHaveBeenCalledWith("/semantic-groups/sg-1/members", {
      dd_namespace: "ns",
      dd_name: "orders",
      association_reason: "手动添加",
    })
    expect(taskId).toBe("t-submit-add")
    // Must NOT call any GET (no polling)
    expect(api.get).not.toHaveBeenCalled()
  })

  it("submitAddSemanticGroupMember throws when task_id is missing", async () => {
    vi.mocked(api.post).mockResolvedValue({ data: {} })
    await expect(
      submitAddSemanticGroupMember("sg-1", { dd_namespace: "ns", dd_name: "n" })
    ).rejects.toThrow("语义组添加成员任务未返回 task_id")
  })

  it("submitRemoveSemanticGroupMember posts and returns task_id only (no poll)", async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { task_id: "t-submit-rm" } })

    const taskId = await submitRemoveSemanticGroupMember("sg-1", { sd_id: "sd-1" })

    expect(api.post).toHaveBeenCalledWith("/semantic-groups/sg-1/members/remove", {
      sd_id: "sd-1",
    })
    expect(taskId).toBe("t-submit-rm")
    // Must NOT call any GET (no polling)
    expect(api.get).not.toHaveBeenCalled()
  })

  it("submitRemoveSemanticGroupMember throws when task_id is missing", async () => {
    vi.mocked(api.post).mockResolvedValue({ data: {} })
    await expect(
      submitRemoveSemanticGroupMember("sg-1", { sd_id: "sd-1" })
    ).rejects.toThrow("语义组移除成员任务未返回 task_id")
  })

  it("removeSemanticGroupMember posts then polls until SUCCESS", async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { task_id: "t-rm" } })
    vi.mocked(api.get).mockResolvedValue({
      data: {
        task_id: "t-rm",
        status: "SUCCESS",
        result: { action: "REINDUCT_SCHEDULED" },
      },
    })

    const out = await removeSemanticGroupMember(
      "sg-1",
      { sd_id: "sd-1" },
      { intervalMs: 0, timeoutMs: 1_000 }
    )

    expect(api.post).toHaveBeenCalledWith("/semantic-groups/sg-1/members/remove", {
      sd_id: "sd-1",
    })
    expect(api.get).toHaveBeenCalledWith("/semantic-groups/member-tasks/t-rm")
    expect(out.result?.action).toBe("REINDUCT_SCHEDULED")
  })

  it("waitForSemanticGroupMemberTask fails on FAILURE", async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { task_id: "t-fail" } })
    vi.mocked(api.get).mockResolvedValue({
      data: {
        task_id: "t-fail",
        status: "FAILURE",
        error: "该数据源尚未生成语义域，无法加入语义组",
      },
    })

    await expect(
      addSemanticGroupMember(
        "sg-1",
        { dd_namespace: "ns", dd_name: "missing" },
        { intervalMs: 0, timeoutMs: 1_000 }
      )
    ).rejects.toThrow("该数据源尚未生成语义域，无法加入语义组")
  })
})
