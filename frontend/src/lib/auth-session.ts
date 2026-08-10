/** Fired after login/logout/session hydrate so client UX gates can refresh without a full remount. */
export const AUTH_CHANGE_EVENT = "dac:auth-change"

export type ClientSessionUser = {
  role?: string
  username?: string
}

export type ClientSession = {
  role: string
  username: string
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
  const role =
    typeof user.role === "string" && user.role.trim() ? user.role.trim() : "user"
  const username = typeof user.username === "string" ? user.username : ""
  return { role, username }
}

/** In-memory UX snapshot only — JWT lives in HttpOnly `dac_token` set by the backend. */
export function getClientSession(): ClientSession | null {
  return clientSession
}

export function establishSession(user: ClientSessionUser): void {
  clientSession = normalizeSessionUser(user)
  notifyAuthChange()
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
