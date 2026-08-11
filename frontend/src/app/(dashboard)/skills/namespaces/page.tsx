"use client"

import { useMemo, useState } from "react"
import { useRouter } from "next/navigation"
import useSWR from "swr"
import { toast } from "sonner"
import { FolderPlus, Loader2, Package, RefreshCw, Trash2 } from "lucide-react"

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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { TableWrapper } from "@/components/ui/table-wrapper"
import type { SkillNamespaceResponse } from "@/lib/api-types"
import {
  SKILL_NAMESPACES_KEY,
  createSkillNamespace,
  deleteSkillNamespace,
  listSkillNamespaces,
} from "@/lib/skills-api"

const NS_PATTERN = /^[a-z0-9][a-z0-9._-]*$/

export default function SkillNamespacesPage() {
  const router = useRouter()
  const [searchQuery, setSearchQuery] = useState("")
  const [createOpen, setCreateOpen] = useState(false)
  const [newName, setNewName] = useState("")
  const [creating, setCreating] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<SkillNamespaceResponse | null>(null)
  const [deleting, setDeleting] = useState(false)

  const { data, error, isLoading, isValidating, mutate } = useSWR(
    SKILL_NAMESPACES_KEY,
    listSkillNamespaces,
    { revalidateOnFocus: true, revalidateOnMount: true }
  )

  const items = data?.items ?? []
  const filtered = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    if (!q) return items
    return items.filter(
      (ns) =>
        ns.id.toLowerCase().includes(q) ||
        (ns.visibility || "").toLowerCase().includes(q)
    )
  }, [items, searchQuery])

  const onCreate = async () => {
    const name = newName.trim()
    if (!name) {
      toast.error("请输入命名空间名称")
      return
    }
    if (!NS_PATTERN.test(name)) {
      toast.error("命名空间须小写字母或数字开头，仅含 a-z、0-9、.、_、-")
      return
    }
    if (name === "default") {
      toast.error("default 为系统保留命名空间，不可创建")
      return
    }
    setCreating(true)
    try {
      await createSkillNamespace(name)
      toast.success(`已创建命名空间 ${name}`)
      setCreateOpen(false)
      setNewName("")
      await mutate()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "创建失败")
    } finally {
      setCreating(false)
    }
  }

  const onConfirmDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await deleteSkillNamespace(deleteTarget.id)
      toast.success(`已删除命名空间 ${deleteTarget.id}`)
      setDeleteTarget(null)
      await mutate()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "删除失败（需为空命名空间）")
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="space-y-6 p-4 sm:space-y-8 sm:p-6 lg:p-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-sm font-medium text-content">
          <span className="font-semibold text-content">命名空间</span>
          <span className="ml-2 text-content-muted">
            {data?.totalCount != null ? `${data.totalCount} 个` : ""}
          </span>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <ListPageSearch
            value={searchQuery}
            onChange={setSearchQuery}
            placeholder="搜索命名空间…"
          />
          <Button
            variant="outline"
            size="icon"
            onClick={() => mutate()}
            disabled={isValidating}
            aria-label="刷新"
          >
            <RefreshCw className={`h-4 w-4 ${isValidating ? "animate-spin" : ""}`} />
          </Button>
          <RbacButton
            className="flex items-center gap-2"
            onClick={() => setCreateOpen(true)}
            requiredRole="admin"
            fallbackTitle="无权限：仅管理员可创建"
          >
            <FolderPlus className="h-4 w-4" />
            新建命名空间
          </RbacButton>
        </div>
      </div>

      {error ? (
        <div className="rounded-md border border-dashed border-line-hover bg-surface-muted px-4 py-10 text-center text-sm text-content-muted">
          加载失败：{error instanceof Error ? error.message : "未知错误"}
        </div>
      ) : isLoading && items.length === 0 ? (
        <div className="flex h-[320px] items-center justify-center text-content-muted">
          <Loader2 className="h-6 w-6 animate-spin" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="flex h-[400px] items-center justify-center rounded-md border border-dashed border-line-hover bg-surface-muted">
          <div className="flex flex-col items-center gap-2 text-muted-foreground">
            <Package className="h-10 w-10 opacity-20" />
            <p>{items.length === 0 ? "暂无命名空间" : "没有匹配的命名空间"}</p>
          </div>
        </div>
      ) : (
        <TableWrapper>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>名称</TableHead>
                <TableHead className="w-[10rem]">可见性</TableHead>
                <TableHead className="w-[8rem] text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((ns) => {
                const isDefault = ns.id === "default"
                return (
                  <TableRow
                    key={ns.id}
                    className="cursor-pointer"
                    onClick={() =>
                      router.push(`/skills/namespaces/${encodeURIComponent(ns.id)}`)
                    }
                  >
                    <TableCell className="font-medium">
                      {ns.id}
                      {isDefault ? (
                        <Badge className="ml-2" variant="secondary">
                          系统
                        </Badge>
                      ) : null}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">{ns.visibility || "public"}</Badge>
                    </TableCell>
                    <TableCell
                      className="text-right"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <RbacWrapper requiredRole="admin">
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label="删除命名空间"
                          disabled={isDefault}
                          title={
                            isDefault
                              ? "default 命名空间不可删除"
                              : "仅可删除空命名空间"
                          }
                          onClick={() => setDeleteTarget(ns)}
                        >
                          <Trash2
                            className={`h-4 w-4 ${isDefault ? "opacity-30" : "text-destructive"}`}
                          />
                        </Button>
                      </RbacWrapper>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </TableWrapper>
      )}

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>新建命名空间</DialogTitle>
            <DialogDescription>
              名称须小写字母或数字开头，仅含 a-z、0-9、.、_、-；default 为系统保留。
            </DialogDescription>
          </DialogHeader>
          {/* Same horizontal inset as DialogHeader (px-6) so left aligns with title and right with description. */}
          <div className="px-6 pt-4">
            <Input
              className="w-full"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="例如 team-a"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === "Enter") void onCreate()
              }}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)} disabled={creating}>
              取消
            </Button>
            <Button onClick={onCreate} disabled={creating}>
              {creating ? "创建中…" : "创建"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={!!deleteTarget} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除命名空间</AlertDialogTitle>
            <AlertDialogDescription>
              确认删除命名空间{" "}
              <span className="font-medium text-content">{deleteTarget?.id}</span>
              ？仅当其中没有任何技能时才能删除。
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
