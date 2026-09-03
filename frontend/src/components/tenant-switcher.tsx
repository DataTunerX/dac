"use client"

/**
 * TenantSwitcher lets the current user pick their active tenant.
 *
 * The selection is stored in useTenantStore and drives the `X-Tenant-Id`
 * header injected by @/lib/api and @/lib/auth-fetch, which the apiserver uses
 * to scope authorization (deny-by-default for non-members).
 */
import { RefreshCw } from "lucide-react"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useTenantStore } from "@/lib/tenant-store"
import { useIsSuper } from "@/lib/use-user-role"
import { cn } from "@/lib/utils"

export function TenantSwitcher({ className }: { className?: string }) {
  const myTenants = useTenantStore((s) => s.myTenants)
  const loadingTenants = useTenantStore((s) => s.loadingTenants)
  const tenantsError = useTenantStore((s) => s.tenantsError)
  const activeTenantId = useTenantStore((s) => s.activeTenantId)
  const selectTenant = useTenantStore((s) => s.selectTenant)
  const loadMyTenants = useTenantStore((s) => s.loadMyTenants)
  const isSuper = useIsSuper()

  // Super admins operate platform-wide; an empty tenant list is normal for
  // them, so render nothing instead of "暂无租户" noise.
  if (isSuper && myTenants.length === 0) return null

  if (loadingTenants && myTenants.length === 0) {
    return (
      <div className={cn("flex items-center gap-2 text-xs text-content-inverse/60", className)}>
        <RefreshCw className="h-3.5 w-3.5 animate-spin" />
        <span>租户加载中…</span>
      </div>
    )
  }

  if (myTenants.length === 0) {
    if (tenantsError) {
      return (
        <div className={cn("flex items-center gap-2 text-xs text-content-inverse/60", className)}>
          <span>租户加载失败</span>
          <button
            type="button"
            onClick={() => void loadMyTenants(true)}
            className="underline underline-offset-2 hover:text-content-inverse cursor-pointer"
            title="重新加载租户"
          >
            重试
          </button>
        </div>
      )
    }
    return (
      <div className={cn("text-xs text-content-inverse/60", className)} title="暂无可用租户">
        暂无租户
      </div>
    )
  }

  return (
    <Select
      value={activeTenantId ?? undefined}
      onValueChange={(v) => v && selectTenant(v)}
    >
      <SelectTrigger
        className={cn(
          "h-8 w-[140px] rounded-full border-white/10 bg-white/10 text-xs font-medium",
          "text-content-inverse shadow-none hover:bg-white/15 focus:ring-white/20",
          "justify-center [&>svg]:absolute [&>svg]:right-3 [&>svg]:top-1/2 [&>svg]:h-3.5 [&>svg]:w-3.5 [&>svg]:-translate-y-1/2 [&>svg]:opacity-60",
          className,
        )}
      >
        <SelectValue placeholder="选择租户" />
      </SelectTrigger>
      <SelectContent
        position="popper"
        side="bottom"
        align="end"
        sideOffset={8}
        collisionPadding={10}
        className="min-w-[140px] rounded-lg"
      >
        {myTenants.map((t) => (
          <SelectItem key={t.id} value={t.id} className="justify-center px-2 text-center">
            {t.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}