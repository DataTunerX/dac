"use client"

import { cn } from "@/lib/utils"
import { TableWrapper } from "@/components/ui/table-wrapper"

function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-md bg-surface-active/60",
        "before:absolute before:inset-0 before:-translate-x-full before:animate-[shimmer_1.5s_infinite]",
        "before:bg-gradient-to-r before:from-transparent before:via-white/40 before:to-transparent",
        className
      )}
      {...props}
    />
  )
}

function CardSkeleton() {
  return (
    <div className="rounded-lg border border-line bg-surface p-4 space-y-4">
      <div className="flex items-center gap-3">
        <Skeleton className="w-10 h-10 rounded-xl" />
        <div className="space-y-2 flex-1">
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-3 w-1/2" />
        </div>
      </div>
      <Skeleton className="h-3 w-full" />
      <Skeleton className="h-3 w-2/3" />
      <div className="flex items-center gap-2">
        <Skeleton className="h-3 w-20" />
        <Skeleton className="h-3 w-24" />
      </div>
    </div>
  )
}

function TableRowSkeleton({ cells = 6 }: { cells?: number }) {
  return (
    <div className="flex items-center gap-4 px-4 py-3 border-b border-line">
      {Array.from({ length: cells }).map((_, i) => (
        <Skeleton key={i} className="h-4" style={{ width: `${Math.random() * 40 + 20}%` }} />
      ))}
    </div>
  )
}

function TableSkeleton({ rows = 5, cells = 6 }: { rows?: number; cells?: number }) {
  return (
    <TableWrapper>
      <div className="flex items-center gap-4 px-4 py-3 bg-surface-muted border-b border-line">
        {Array.from({ length: cells }).map((_, i) => (
          <Skeleton key={`header-${i}`} className="h-4" style={{ width: `${Math.random() * 30 + 15}%` }} />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <TableRowSkeleton key={rowIndex} cells={cells} />
      ))}
    </TableWrapper>
  )
}

function ListSkeleton({ items = 6 }: { items?: number }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
      {Array.from({ length: items }).map((_, i) => (
        <CardSkeleton key={i} />
      ))}
    </div>
  )
}

export { Skeleton, CardSkeleton, TableRowSkeleton, TableSkeleton, ListSkeleton }