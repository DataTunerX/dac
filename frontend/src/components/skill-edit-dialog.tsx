"use client"

import { useEffect, useState } from "react"
import useSWR from "swr"
import { Download, Loader2, Package, Save } from "lucide-react"
import { toast } from "sonner"

import { RbacWrapper } from "@/components/rbac"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
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
import type { SkillInfoResponse } from "@/lib/api-types"
import { getSkill, updateSkill } from "@/lib/skills-api"
import { cn } from "@/lib/utils"

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

type FormState = {
  description: string
  detail: string
  version: string
  allowedTools: string[]
}

type SkillEditDialogProps = {
  /** List-row summary used to open the dialog; full pack fields load via getSkill. */
  skill: SkillInfoResponse | null
  downloading?: boolean
  onClose: () => void
  onDownload: (skill: SkillInfoResponse) => void
  /** Called after a successful save so the parent can refresh the list. */
  onSaved?: (skill: SkillInfoResponse) => void
}

/**
 * Namespace skill edit dialog: edit metadata (preserves pack scripts on save).
 * Row click opens read-only SkillDetailDialog instead.
 */
export function SkillEditDialog({
  skill,
  downloading = false,
  onClose,
  onDownload,
  onSaved,
}: SkillEditDialogProps) {
  const detailKey = skill
    ? `skill-edit:${skill.namespace}/${skill.name}@${skill.version}`
    : null
  const {
    data: skillDetail,
    error: detailError,
    isLoading: detailLoading,
    mutate: mutateDetail,
  } = useSWR(
    detailKey,
    () => getSkill(skill!.namespace, skill!.name, skill!.version || undefined),
    { revalidateOnFocus: false }
  )

  const [form, setForm] = useState<FormState>({
    description: "",
    detail: "",
    version: "1.0.0",
    allowedTools: [],
  })
  const [sourceVersion, setSourceVersion] = useState("")
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!skillDetail) return
    setForm({
      description: skillDetail.description || "",
      detail: skillDetail.detail || "",
      version: skillDetail.version || "1.0.0",
      allowedTools: [...(skillDetail.allowedTools || [])],
    })
    setSourceVersion(skillDetail.version || "")
  }, [skillDetail])

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

  const onSave = async () => {
    if (!skill) return
    const description = form.description.trim()
    const version = form.version.trim() || sourceVersion || "1.0.0"
    if (!description) {
      toast.error("请输入技能描述")
      return
    }

    setSaving(true)
    try {
      const updated = await updateSkill(
        skill.namespace,
        skill.name,
        {
          name: skill.name,
          description,
          detail: form.detail,
          version,
          allowedTools: form.allowedTools,
        },
        sourceVersion || undefined
      )
      toast.success(`已保存 ${updated.name}@${updated.version}`)
      await mutateDetail()
      onSaved?.(updated)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "保存失败")
    } finally {
      setSaving(false)
    }
  }

  const scripts = skillDetail?.scripts ?? []
  const resourceDirs = skillDetail?.resourceDirs ?? []
  const extrasNote =
    scripts.length > 0 || resourceDirs.length > 0
      ? "保存时会保留包内脚本与资源目录；若要改脚本内容请重新上传 zip。"
      : "保存将重写 SKILL.md 与 _meta.json；复杂脚本请用「上传技能」。"

  return (
    <Dialog
      open={!!skill}
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent className="flex max-h-[90vh] max-w-2xl flex-col gap-0 overflow-hidden p-0 sm:max-w-[720px]">
        <DialogHeader className="border-b border-line px-6 py-4">
          <DialogTitle className="flex items-center gap-2 break-all">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-[#c7d2fe] bg-[#e0e7ff] text-[#4f46e5]">
              <Package className="h-4 w-4" />
            </span>
            编辑技能
          </DialogTitle>
          <DialogDescription>
            命名空间{" "}
            <span className="font-mono text-content">{skill?.namespace}</span>
            {" · "}
            {extrasNote}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 overflow-y-auto px-6 py-4">
          {detailLoading && !skillDetail ? (
            <div className="flex h-40 items-center justify-center text-content-muted">
              <Loader2 className="h-5 w-5 animate-spin" />
            </div>
          ) : detailError ? (
            <div className="rounded-md border border-dashed border-line-hover bg-surface-muted px-4 py-8 text-center text-sm text-content-muted">
              加载详情失败：
              {detailError instanceof Error ? detailError.message : "未知错误"}
            </div>
          ) : (
            <>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="edit-skill-name">名称</Label>
                  <Input
                    id="edit-skill-name"
                    value={skill?.name || ""}
                    disabled
                    className="font-mono"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="edit-skill-version">版本</Label>
                  <Input
                    id="edit-skill-version"
                    value={form.version}
                    disabled
                    className="font-mono"
                  />
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="edit-skill-description">描述 *</Label>
                <Textarea
                  id="edit-skill-description"
                  value={form.description}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, description: e.target.value }))
                  }
                  disabled={saving}
                  rows={5}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="edit-skill-detail">详细说明</Label>
                <Textarea
                  id="edit-skill-detail"
                  value={form.detail}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, detail: e.target.value }))
                  }
                  disabled={saving}
                  rows={10}
                  className="font-mono text-xs leading-relaxed"
                />
              </div>

              <div className="space-y-2">
                <Label>允许的工具</Label>
                <div className="flex flex-wrap gap-2">
                  {TOOL_OPTIONS.map((tool) => {
                    const selected = form.allowedTools.includes(tool)
                    return (
                      <button
                        key={tool}
                        type="button"
                        disabled={saving}
                        onClick={() => toggleTool(tool)}
                        className={cn(
                          "rounded-md border px-2.5 py-1 font-mono text-xs transition-colors",
                          selected
                            ? "border-primary bg-primary/10 text-primary"
                            : "border-line bg-surface text-content-muted hover:border-line-hover"
                        )}
                      >
                        {tool}
                      </button>
                    )
                  })}
                </div>
                <p className="text-xs text-content-muted">
                  未选择表示不限制工具；选择后仅允许列出的工具。
                </p>
              </div>

              {(scripts.length > 0 || resourceDirs.length > 0) && (
                <div className="space-y-2 rounded-md border border-line bg-surface-muted px-3 py-3">
                  <div className="text-xs font-medium text-content-muted">
                    包内附加内容（只读，保存时保留）
                  </div>
                  {scripts.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {scripts.map((s) => (
                        <Badge key={s.scriptName} variant="secondary" className="font-mono">
                          {s.scriptName}
                          {s.interpreter ? ` · ${s.interpreter}` : ""}
                        </Badge>
                      ))}
                    </div>
                  )}
                  {resourceDirs.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {resourceDirs.map((d) => (
                        <Badge key={d} variant="outline" className="font-mono">
                          {d}/
                        </Badge>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>

        <DialogFooter className="border-t border-line px-6 py-4 sm:justify-between">
          <Button
            variant="outline"
            disabled={!skill || downloading}
            onClick={() => skill && onDownload(skill)}
          >
            {downloading ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                下载中…
              </>
            ) : (
              <>
                <Download className="mr-2 h-4 w-4" />
                下载
              </>
            )}
          </Button>
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="outline" onClick={onClose} disabled={saving}>
              关闭
            </Button>
            <RbacWrapper requiredPermission="skill:manage">
              <Button
                disabled={!skillDetail || saving || !!detailError}
                onClick={onSave}
              >
                {saving ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    保存中…
                  </>
                ) : (
                  <>
                    <Save className="mr-2 h-4 w-4" />
                    保存
                  </>
                )}
              </Button>
            </RbacWrapper>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
