/** Fired after login/logout/session hydrate so client UX gates can refresh without a full remount. */
export const AUTH_CHANGE_EVENT = "dac:auth-change"

export type ClientSessionUser = {
  username?: string
  isSuper?: boolean
  /** Platform-role codes (e.g. ["super_admin", "ops"]). */
  platformRoles?: string[]
  /** Every permission code the user holds (platform roles + tenant memberships). */
  permissionCodes?: string[]
}

export type ClientSession = {
  username: string
  isSuper: boolean
  platformRoles: string[]
  permissionCodes: string[]
}

let clientSession: ClientSession | null = null

/** Single-flight refresh shared by axios + authFetch. */
let refreshPromise: Promise<boolean> | null = null

function notifyAuthChange() {
  if (typeof window === "undefined") return
  window.dispatchEvent(new Event(AUTH_CHANGE_EVENT))
}

function normalizeRelativePath(rawPath: string): string {
  if (!rawPath || !rawPath.startsWith("/")) return "/"
  if (rawPath.startsWith("//")) return "/"
  return rawPath
}

function normalizeSessionUser(user: ClientSessionUser): ClientSession {
  const username = typeof user.username === "string" ? user.username : ""
  return {
    username,
    isSuper: Boolean(user.isSuper),
    platformRoles: Array.isArray(user.platformRoles)
      ? user.platformRoles.filter((x): x is string => typeof x === "string")
      : [],
    permissionCodes: Array.isArray(user.permissionCodes)
      ? user.permissionCodes.filter((x): x is string => typeof x === "string")
      : [],
  }
}

/** In-memory UX snapshot only — JWT lives in HttpOnly `dac_token` set by the backend. */
export function getClientSession(): ClientSession | null {
  return clientSession
}

export function establishSession(user: ClientSessionUser): void {
  const next = normalizeSessionUser(user)
  // Avoid creating a new session object and notifying subscribers when
  // the data is identical. This prevents unnecessary re-renders during
  // focus/visibility revalidation.
  if (
    clientSession &&
    clientSession.username === next.username &&
    clientSession.isSuper === next.isSuper &&
    arraysEqual(clientSession.platformRoles, next.platformRoles) &&
    arraysEqual(clientSession.permissionCodes, next.permissionCodes)
  ) {
    return
  }
  clientSession = next
  notifyAuthChange()
}

function arraysEqual(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return false
  }
  return true
}

export function clearClientSession(): void {
  clientSession = null
  notifyAuthChange()
}

/**
 * POST /api/v1/auth/logout with credentials so the backend clears HttpOnly dac_token,
 * then drop the client UX snapshot.
 */
export async function logout(): Promise<void> {
  try {
    await fetch("/api/v1/auth/logout", {
      method: "POST",
      credentials: "include",
    })
  } catch {
    // Still clear local UX state if the network call fails.
  }
  clearClientSession()
}

/**
 * Attempt cookie-based token refresh. Concurrent callers share one in-flight request.
 * Returns true when the refresh response is OK (Set-Cookie updates dac_token).
 */
export function refreshAuthSession(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = fetch("/api/v1/auth/refresh", {
      method: "POST",
      credentials: "include",
    })
      .then((res) => res.ok)
      .catch(() => false)
      .finally(() => {
        refreshPromise = null
      })
  }
  return refreshPromise
}

export function isAuthRefreshPath(url: string): boolean {
  return (
    url.includes("/auth/login") ||
    url.includes("/auth/register") ||
    url.includes("/auth/refresh") ||
    url.includes("/auth/logout")
  )
}

export function getSafeNextPath(search: string): string {
  return normalizeRelativePath(new URLSearchParams(search).get("next") || "")
}

export function redirectToLogin(nextPath: string): void {
  const safeNextPath = normalizeRelativePath(nextPath)
  window.location.replace(`/login?next=${encodeURIComponent(safeNextPath)}`)
}

export function navigateAfterAuth(nextPath: string): void {
  window.location.replace(normalizeRelativePath(nextPath))
}
