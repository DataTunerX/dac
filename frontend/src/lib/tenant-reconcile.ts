/**
 * Tenant reconciliation: called by the axios/fetch interceptors when a 403
 * response suggests the active tenant is no longer valid (disabled, removed,
 * or deleted).
 *
 * This module intentionally uses raw `fetch` instead of the `api` instance to
 * avoid a circular dependency (api.ts → tenant-reconcile → tenant-store →
 * rbac-api → api.ts). It also sends the /rbac/me/tenants call without the
 * X-Tenant-Id header so the backend returns the user's global tenant list
 * rather than scoping the call to a potentially invalid tenant.
 */
import { getActiveTenantId, setActiveTenantId } from "@/lib/tenant-context"
import type { RbacMyTenant } from "@/lib/api-types"

/** Dispatched after reconciliation so the Zustand store can sync with the new state. */
export const TENANT_RECONCILED_EVENT = "dac:tenant-reconciled"

export type TenantReconcileResult = {
  /** Whether the active tenant changed (old vs new id). */
  switched: boolean
  /** Fresh tenant list. */
  tenants: RbacMyTenant[]
  /** New active tenant ID, or null when none are available. */
  activeTenantId: string | null
}

/**
 * Clear the failed tenant selection, fetch the fresh list, and auto-select
 * the first available tenant. Safe to call when there is no active tenant
 * (returns immediately with switched=false).
 */
export async function reconcileTenant(): Promise<TenantReconcileResult> {
  const oldId = getActiveTenantId()
  if (!oldId) {
    return { switched: false, tenants: [], activeTenantId: null }
  }

  // Clear immediately so the retry (and future requests) do not send the
  // invalid tenant header again.
  setActiveTenantId(null)

  let tenants: RbacMyTenant[] = []
  try {
    const res = await fetch("/api/v1/rbac/me/tenants", {
      credentials: "include",
      headers: { "Content-Type": "application/json" },
    })
    if (res.ok) {
      const body = (await res.json()) as { code?: string; data?: RbacMyTenant[] }
      tenants = body.data ?? []
    }
    // On any failure (network, 403, etc.) tenants stays empty — the user
    // will see "暂无租户" in the switcher and their next action will fail
    // with a clear error rather than a confusing 403.
  } catch {
    // swallowed: tenants stays empty
  }

  const first = tenants[0]
  const result: TenantReconcileResult = {
    switched: oldId !== (first?.id ?? null),
    tenants,
    activeTenantId: first?.id ?? null,
  }

  if (first) {
    setActiveTenantId(first.id)
  }

  // Notify the Zustand store so the UI (tenant switcher, sidebar) reflects
  // the new state immediately without waiting for a full auth re-hydration.
  if (typeof window !== "undefined") {
    window.dispatchEvent(
      new CustomEvent<{ tenants: RbacMyTenant[]; activeTenantId: string | null }>(
        TENANT_RECONCILED_EVENT,
        { detail: { tenants, activeTenantId: result.activeTenantId } },
      ),
    )
  }

  return result
}