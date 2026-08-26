"use client"

import * as React from "react"
import { cn } from "@/lib/utils"

export function TableWrapper({
  className,
  children,
  noBorder,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { noBorder?: boolean }) {
  return (
    <div
      className={cn(
        "w-full overflow-hidden bg-surface",
        !noBorder && "rounded-lg border border-line",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  )
}
