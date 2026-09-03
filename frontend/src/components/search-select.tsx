"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { Check, ChevronDown, Loader2, Search } from "lucide-react"

import { cn } from "@/lib/utils"

export type SearchSelectOption = {
  value: string
  label: string
  hint?: string
}

/**
 * Searchable dropdown (trigger + panel with search box), used for filters and
 * pickers where a plain <Select> cannot scale (e.g. 1000 tenants).
 */
export function SearchSelect({
  options,
  value,
  onChange,
  allLabel,
  placeholder = "请选择",
  searchPlaceholder = "搜索",
  loading = false,
  footer,
  className,
}: {
  options: SearchSelectOption[]
  value: string | null
  onChange: (v: string | null) => void
  /** When set, renders a top option representing value=null (i.e. no filter). */
  allLabel?: string
  placeholder?: string
  searchPlaceholder?: string
  loading?: boolean
  footer?: string
  className?: string
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const rootRef = useRef<HTMLDivElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false)
    }
    document.addEventListener("mousedown", onDown)
    document.addEventListener("keydown", onKey)
    return () => {
      document.removeEventListener("mousedown", onDown)
      document.removeEventListener("keydown", onKey)
    }
  }, [open])

  useEffect(() => {
    if (open) {
      setQuery("")
      requestAnimationFrame(() => searchRef.current?.focus())
    }
  }, [open])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return options
    return options.filter(
      (o) =>
        o.label.toLowerCase().includes(q) ||
        (o.hint ?? "").toLowerCase().includes(q) ||
        o.value.toLowerCase().includes(q),
    )
  }, [options, query])

  const selected = value ? options.find((o) => o.value === value) : null

  return (
    <div ref={rootRef} className={cn("relative", className)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex h-9 w-full items-center justify-between gap-2 rounded-md border border-line bg-surface px-3 text-sm text-content hover:bg-surface-muted/60 focus:outline-none focus:ring-2 focus:ring-cta/30"
      >
        <span className={cn("truncate", !selected && !allLabel && "text-content-muted")}>
          {selected ? selected.label : (allLabel ?? placeholder)}
        </span>
        {loading ? (
          <Loader2 className="h-4 w-4 shrink-0 animate-spin text-content-muted" />
        ) : (
          <ChevronDown className="h-4 w-4 shrink-0 text-content-muted" />
        )}
      </button>

      {open && (
        <div className="absolute z-50 mt-1 w-full min-w-[260px] rounded-lg border border-line bg-surface shadow-lg">
          <div className="border-b border-line p-2">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-content-muted" />
              <input
                ref={searchRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={searchPlaceholder}
                className="h-8 w-full rounded-md border border-line bg-surface pl-8 pr-2 text-sm text-content placeholder:text-content-muted focus:outline-none focus:ring-2 focus:ring-cta/30"
              />
            </div>
          </div>
          <div className="max-h-72 overflow-y-auto p-1" role="listbox">
            {allLabel && (
              <button
                type="button"
                role="option"
                aria-selected={value === null}
                className="flex w-full items-center justify-between rounded-md px-2.5 py-2 text-sm text-content hover:bg-surface-muted/60"
                onClick={() => {
                  onChange(null)
                  setOpen(false)
                }}
              >
                <span>{allLabel}</span>
                {value === null && <Check className="h-4 w-4 text-cta" />}
              </button>
            )}
            {filtered.length === 0 ? (
              <div className="px-2.5 py-6 text-center text-sm text-content-muted">无匹配结果</div>
            ) : (
              filtered.map((o) => (
                <button
                  key={o.value}
                  type="button"
                  role="option"
                  aria-selected={o.value === value}
                  className="flex w-full items-center justify-between gap-2 rounded-md px-2.5 py-2 text-sm text-content hover:bg-surface-muted/60"
                  onClick={() => {
                    onChange(o.value)
                    setOpen(false)
                  }}
                >
                  <span className="min-w-0 text-left">
                    <span className="block truncate">{o.label}</span>
                    {o.hint && (
                      <span className="block truncate font-mono text-xs text-content-muted">{o.hint}</span>
                    )}
                  </span>
                  {o.value === value && <Check className="h-4 w-4 shrink-0 text-cta" />}
                </button>
              ))
            )}
          </div>
          {footer && (
            <div className="border-t border-line px-3 py-1.5 text-xs text-content-muted">{footer}</div>
          )}
        </div>
      )}
    </div>
  )
}
