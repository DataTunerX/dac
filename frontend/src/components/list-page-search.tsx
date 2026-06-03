"use client"

import { Search } from "lucide-react"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"

type ListPageSearchProps = {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  className?: string
  inputClassName?: string
}

/** Search field used on list pages (same pattern as agent-registry-panel). */
export function ListPageSearch({
  value,
  onChange,
  placeholder = "搜索",
  className,
  inputClassName,
}: ListPageSearchProps) {
  return (
    <div className={cn("relative", className)}>
      <Search
        className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-content-muted"
        aria-hidden
      />
      <Input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className={cn("h-9 w-[min(16rem,70vw)] bg-surface pl-8", inputClassName)}
        aria-label={placeholder}
      />
    </div>
  )
}
