"use client"

import * as React from "react"
import { cn } from "@/lib/utils"

export function PageContainer({
  className,
  children,
  compact,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { compact?: boolean }) {
  return (
    <div
      className={cn(
        compact
          ? "p-4 sm:p-5 space-y-4"
          : "p-6 sm:p-8 lg:p-10 space-y-8 sm:space-y-10",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  )
}
