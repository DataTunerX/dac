/**
 * Module-level active-tenant channel decoupled from the Zustand store.
 *
 * The axios/fetch request interceptors need the current tenant id outside React,
 * but importing the full tenant store would create a circular dependency
 * (tenant-store → rbac-api → api → tenant-store). This tiny module holds only
 * the current tenant id string and mirrors the persisted selection.
 *
 * Storage helpers are intentionally re-implemented here (instead of importing
 * from chat-store) to keep the module dependency-free and avoid the cycle
 * tenant-context → chat-store → auth-fetch → tenant-context.
 */
const STORAGE_KEY = "dac.active_tenant_id"

function readStored(): string | null {
  try {
    return typeof window !== "undefined" ? window.localStorage.getItem(STORAGE_KEY) : null
  } catch {
    return null
  }
}

function writeStored(id: string) {
  try {
    if (typeof window !== "undefined") window.localStorage.setItem(STORAGE_KEY, id)
  } catch {
    // ignore storage errors
  }
}

function clearStored() {
  try {
    if (typeof window !== "undefined") window.localStorage.removeItem(STORAGE_KEY)
  } catch {
    // ignore storage errors
  }
}

let currentTenantId: string | null = readStored()

/** Read the active tenant id (non-React call sites). */
export function getActiveTenantId(): string | null {
  return currentTenantId
}

/** Set the active tenant id (kept in sync with the store + localStorage). */
export function setActiveTenantId(id: string | null): void {
  currentTenantId = id
  if (id) writeStored(id)
  else clearStored()
}

/** Example helper used by tests / edge cases. */
export const TENANT_HEADER_NAME = "X-Tenant-Id"