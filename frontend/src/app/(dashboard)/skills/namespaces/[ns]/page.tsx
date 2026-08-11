"use client"

import { useMemo, useRef, useState } from "react"
import Link from "next/link"
import { useParams } from "next/navigation"
import useSWR, { mutate as globalMutate } from "swr"
import { toast } from "sonner"
import { ArrowLeft, Download, Loader2, Package, Plus, RefreshCw, Trash2, Upload } from "lucide-react"

import { RbacButton, RbacWrapper } from "@/components/rbac"
import { ListPageSearch } from "@/components/list-page-search"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { TableWrapper } from "@/components/ui/table-wrapper"
import type { SkillInfoResponse } from "@/lib/api-types"
import {
  SKILL_NAMESPACES_KEY,
  createSkill,
  deleteSkill,
  downloadSkill,
  listSkills,
  uploadSkill,
} from "@/lib/skills-api"
import { cn } from "@/lib/utils"

const NAME_PATTERN = /^[A-Za-z0-9._-]+$/
const VERSION_PATTERN = /^[A-Za-z0-9._+-]+$/

/** Common skill_sdk tool plugins + runner builtins users may allow-list. */
const TOOL_OPTIONS = [
  "glob",
  "grep",
  "lsp",
  "readline_in_range",
  "web_fetch",
  "tavily_search",
  "tavily_extract",
  "extract_pdf",
  "code_exec",
] as const

const EMPTY_FORM = {
  name: "",
  description: "",
  detail: "",
  version: "1.0.0",
  allowedTools: [] as string[],
}

