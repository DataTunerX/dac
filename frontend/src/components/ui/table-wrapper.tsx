"use client"

import * as React from "react"
import { cn } from "@/lib/utils"

export function TableWrapper({
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "w-full overflow-hidden rounded-lg border border-line bg-surface",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  )
}
