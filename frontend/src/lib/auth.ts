import { getClientSession } from "@/lib/auth-session"

// Stable empty array for fallback — avoids creating new array references
// on every call to getPermissionCodes when session is null.
const EMPTY_CODES: string[] = []

/** Every permission code the current session snapshot holds (empty pre-hydration). */
export const getPermissionCodes = (): string[] => {
  return getClientSession()?.permissionCodes ?? EMPTY_CODES
}

/** Whether the session snapshot is a platform super admin. */
export const isSuperAdmin = (): boolean => {
  return Boolean(getClientSession()?.isSuper)
}

/** Whether a session snapshot holds every listed permission code. */
export const hasPermissions = (required: string[]): boolean => {
  if (!Array.isArray(required) || required.length === 0) return true
  if (isSuperAdmin()) return true
  const owned = new Set(getPermissionCodes())
  return required.every((code) => owned.has(code))
}

/** Whether a session snapshot holds at least one of the listed permission codes. */
export const hasAnyPermission = (required: string[]): boolean => {
  if (!Array.isArray(required) || required.length === 0) return true
  if (isSuperAdmin()) return true
  const owned = new Set(getPermissionCodes())
  return required.some((code) => owned.has(code))
}