export default function SkillNamespaceDetailPage() {
  const params = useParams<{ ns: string }>()
  const namespace = decodeURIComponent(params.ns || "")
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [searchQuery, setSearchQuery] = useState("")
  const [uploading, setUploading] = useState(false)
  const [downloadingKey, setDownloadingKey] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<SkillInfoResponse | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)

  const skillsKey = namespace ? `skills:${namespace}` : null
  const {
    data: skillsData,
    error,
    isLoading,
    isValidating,
    mutate: mutateSkills,
  } = useSWR(skillsKey, () => listSkills(namespace))

  const skills = skillsData?.items ?? []
  const filtered = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    if (!q) return skills
    return skills.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        (s.description || "").toLowerCase().includes(q) ||
        s.version.toLowerCase().includes(q)
    )
  }, [skills, searchQuery])

  const onUploadClick = () => fileInputRef.current?.click()

  const onFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ""
    if (!file) return
    if (!file.name.toLowerCase().endsWith(".zip")) {
      toast.error("请上传 .zip 格式的技能包")
      return
    }
    setUploading(true)
    try {
      const skill = await uploadSkill(namespace, file)
      toast.success(`已上传 ${skill.name}@${skill.version}`)
      await Promise.all([mutateSkills(), globalMutate(SKILL_NAMESPACES_KEY)])
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "上传失败")
    } finally {
      setUploading(false)
    }
  }

  const toggleTool = (tool: string) => {
    setForm((prev) => {
      const has = prev.allowedTools.includes(tool)
      return {
        ...prev,
        allowedTools: has
          ? prev.allowedTools.filter((t) => t !== tool)
          : [...prev.allowedTools, tool],
      }
    })
  }

  const resetCreateForm = () => setForm(EMPTY_FORM)

  const onCreate = async () => {
    const name = form.name.trim()
    const description = form.description.trim()
    const version = (form.version.trim() || "1.0.0")
    if (!name) {
      toast.error("请输入技能名称")
      return
    }
    if (!NAME_PATTERN.test(name)) {
      toast.error("技能名称仅允许字母、数字、.、_、-")
      return
    }
    if (!description) {
      toast.error("请输入技能描述")
      return
    }
    if (!VERSION_PATTERN.test(version)) {
      toast.error("版本号仅允许字母、数字、.、_、+、-")
      return
    }

    setCreating(true)
    try {
      const skill = await createSkill(namespace, {
        name,
        description,
        detail: form.detail,
        version,
        allowedTools: form.allowedTools,
      })
      toast.success(`已创建 ${skill.name}@${skill.version}`)
      setCreateOpen(false)
      resetCreateForm()
      await Promise.all([mutateSkills(), globalMutate(SKILL_NAMESPACES_KEY)])
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "创建失败")
    } finally {
      setCreating(false)
    }
  }

  const onDownload = async (skill: SkillInfoResponse) => {
    const key = `${skill.namespace}/${skill.name}`
    setDownloadingKey(key)
    try {
      await downloadSkill(skill.namespace, skill.name)
      toast.success(`已开始下载 ${skill.name}`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "下载失败")
    } finally {
      setDownloadingKey(null)
    }
  }

  const onConfirmDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await deleteSkill(deleteTarget.namespace, deleteTarget.name, deleteTarget.version)
      toast.success(`已删除 ${deleteTarget.name}@${deleteTarget.version}`)
      setDeleteTarget(null)
      await mutateSkills()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "删除失败")
    } finally {
      setDeleting(false)
    }
  }

  if (!namespace) {
    return (
      <div className="p-8 text-sm text-content-muted">无效的命名空间</div>
    )
  }

  return (
    <div className="space-y-6 p-4 sm:space-y-8 sm:p-6 lg:p-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <Button variant="ghost" size="icon" asChild aria-label="返回命名空间列表">
            <Link href="/skills/namespaces">
              <ArrowLeft className="h-4 w-4" />
            </Link>
          </Button>
          <div className="min-w-0 text-sm font-medium text-content">
            <span className="font-semibold text-content truncate">{namespace}</span>
            <span className="ml-2 text-content-muted">
              {skillsData?.totalCount != null ? `${skillsData.totalCount} 个技能` : ""}
            </span>
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <ListPageSearch
            value={searchQuery}
            onChange={setSearchQuery}
            placeholder="搜索名称、描述、版本…"
          />
          <Button
            variant="outline"
            size="icon"
            onClick={() => mutateSkills()}
            disabled={isValidating}
            aria-label="刷新"
          >
            <RefreshCw className={`h-4 w-4 ${isValidating ? "animate-spin" : ""}`} />
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".zip,application/zip"
            className="hidden"
            onChange={onFileChange}
          />
          <RbacButton
            className="flex items-center gap-2"
            variant="outline"
            onClick={onUploadClick}
            disabled={uploading}
            requiredRole="admin"
            fallbackTitle="无权限：仅管理员可上传"
          >
            {uploading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Upload className="h-4 w-4" />
            )}
            上传技能
          </RbacButton>
          <RbacButton
            className="flex items-center gap-2"
            onClick={() => setCreateOpen(true)}
            requiredRole="admin"
            fallbackTitle="无权限：仅管理员可创建"
          >
            <Plus className="h-4 w-4" />
            创建技能
          </RbacButton>
        </div>
      </div>

      {error ? (
        <div className="rounded-md border border-dashed border-line-hover bg-surface-muted px-4 py-10 text-center text-sm text-content-muted">
          加载失败：{error instanceof Error ? error.message : "未知错误"}
        </div>
      ) : isLoading && skills.length === 0 ? (
        <div className="flex h-[320px] items-center justify-center text-content-muted">
          <Loader2 className="h-6 w-6 animate-spin" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="flex h-[400px] items-center justify-center rounded-md border border-dashed border-line-hover bg-surface-muted">
          <div className="flex flex-col items-center gap-2 text-muted-foreground">
            <Package className="h-10 w-10 opacity-20" />
            <p>
              {skills.length === 0
                ? "该命名空间暂无技能，可创建或上传 .zip 技能包"
                : "没有匹配的技能"}
            </p>
          </div>
        </div>
      ) : (
        <TableWrapper>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>名称</TableHead>
                <TableHead>描述</TableHead>
                <TableHead className="w-[8rem]">最新版本</TableHead>
                <TableHead className="w-[8rem]">版本数</TableHead>
                <TableHead className="w-[10rem] text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((skill) => {
                const dlKey = `${skill.namespace}/${skill.name}`
                return (
                  <TableRow key={dlKey}>
                    <TableCell className="font-medium">{skill.name}</TableCell>
                    <TableCell
                      className="max-w-[28rem] truncate text-content-muted"
                      title={skill.description}
                    >
                      {skill.description || "—"}
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary">{skill.version || "—"}</Badge>
                    </TableCell>
                    <TableCell>{skill.availableVersions?.length ?? 0}</TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label="下载"
                          disabled={downloadingKey === dlKey}
                          onClick={() => onDownload(skill)}
                        >
                          {downloadingKey === dlKey ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : (
                            <Download className="h-4 w-4" />
                          )}
                        </Button>
                        <RbacWrapper requiredRole="admin">
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label="删除最新版本"
                            onClick={() => setDeleteTarget(skill)}
                          >
                            <Trash2 className="h-4 w-4 text-destructive" />
                          </Button>
                        </RbacWrapper>
                      </div>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </TableWrapper>
      )}

      <Dialog
        open={createOpen}
        onOpenChange={(open) => {
          setCreateOpen(open)
          if (!open) resetCreateForm()
        }}
      >
        <DialogContent className="flex max-h-[90vh] max-w-2xl flex-col gap-0 overflow-hidden p-0 sm:max-w-[720px]">
          <DialogHeader className="border-b border-line px-6 py-4">
            <DialogTitle>创建技能</DialogTitle>
            <DialogDescription>
              填写技能元数据与说明；服务端将打包为符合 skill_sdk 的 zip（SKILL.md +
              _meta.json）。含 scripts/资源目录的复杂技能请继续使用「上传技能」。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 overflow-y-auto px-6 py-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="skill-name">名称 *</Label>
                <Input
                  id="skill-name"
                  placeholder="my-skill"
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  disabled={creating}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="skill-version">版本</Label>
                <Input
                  id="skill-version"
                  placeholder="1.0.0"
                  value={form.version}
                  onChange={(e) => setForm((f) => ({ ...f, version: e.target.value }))}
                  disabled={creating}
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="skill-description">描述 *</Label>
              <Input
                id="skill-description"
                placeholder="简短说明该技能做什么"
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                disabled={creating}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="skill-detail">详细说明 / 指令</Label>
              <Textarea
                id="skill-detail"
                placeholder={"## 核心目标\n\n在此编写给 Agent 的完整指令（Markdown）…"}
                className="min-h-[180px] font-mono text-sm"
                value={form.detail}
                onChange={(e) => setForm((f) => ({ ...f, detail: e.target.value }))}
                disabled={creating}
              />
            </div>
            <div className="space-y-2">
              <Label>允许的工具（可选）</Label>
              <p className="text-xs text-content-muted">
                不选表示不限制；选中后仅允许这些工具（runner 会始终保留 finish）。
              </p>
              <div className="flex flex-wrap gap-2">
                {TOOL_OPTIONS.map((tool) => {
                  const selected = form.allowedTools.includes(tool)
                  return (
                    <button
                      key={tool}
                      type="button"
                      disabled={creating}
                      onClick={() => toggleTool(tool)}
                      className={cn(
                        "rounded-md border px-2.5 py-1 text-xs transition-colors",
                        selected
                          ? "border-primary bg-primary/10 text-primary"
                          : "border-line bg-surface text-content-muted hover:border-line-hover hover:text-content"
                      )}
                    >
                      {tool}
                    </button>
                  )
                })}
              </div>
            </div>
          </div>
          <DialogFooter className="border-t border-line px-6 py-4">
            <Button
              variant="outline"
              onClick={() => setCreateOpen(false)}
              disabled={creating}
            >
              取消
            </Button>
            <Button onClick={onCreate} disabled={creating}>
              {creating ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  创建中…
                </>
              ) : (
                "创建"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={!!deleteTarget} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除技能版本</AlertDialogTitle>
            <AlertDialogDescription>
              确认删除{" "}
              <span className="font-medium text-content">
                {deleteTarget?.name}@{deleteTarget?.version}
              </span>
              ？若这是该技能的最后一个版本，技能本身也会被移除。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>取消</AlertDialogCancel>
            <AlertDialogAction onClick={onConfirmDelete} disabled={deleting}>
              {deleting ? "删除中…" : "确认删除"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
