"use client"

import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

type Props = {
  total: number
  page: number
  pageSize: number
  pageSizeOptions?: number[]
  isLoading?: boolean
  onPageChange: (nextPage: number) => void
  onPageSizeChange?: (nextPageSize: number) => void
}

function clamp(n: number, min: number, max: number) {
  return Math.max(min, Math.min(max, n))
}

export function PaginationBar({
  total,
  page,
  pageSize,
  pageSizeOptions,
  isLoading,
  onPageChange,
  onPageSizeChange,
}: Props) {
  // NOTE: keep this component simple and deterministic; no internal state.
  const safeTotal = Math.max(0, total)
  const safePageSize = Math.max(1, pageSize)
  const totalPages = Math.max(1, Math.ceil(safeTotal / safePageSize))
  const safePage = clamp(page, 1, totalPages)

  const startIdx = safeTotal === 0 ? 0 : (safePage - 1) * safePageSize + 1
  const endIdx = Math.min(safeTotal, safePage * safePageSize)
  const fallbackPageSizeOptions = [10, 20, 50, 100]
  const rawOptions =
    onPageSizeChange ? (pageSizeOptions && pageSizeOptions.length > 0 ? pageSizeOptions : fallbackPageSizeOptions) : []
  const normalizedPageSizeOptions = Array.from(
    new Set([safePageSize, ...rawOptions].filter((n) => Number.isFinite(n) && n > 0))
  ).sort((a, b) => a - b)

  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="text-xs text-content-muted shrink-0">
        共 {safeTotal} 条记录{safeTotal > 0 ? `，当前显示 ${startIdx}-${endIdx}` : ""}。
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {normalizedPageSizeOptions.length > 0 && onPageSizeChange ? (
          <div className="flex items-center gap-2">
            <span className="text-xs text-content-muted">每页</span>
            <Select
              value={String(safePageSize)}
              onValueChange={(v) => {
                const n = Number(v)
                if (Number.isFinite(n) && n > 0) {
                  onPageSizeChange(n)
                  // Keep UX consistent across all list pages.
                  onPageChange(1)
                }
              }}
            >
              <SelectTrigger className="h-8 w-[92px]">
                <SelectValue placeholder="每页" />
              </SelectTrigger>
              <SelectContent position="popper" side="bottom" align="end" sideOffset={6} collisionPadding={10}>
                {normalizedPageSizeOptions.map((n) => (
                  <SelectItem key={n} value={String(n)}>
                    {n}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <span className="text-xs text-content-muted">条</span>
          </div>
        ) : null}
        <Button
          variant="outline"
          size="sm"
          onClick={() => onPageChange(Math.max(1, safePage - 1))}
          disabled={Boolean(isLoading) || safePage <= 1}
        >
          上一页
        </Button>
        <div className="text-xs text-content">
          第 <span className="font-mono">{safePage}</span> / <span className="font-mono">{totalPages}</span> 页
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => onPageChange(Math.min(totalPages, safePage + 1))}
          disabled={Boolean(isLoading) || safePage >= totalPages}
        >
          下一页
        </Button>
      </div>
    </div>
  )
}

