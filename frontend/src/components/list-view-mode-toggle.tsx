"use client"

import { LayoutGrid, List } from "lucide-react"
import { Button } from "@/components/ui/button"

export type ListViewMode = "grid" | "list"

type ListViewModeToggleProps = {
  value: ListViewMode
  onChange: (mode: ListViewMode) => void
}

/** Grid / list display toggle for resource list pages. */
export function ListViewModeToggle({ value, onChange }: ListViewModeToggleProps) {
  return (
    <div
      className="inline-flex rounded-md border border-line bg-surface p-0.5"
      role="group"
      aria-label="展示方式"
    >
      <Button
        type="button"
        variant={value === "grid" ? "default" : "ghost"}
        size="icon"
        className="h-8 w-8"
        onClick={() => onChange("grid")}
        aria-label="卡片视图"
        aria-pressed={value === "grid"}
        title="卡片视图"
      >
        <LayoutGrid className="h-4 w-4" />
      </Button>
      <Button
        type="button"
        variant={value === "list" ? "default" : "ghost"}
        size="icon"
        className="h-8 w-8"
        onClick={() => onChange("list")}
        aria-label="列表视图"
        aria-pressed={value === "list"}
        title="列表视图"
      >
        <List className="h-4 w-4" />
      </Button>
    </div>
  )
}
