import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}))

import { api } from "@/lib/api"
import {
  createSkill,
  createSkillNamespace,
  deleteSkill,
  deleteSkillNamespace,
  downloadSkill,
  getSkill,
  updateSkill,
  listSkillNamespaces,
  listSkills,
  reloadSkills,
  skillNamespaceExists,
  uploadSkill,
} from "./skills-api"

describe("skills-api", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset()
    vi.mocked(api.post).mockReset()
    vi.mocked(api.delete).mockReset()
  })

  it("listSkillNamespaces hits /skills/namespaces", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { items: [{ id: "default", visibility: "public" }], totalCount: 1 },
    })
    const out = await listSkillNamespaces()
    expect(api.get).toHaveBeenCalledWith("/skills/namespaces")
    expect(out.totalCount).toBe(1)
    expect(out.items[0].id).toBe("default")
  })

  it("listSkills encodes namespace", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { items: [], totalCount: 0, namespace: "team-a" },
    })
    await listSkills("team-a")
    expect(api.get).toHaveBeenCalledWith("/skills/namespaces/team-a/skills")
  })

  it("createSkillNamespace posts name body", async () => {
    vi.mocked(api.post).mockResolvedValue({
      data: { id: "team-b", visibility: "public" },
    })
    const out = await createSkillNamespace("team-b")
    expect(api.post).toHaveBeenCalledWith("/skills/namespaces", { name: "team-b" })
    expect(out.id).toBe("team-b")
  })

  it("deleteSkillNamespace hits namespaced path", async () => {
    vi.mocked(api.delete).mockResolvedValue({ data: undefined })
    await deleteSkillNamespace("team-a")
    expect(api.delete).toHaveBeenCalledWith("/skills/namespaces/team-a")
  })

  it("skillNamespaceExists hits exists path", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { namespace: "team-a", exists: true },
    })
    const out = await skillNamespaceExists("team-a")
    expect(api.get).toHaveBeenCalledWith("/skills/namespaces/team-a/exists")
    expect(out.exists).toBe(true)
  })

  it("getSkill fetches detail with optional version", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: {
        name: "report",
        namespace: "team-a",
        description: "d",
        detail: "## Goal\n",
        version: "1.1.0",
        filename: "report-1.1.0.zip",
        availableVersions: ["1.1.0"],
        allowedTools: ["glob"],
        scripts: [],
        resourceDirs: [],
      },
    })
    const out = await getSkill("team-a", "report", "1.1.0")
    expect(api.get).toHaveBeenCalledWith("/skills/namespaces/team-a/skills/report", {
      params: { version: "1.1.0" },
    })
    expect(out.detail).toBe("## Goal\n")
    expect(out.allowedTools).toEqual(["glob"])
  })

  it("createSkill posts JSON to /skills/create", async () => {
    vi.mocked(api.post).mockResolvedValue({
      data: {
        name: "form-skill",
        namespace: "team-a",
        description: "from form",
        version: "1.0.0",
        filename: "form-skill-1.0.0.zip",
        availableVersions: ["1.0.0"],
      },
    })
    const out = await createSkill("team-a", {
      name: "form-skill",
      description: "from form",
      detail: "## Hi\n",
      version: "1.0.0",
      allowedTools: ["glob"],
    })
    expect(api.post).toHaveBeenCalledWith("/skills/namespaces/team-a/skills/create", {
      name: "form-skill",
      description: "from form",
      detail: "## Hi\n",
      version: "1.0.0",
      allowedTools: ["glob"],
    })
    expect(out.name).toBe("form-skill")
  })

  it("updateSkill posts JSON to /skills/:name/update", async () => {
    vi.mocked(api.post).mockResolvedValue({
      data: {
        name: "form-skill",
        namespace: "team-a",
        description: "updated",
        version: "1.1.0",
        filename: "form-skill-1.1.0.zip",
        availableVersions: ["1.0.0", "1.1.0"],
      },
    })
    const out = await updateSkill(
      "team-a",
      "form-skill",
      {
        name: "form-skill",
        description: "updated",
        detail: "## Hi\n",
        version: "1.1.0",
        allowedTools: ["grep"],
      },
      "1.0.0"
    )
    expect(api.post).toHaveBeenCalledWith(
      "/skills/namespaces/team-a/skills/form-skill/update",
      {
        name: "form-skill",
        description: "updated",
        detail: "## Hi\n",
        version: "1.1.0",
        allowedTools: ["grep"],
      },
      { params: { version: "1.0.0" } }
    )
    expect(out.version).toBe("1.1.0")
  })

  it("uploadSkill sends multipart FormData", async () => {
    vi.mocked(api.post).mockResolvedValue({
      data: {
        name: "demo",
        namespace: "default",
        description: "",
        version: "1.0.0",
        filename: "demo-1.0.0.zip",
        availableVersions: ["1.0.0"],
      },
    })
    const file = new File(["zip"], "demo.zip", { type: "application/zip" })
    const out = await uploadSkill("default", file)
    expect(api.post).toHaveBeenCalledTimes(1)
    const [path, body] = vi.mocked(api.post).mock.calls[0]
    expect(path).toBe("/skills/namespaces/default/skills")
    expect(body).toBeInstanceOf(FormData)
    expect((body as FormData).get("file")).toBeInstanceOf(File)
    expect(out.name).toBe("demo")
  })

  it("deleteSkill passes optional version query", async () => {
    vi.mocked(api.delete).mockResolvedValue({ data: undefined })
    await deleteSkill("default", "hashgen", "1.0.0")
    expect(api.delete).toHaveBeenCalledWith(
      "/skills/namespaces/default/skills/hashgen",
      { params: { version: "1.0.0" } },
    )
  })

  it("deleteSkill omits version params when absent", async () => {
    vi.mocked(api.delete).mockResolvedValue({ data: undefined })
    await deleteSkill("default", "hashgen")
    expect(api.delete).toHaveBeenCalledWith(
      "/skills/namespaces/default/skills/hashgen",
      { params: undefined },
    )
  })

  it("reloadSkills posts /skills/reload", async () => {
    vi.mocked(api.post).mockResolvedValue({
      data: { items: [], totalCount: 0 },
    })
    await reloadSkills()
    expect(api.post).toHaveBeenCalledWith("/skills/reload")
  })

  it("encodes special characters in paths", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { items: [], totalCount: 0 } })
    await listSkills("team/a")
    expect(api.get).toHaveBeenCalledWith("/skills/namespaces/team%2Fa/skills")
  })

  it("downloadSkill fetches zip and triggers browser download", async () => {
    const blob = new Blob(["PK"], { type: "application/zip" })
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      blob: async () => blob,
      headers: {
        get: (key: string) =>
          key === "Content-Disposition" ? 'attachment; filename="hashgen.zip"' : null,
      },
    })
    vi.stubGlobal("fetch", fetchMock)

    const click = vi.fn()
    const remove = vi.fn()
    const appendChild = vi.fn()
    const anchor = { href: "", download: "", click, remove }
    vi.stubGlobal("document", {
      createElement: vi.fn().mockReturnValue(anchor),
      body: { appendChild },
    })
    const createObjectURL = vi.fn().mockReturnValue("blob:mock")
    const revokeObjectURL = vi.fn()
    vi.stubGlobal("URL", {
      createObjectURL,
      revokeObjectURL,
    })

    await downloadSkill("default", "hashgen", "2.0.0")

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/skills/namespaces/default/skills/hashgen/download?version=2.0.0",
      { credentials: "include" },
    )
    expect(appendChild).toHaveBeenCalledWith(anchor)
    expect(click).toHaveBeenCalled()
    expect(anchor.download).toBe("hashgen.zip")
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:mock")

    vi.unstubAllGlobals()
  })

  it("downloadSkill surfaces API error message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        json: async () => ({ message: "skill not found" }),
      }),
    )
    await expect(downloadSkill("default", "missing")).rejects.toThrow("skill not found")
    vi.unstubAllGlobals()
  })
})
