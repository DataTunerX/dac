"use client"

/**
 * Client-side active-tenant state for the RBAC multi-tenant model.
 *
 * dac-apiserver scopes authorization by the `X-Tenant-Id` request header
 * (see pkg/rbac/middleware.go TenantHeaderName). This store holds the currently
 * selected tenant and the caller's "my tenants" list, so API calls made through
 * @/lib/api can be tagged with the active tenant automatically.
 *
 * Reading the active tenant:
 * - `getActiveTenantId()` — module-level getter, used by the axios interceptor
 *   (outside React) and by authFetch for non-axios calls.
 * - `useActiveTenant()` — reactive hook for components.
 *
 * The tenant list is loaded from GET /rbac/me/tenants. It is intentionally
 * "as-is" for UX (no authz enforcement client-side — the API denies by default).
 *
 * Tenant reconciliation: when the backend returns 403 because the active tenant
 * is disabled/removed/deleted, the axios/fetch interceptors call reconcileTenant
 * which dispatches TENANT_RECONCILED_EVENT. This store listens for that event
 * so the UI (tenant switcher, sidebar) reflects the new state immediately.
 */
import { create } from "zustand"
import { listMyTenants } from "@/lib/rbac-api"
import type { RbacMyTenant } from "@/lib/api-types"
import { getActiveTenantId, setActiveTenantId } from "@/lib/tenant-context"
import { TENANT_RECONCILED_EVENT } from "@/lib/tenant-reconcile"

type TenantState = {
  /** Tenants the current user may access (loaded via /rbac/me/tenants). */
  myTenants: RbacMyTenant[]
  /** Loading flag for the first load of myTenants. */
  loadingTenants: boolean
  /** Last load error (null when OK). */
  tenantsError: string | null
  /** Current active tenant id (null when no tenant selected yet). */
  activeTenantId: string | null
  /** Whether the active tenant id comes from an explicit user selection. */
  autoSelected: boolean
}

type TenantActions = {
  /** Fetch /rbac/me/tenants into the store. Keeps previous list on failure. */
  loadMyTenants: (force?: boolean) => Promise<RbacMyTenant[]>
  /** Set the active tenant (persisted to localStorage). */
  selectTenant: (tenantId: string | null) => void
  /** Drop all tenant state (logout). */
  reset: () => void
}

export type TenantStore = TenantState & TenantActions

const initialState: TenantState = {
  myTenants: [],
  loadingTenants: false,
  tenantsError: null,
  activeTenantId: null,
  autoSelected: false,
}

export const useTenantStore = create<TenantStore>((set, get) => ({
  ...initialState,

  loadMyTenants: async (force = false) => {
    const state = get()
    // Avoid duplicate concurrent loads; allow force refresh by callers.
    if (state.loadingTenants && !force) return state.myTenants
    if (state.myTenants.length > 0 && !force) return state.myTenants

    set({ loadingTenants: true, tenantsError: null })
    try {
      const tenants = await listMyTenants()
      const next: Pick<TenantState, "myTenants" | "loadingTenants" | "tenantsError" | "activeTenantId" | "autoSelected"> = {
        myTenants: tenants,
        loadingTenants: false,
        tenantsError: null,
        activeTenantId: null,
        autoSelected: false,
      }
      // Restore a previously selected tenant if it still exists in the list.
      const stored = getActiveTenantId()
      const restore = stored && tenants.some((t) => t.id === stored) ? stored : null
      if (restore) {
        next.activeTenantId = restore
        next.autoSelected = false
      } else {
        // Default to the first accessible tenant (common case for single-tenant users).
        const first = tenants[0]
        if (first) {
          next.activeTenantId = first.id
          next.autoSelected = true
          setActiveTenantId(first.id)
        }
      }
      if (next.activeTenantId) setActiveTenantId(next.activeTenantId)
      set(next)
      return tenants
    } catch (err) {
      const msg = err instanceof Error ? err.message : "加载租户失败"
      set({ loadingTenants: false, tenantsError: msg })
      return get().myTenants
    }
  },

  selectTenant: (tenantId) => {
    setActiveTenantId(tenantId)
    set({ activeTenantId: tenantId, autoSelected: false })
  },

  reset: () => {
    setActiveTenantId(null)
    set({ ...initialState })
  },
}))

// ---- Reconciliation listener: sync store with module-level state after a 403-recovery ----
if (typeof window !== "undefined") {
  window.addEventListener(
    TENANT_RECONCILED_EVENT,
    ((e: CustomEvent<{ tenants: RbacMyTenant[]; activeTenantId: string | null }>) => {
      useTenantStore.setState({
        myTenants: e.detail.tenants,
        activeTenantId: e.detail.activeTenantId,
        autoSelected: true,
        loadingTenants: false,
        tenantsError: null,
      })
    }) as EventListener,
  )
}

/** Reactive hook returning the currently active tenant id. */
export function useActiveTenantId(): string | null {
  return useTenantStore((s) => s.activeTenantId)
}

/** Reactive hook returning the active tenant object (from myTenants). */
export function useActiveTenant(): RbacMyTenant | undefined {
  const id = useActiveTenantId()
  return useTenantStore((s) => s.myTenants.find((t) => t.id === id))
}