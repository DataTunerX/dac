"use client"

import * as React from "react"
import { cn } from "@/lib/utils"

export const ScrollArea = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(function ScrollArea(
  { className, ...props },
  ref
) {
  return <div ref={ref} className={cn("overflow-auto", className)} {...props} />
})

