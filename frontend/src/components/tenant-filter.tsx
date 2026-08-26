"use client"

import { useMemo } from "react"

import { SearchSelect } from "@/components/search-select"
import { useAllTenants } from "@/hooks/use-all-tenants"
import { Badge } from "@/components/ui/badge"

/**
 * Tenant-as-filter control: a searchable dropdown over ALL tenants.
 * Tenant is treated as an attribute/filter of users & roles, so management
 * pages scale to thousands of tenants without per-tenant sections.
 */
export function TenantFilter({
  value,
  onChange,
  reloadKey,
  allLabel,
  placeholder = "选择租户",
  className = "w-72",
  showStatus = false,
}: {
  value: string | null
  onChange: (id: string | null) => void
  reloadKey?: number
  /** When provided, shows a "no filter" option (optional filter). */
  allLabel?: string
  placeholder?: string
  className?: string
  showStatus?: boolean
}) {
  const { tenants, isLoading } = useAllTenants(reloadKey)

  const options = useMemo(
    () =>
      tenants.map((t) => ({
        value: t.id,
        label: t.name,
        hint: t.status === "disabled" ? `${t.code} · 已禁用` : t.code,
      })),
    [tenants],
  )

  const selected = value ? (tenants.find((t) => t.id === value) ?? null) : null

  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <SearchSelect
        className="flex-1"
        options={options}
        value={value}
        onChange={onChange}
        allLabel={allLabel}
        placeholder={placeholder}
        searchPlaceholder="搜索租户名称 / 编码"
        loading={isLoading}
        footer={`共 ${tenants.length} 个租户`}
      />
      {showStatus && selected && (
        <Badge variant={selected.status === "disabled" ? "destructive" : "secondary"} className="shrink-0">
          {selected.status === "disabled" ? "已禁用" : "正常"}
        </Badge>
      )}
    </div>
  )
}
