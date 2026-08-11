"use client"

import type { ReactNode } from "react"
import useSWR from "swr"
import { Download, Loader2, Package } from "lucide-react"

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
import type { SkillInfoResponse } from "@/lib/api-types"
import { getSkill } from "@/lib/skills-api"

type SkillDetailDialogProps = {
  /** List-row summary used to open the dialog; full pack fields load via getSkill. */
  skill: SkillInfoResponse | null
  downloading?: boolean
  onClose: () => void
  onDownload: (skill: SkillInfoResponse) => void
}

function DetailField({
  label,
  children,
}: {
  label: string
  children: ReactNode
}) {
  return (
    <div className="grid gap-1 sm:grid-cols-[7rem_1fr] sm:gap-4">
      <div className="text-xs font-medium text-content-muted sm:pt-0.5">{label}</div>
      <div className="min-w-0 text-sm text-content">{children}</div>
    </div>
  )
}

/**
 * Read-only skill detail modal (marketplace).
 * Namespace management uses SkillEditDialog for view + edit.
 */
export function SkillDetailDialog({
  skill,
  downloading = false,
  onClose,
  onDownload,
}: SkillDetailDialogProps) {
  const detailKey = skill
    ? `skill-detail:${skill.namespace}/${skill.name}@${skill.version}`
    : null
  const {
    data: skillDetail,
    error: detailError,
    isLoading: detailLoading,
  } = useSWR(
    detailKey,
    () => getSkill(skill!.namespace, skill!.name, skill!.version || undefined),
    { revalidateOnFocus: false }
  )

  return (
    <Dialog
      open={!!skill}
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent className="flex max-h-[90vh] max-w-lg flex-col gap-0 overflow-hidden p-0 sm:max-w-[720px]">
        <DialogHeader className="border-b border-line px-6 py-4">
          <DialogTitle className="flex items-center gap-2 break-all">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-[#c7d2fe] bg-[#e0e7ff] text-[#4f46e5]">
              <Package className="h-4 w-4" />
            </span>
            {skill?.name || "技能详情"}
          </DialogTitle>
          <DialogDescription>
            命名空间 <span className="font-mono text-content">{skill?.namespace}</span>
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
              <p className="mt-2 text-xs">
                若接口 404，请确认集群已部署含 GET …/skills/:name 的 skill-hub /
                dac-apiserver。
              </p>
            </div>
          ) : skillDetail ? (
            <>
              <DetailField label="名称">
                <span className="font-medium break-all">{skillDetail.name}</span>
              </DetailField>
              <DetailField label="命名空间">
                <span className="font-mono">{skillDetail.namespace}</span>
              </DetailField>
              <DetailField label="描述">
                <p className="whitespace-pre-wrap break-words leading-relaxed">
                  {skillDetail.description || "—"}
                </p>
              </DetailField>
              <DetailField label="版本">
                <Badge variant="secondary">{skillDetail.version || "—"}</Badge>
              </DetailField>
              <DetailField label="全部版本">
                {skillDetail.availableVersions?.length ? (
                  <div className="flex flex-wrap gap-1.5">
                    {skillDetail.availableVersions.map((v) => (
                      <Badge key={v} variant="outline" className="font-mono text-xs">
                        {v}
                      </Badge>
                    ))}
                  </div>
                ) : (
                  "—"
                )}
              </DetailField>
              <DetailField label="文件名">
                <span className="break-all font-mono text-xs">
                  {skillDetail.filename ||
                    `${skillDetail.name}-${skillDetail.version}.zip`}
                </span>
              </DetailField>
              {/* From _meta.json; empty list means unrestricted tools. */}
              <DetailField label="允许的工具">
                {skillDetail.allowedTools?.length ? (
                  <div className="flex flex-wrap gap-1.5">
                    {skillDetail.allowedTools.map((t) => (
                      <Badge key={t} variant="outline" className="font-mono text-xs">
                        {t}
                      </Badge>
                    ))}
                  </div>
                ) : (
                  <span className="text-content-muted">不限制（空列表）</span>
                )}
              </DetailField>
              <DetailField label="脚本">
                {skillDetail.scripts?.length ? (
                  <ul className="space-y-1 font-mono text-xs">
                    {skillDetail.scripts.map((s) => (
                      <li key={s.scriptName}>
                        {s.scriptName}
                        {s.interpreter ? (
                          <span className="text-content-muted"> ({s.interpreter})</span>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                ) : (
                  "—"
                )}
              </DetailField>
              <DetailField label="资源目录">
                {skillDetail.resourceDirs?.length ? (
                  <div className="flex flex-wrap gap-1.5">
                    {skillDetail.resourceDirs.map((d) => (
                      <Badge key={d} variant="outline" className="font-mono text-xs">
                        {d}
                      </Badge>
                    ))}
                  </div>
                ) : (
                  "—"
                )}
              </DetailField>
              {/* SKILL.md body after YAML frontmatter. */}
              <DetailField label="详细说明">
                <pre className="max-h-[280px] overflow-auto whitespace-pre-wrap break-words rounded-md border border-line bg-surface-muted px-3 py-2 font-mono text-xs leading-relaxed">
                  {skillDetail.detail?.trim() ? skillDetail.detail : "—"}
                </pre>
              </DetailField>
            </>
          ) : null}
        </div>
        <DialogFooter className="border-t border-line px-6 py-4">
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="outline" onClick={onClose}>
              关闭
            </Button>
            <Button
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
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
