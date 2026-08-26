"use client"

/**
 * TenantProvider hydrates the active-tenant store once the auth session is
 * available. It is mounted at the dashboard layout so the whole app (sidebar,
 * topbar, business pages) can rely on useActiveTenant* hooks and the axios
 * interceptor can tag requests with X-Tenant-Id.
 *
 * Loading the "my tenants" list happens exactly once per auth hydration via an
 * effect keyed on the hydrated flag; logout clears it through reset().
 */
import { useEffect } from "react"
import { useAuthHydrated } from "@/lib/use-user-role"
import { useTenantStore } from "@/lib/tenant-store"
import { AUTH_CHANGE_EVENT, getClientSession } from "@/lib/auth-session"

export function TenantProvider({ children }: { children: React.ReactNode }) {
  const hydrated = useAuthHydrated()
  const loadMyTenants = useTenantStore((s) => s.loadMyTenants)
  const reset = useTenantStore((s) => s.reset)

  useEffect(() => {
    if (!hydrated) return
    void loadMyTenants().catch(() => {
      // Failure is non-fatal: the app still works with an empty tenant list.
    })
  }, [hydrated, loadMyTenants])

  // When the session is cleared (logout / 401), drop tenant state too.
  useEffect(() => {
    const handleAuthChange = () => {
      if (!getClientSession()) reset()
    }
    window.addEventListener(AUTH_CHANGE_EVENT, handleAuthChange)
    return () => window.removeEventListener(AUTH_CHANGE_EVENT, handleAuthChange)
  }, [reset])

  return <>{children}</>
}