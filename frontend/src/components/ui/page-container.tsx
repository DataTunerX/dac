"use client"

import * as React from "react"
import { cn } from "@/lib/utils"

export function PageContainer({
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("p-6 sm:p-8 lg:p-10 space-y-8 sm:space-y-10", className)}
      {...props}
    >
      {children}
    </div>
  )
}
