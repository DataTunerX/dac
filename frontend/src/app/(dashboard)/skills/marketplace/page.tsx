"use client"

import { memo, useEffect, useMemo, useState, type ReactNode } from "react"
import useSWR from "swr"
import { toast } from "sonner"
import { Download, Eye, Loader2, Package, RefreshCw } from "lucide-react"

import { ListPageSearch } from "@/components/list-page-search"
import {
  ListViewModeToggle,
  type ListViewMode,
} from "@/components/list-view-mode-toggle"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
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
  downloadSkill,
  getSkill,
  listSkillNamespaces,
  listSkills,
} from "@/lib/skills-api"

type SkillCardProps = {
  skill: SkillInfoResponse
  downloading: boolean
  onOpen: (skill: SkillInfoResponse) => void
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

const SkillCard = memo(function SkillCard({
  skill,
  downloading,
  onOpen,
  onDownload,
}: SkillCardProps) {
  const versionCount = skill.availableVersions?.length ?? 0
  return (
    <Card
      className="group relative cursor-pointer gap-0 overflow-hidden py-0 transition-all duration-200 hover:border-line-hover hover:shadow-md"
      onClick={() => onOpen(skill)}
    >
      <CardHeader className="bg-surface-muted/50 p-4 pb-3">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 flex-1 items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-[#c7d2fe] bg-[#e0e7ff] text-[#4f46e5]">
              <Package className="h-5 w-5" />
            </div>
            <div className="min-w-0 flex-1">
              <CardTitle
                className="line-clamp-1 break-all pr-1 text-sm font-semibold"
                title={skill.name}
              >
                {skill.name}
              </CardTitle>
              <div className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
                <span className="font-mono text-content-muted">{skill.namespace}</span>
                <span className="text-content-muted">·</span>
                <Badge variant="secondary" className="h-5 px-1.5 text-[10px] font-normal">
                  {skill.version || "—"}
                </Badge>
              </div>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 text-content-muted"
              aria-label="查看详情"
              onClick={(e) => {
                e.stopPropagation()
                onOpen(skill)
              }}
            >
              <Eye className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 text-content-muted"
              aria-label="下载"
              disabled={downloading}
              onClick={(e) => {
                e.stopPropagation()
                onDownload(skill)
              }}
            >
              {downloading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Download className="h-4 w-4" />
              )}
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 px-4 pb-4 pt-3">
        <p
          className="min-h-[32px] line-clamp-2 text-xs leading-relaxed text-content"
          title={skill.description}
        >
          {skill.description || "暂无描述"}
        </p>
        <div className="flex items-center justify-between text-xs text-content-muted">
          <span>{versionCount} 个版本</span>
          <span className="truncate font-mono" title={skill.filename}>
            {skill.filename || `${skill.name}-${skill.version}.zip`}
          </span>
        </div>
      </CardContent>
    </Card>
  )
})

export default function SkillMarketplacePage() {
  const [namespace, setNamespace] = useState("")
  const [searchQuery, setSearchQuery] = useState("")
  const [viewMode, setViewMode] = useState<ListViewMode>("grid")
  const [downloadingKey, setDownloadingKey] = useState<string | null>(null)
  // List row/card summary used to open the dialog; full pack fields come from getSkill.
  const [detailSkill, setDetailSkill] = useState<SkillInfoResponse | null>(null)

  // Fetch zip-backed detail (detail / allowedTools / scripts) when the dialog opens.
  const detailKey = detailSkill
    ? `skill-detail:${detailSkill.namespace}/${detailSkill.name}@${detailSkill.version}`
    : null
  const {
    data: skillDetail,
    error: detailError,
    isLoading: detailLoading,
  } = useSWR(
    detailKey,
    () =>
      getSkill(
        detailSkill!.namespace,
        detailSkill!.name,
        detailSkill!.version || undefined
      ),
    { revalidateOnFocus: false }
  )

  const {
    data: nsData,
    error: nsError,
    isLoading: nsLoading,
    isValidating: nsValidating,
    mutate: mutateNamespaces,
  } = useSWR(SKILL_NAMESPACES_KEY, listSkillNamespaces, {
    revalidateOnFocus: true,
    revalidateOnMount: true,
  })

  const namespaces = useMemo(
    () => {
      const raw = (nsData?.items ?? [])
        .map((n) => n.id?.trim())
        .filter((id): id is string => Boolean(id))
      // Always include "default" — it holds public skills visible to all users
      if (!raw.includes("default")) {
        raw.unshift("default")
      }
      return raw
    },
    [nsData]
  )

  useEffect(() => {
    if (namespaces.length === 0) {
      if (namespace) setNamespace("")
      return
    }
    if (!namespaces.includes(namespace)) {
      setNamespace(namespaces.includes("default") ? "default" : namespaces[0])
    }
  }, [namespaces, namespace])

  const skillsKey = namespace ? `skills:${namespace}` : null
  const {
    data: skillsData,
    error: skillsError,
    isLoading: skillsLoading,
    isValidating: skillsValidating,
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

  const isValidating = nsValidating || skillsValidating
  const loading = nsLoading || (!!namespace && skillsLoading && skills.length === 0)
  const loadError = nsError || skillsError
  const detailDlKey = detailSkill
    ? `${detailSkill.namespace}/${detailSkill.name}`
    : null

  const onRefresh = async () => {
    await Promise.all([mutateNamespaces(), namespace ? mutateSkills() : Promise.resolve()])
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

  return (
    <div className="space-y-6 p-4 sm:space-y-8 sm:p-6 lg:p-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-sm font-medium text-content">
          <span className="font-semibold text-content">技能市场</span>
          <span className="ml-2 text-content-muted">
            {skillsData?.totalCount != null ? `${skillsData.totalCount} 个` : ""}
          </span>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <ListPageSearch
            value={searchQuery}
            onChange={setSearchQuery}
            placeholder="搜索名称、描述、版本…"
          />
          <ListViewModeToggle value={viewMode} onChange={setViewMode} />
          <Select
            value={namespace || undefined}
            onValueChange={setNamespace}
            disabled={nsLoading || namespaces.length === 0}
          >
            <SelectTrigger className="h-9 w-[min(12rem,45vw)] bg-surface">
              <SelectValue placeholder={nsLoading ? "加载中…" : "技能命名空间"} />
            </SelectTrigger>
            <SelectContent align="end">
              {namespaces.map((ns) => (
                <SelectItem key={ns} value={ns}>
                  {ns}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            size="icon"
            onClick={onRefresh}
            disabled={isValidating}
            aria-label="刷新"
          >
            <RefreshCw className={`h-4 w-4 ${isValidating ? "animate-spin" : ""}`} />
          </Button>
        </div>
      </div>

      {loadError ? (
        <div className="rounded-md border border-dashed border-line-hover bg-surface-muted px-4 py-10 text-center text-sm text-content-muted">
          加载失败：{loadError instanceof Error ? loadError.message : "未知错误"}
        </div>
      ) : nsLoading && namespaces.length === 0 ? (
        <div className="flex h-[320px] items-center justify-center text-content-muted">
          <Loader2 className="h-6 w-6 animate-spin" />
        </div>
      ) : namespaces.length === 0 ? (
        <div className="flex h-[400px] items-center justify-center rounded-md border border-dashed border-line-hover bg-surface-muted">
          <div className="flex flex-col items-center gap-2 text-muted-foreground">
            <Package className="h-10 w-10 opacity-20" />
            <p>暂无技能命名空间，请先在「技能命名空间」中创建</p>
          </div>
        </div>
      ) : loading ? (
        <div className="flex h-[320px] items-center justify-center text-content-muted">
          <Loader2 className="h-6 w-6 animate-spin" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="flex h-[400px] items-center justify-center rounded-md border border-dashed border-line-hover bg-surface-muted">
          <div className="flex flex-col items-center gap-2 text-muted-foreground">
            <Package className="h-10 w-10 opacity-20" />
            <p>{skills.length === 0 ? "当前技能命名空间暂无技能" : "没有匹配的技能"}</p>
          </div>
        </div>
      ) : viewMode === "list" ? (
        <TableWrapper>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>名称</TableHead>
                <TableHead>描述</TableHead>
                <TableHead className="w-[8rem]">最新版本</TableHead>
                <TableHead className="w-[8rem]">版本数</TableHead>
                <TableHead className="w-[8rem] text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((skill) => {
                const dlKey = `${skill.namespace}/${skill.name}`
                return (
                  <TableRow
                    key={dlKey}
                    className="cursor-pointer"
                    onClick={() => setDetailSkill(skill)}
                  >
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
                    <TableCell className="text-right" onClick={(e) => e.stopPropagation()}>
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label="查看详情"
                          onClick={() => setDetailSkill(skill)}
                        >
                          <Eye className="h-4 w-4" />
                        </Button>
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
                      </div>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </TableWrapper>
      ) : (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
          {filtered.map((skill) => {
            const dlKey = `${skill.namespace}/${skill.name}`
            return (
              <SkillCard
                key={dlKey}
                skill={skill}
                downloading={downloadingKey === dlKey}
                onOpen={setDetailSkill}
                onDownload={onDownload}
              />
            )
          })}
        </div>
      )}

      <Dialog
        open={!!detailSkill}
        onOpenChange={(open) => {
          if (!open) setDetailSkill(null)
        }}
      >
        <DialogContent className="flex max-h-[90vh] max-w-lg flex-col gap-0 overflow-hidden p-0 sm:max-w-[720px]">
          <DialogHeader className="border-b border-line px-6 py-4">
            <DialogTitle className="flex items-center gap-2 break-all">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-[#c7d2fe] bg-[#e0e7ff] text-[#4f46e5]">
                <Package className="h-4 w-4" />
              </span>
              {detailSkill?.name || "技能详情"}
            </DialogTitle>
            <DialogDescription>
              技能命名空间{" "}
              <span className="font-mono text-content">{detailSkill?.namespace}</span>
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
                <DetailField label="技能命名空间">
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
            <Button variant="outline" onClick={() => setDetailSkill(null)}>
              关闭
            </Button>
            <Button
              disabled={!detailSkill || downloadingKey === detailDlKey}
              onClick={() => detailSkill && onDownload(detailSkill)}
            >
              {downloadingKey === detailDlKey ? (
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
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
