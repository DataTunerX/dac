import {
  clearClientSession,
  isAuthRefreshPath,
  redirectToLogin,
  refreshAuthSession,
} from "@/lib/auth-session"
import { getActiveTenantId, TENANT_HEADER_NAME } from "@/lib/tenant-context"
import { reconcileTenant } from "@/lib/tenant-reconcile"

export type AuthFetchInit = RequestInit & {
  /** Skip global 401 → login redirect (e.g. login form itself / chat handlers). */
  skipAuthRedirect?: boolean
}

function resolveUrl(input: string | URL): string {
  if (typeof input === "string") return input
  return input.toString()
}

/** Whether a URL is a tenant-scoped API call that carries X-Tenant-Id. */
function isTenantScoped(url: string): boolean {
  return url.startsWith("/api/v1/") && !isAuthRefreshPath(url) && !url.includes("/rbac/me/tenants")
}

/**
 * fetch wrapper shared by chat streaming and other non-axios calls.
 * Sends cookies (credentials) — no Bearer from JS-readable token.
 * Mirrors api.ts 401 → single-flight refresh → retry once.
 * Mirrors api.ts 403 → tenant reconciliation → retry once (when the active
 * tenant in localStorage is disabled, removed, or deleted).
 */
export async function authFetch(input: string | URL, init: AuthFetchInit = {}): Promise<Response> {
  const { skipAuthRedirect, headers: initHeaders, credentials, ...rest } = init
  const headers = new Headers(initHeaders)
  const url = resolveUrl(input)

  // Multi-tenant scoping: mirror the axios interceptor for raw fetch calls.
  const tenantId = getActiveTenantId()
  if (tenantId && !headers.has(TENANT_HEADER_NAME)) {
    headers.set(TENANT_HEADER_NAME, tenantId)
  }

  const doFetch = () =>
    fetch(input, {
      ...rest,
      headers,
      credentials: credentials ?? "include",
    })

  let res = await doFetch()

  // ---- 401: session expired → refresh → retry once ----
  if (res.status === 401 && !isAuthRefreshPath(url)) {
    const refreshed = await refreshAuthSession()
    if (refreshed) {
      res = await doFetch()
    }
  }

  if (res.status === 401 && !skipAuthRedirect && typeof window !== "undefined") {
    clearClientSession()
    const path = window.location.pathname || "/"
    const search = window.location.search || ""
    const hash = window.location.hash || ""
    if (!path.startsWith("/login") && !path.startsWith("/register")) {
      redirectToLogin(`${path}${search}${hash}`)
    }
  }

  // ---- 403: active tenant may be invalid → reconcile → retry once ----
  if (res.status === 403) {
    const currentTenant = getActiveTenantId()
    if (currentTenant && isTenantScoped(url)) {
      const result = await reconcileTenant()
      if (result.switched || result.activeTenantId !== currentTenant) {
        // Rebuild headers with the new tenant id before retrying.
        const newTenantId = getActiveTenantId()
        if (newTenantId) {
          headers.set(TENANT_HEADER_NAME, newTenantId)
        } else {
          headers.delete(TENANT_HEADER_NAME)
        }
        res = await doFetch()
      }
    }
  }

  return res
}
