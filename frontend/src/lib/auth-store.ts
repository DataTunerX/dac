/**
 * Shared browser auth subscription (N consumers → 1 set of listeners).
 * See vercel-react-best-practices: client-event-listeners.
 *
 * Hydrates the in-memory session snapshot from GET /api/auth/session and
 * revalidates it when the page becomes active again.
 */
import {
  AUTH_CHANGE_EVENT,
  clearClientSession,
  establishSession,
} from "@/lib/auth-session"

type Listener = () => void

const listeners = new Set<Listener>()
let attached = false
let hydrated = false
let hydratePromise: Promise<void> | null = null

function notify() {
  listeners.forEach((listener) => listener())
}

async function hydrateFromServer(): Promise<void> {
  try {
    const res = await fetch("/api/auth/session", { credentials: "include" })
    if (!res.ok) {
      // A server or network failure is not proof that the cookie is invalid.
      return
    }
    const data = (await res.json()) as {
      authenticated?: boolean
      username?: string
      isSuper?: boolean
      platformRoles?: string[]
      permissionCodes?: string[]
    }
    if (data?.authenticated) {
      establishSession({
        username: data.username,
        isSuper: data.isSuper,
        platformRoles: data.platformRoles,
        permissionCodes: data.permissionCodes,
      })
    } else {
      clearClientSession()
    }
  } catch {
    // Preserve the last confirmed snapshot and retry on the next focus/visibility event.
  } finally {
    const wasHydrated = hydrated
    hydrated = true
    // Only notify subscribers if this is the first hydration or if the
    // session data actually changed (establishSession/clearClientSession
    // already notify via AUTH_CHANGE_EVENT when data changes).
    if (!wasHydrated) {
      notify()
    }
  }
}

function ensureHydration(): Promise<void> | null {
  if (typeof window === "undefined") return null
  if (!hydratePromise) {
    hydratePromise = hydrateFromServer().finally(() => {
      hydratePromise = null
    })
  }
  return hydratePromise
}

function revalidateSession() {
  void ensureHydration()
}

function revalidateVisibleSession() {
  if (document.visibilityState !== "hidden") revalidateSession()
}

/**
 * Force a re-hydration of the in-memory session snapshot (permission codes etc.)
 * from GET /api/auth/session. Called by RBAC management mutations so permission
 * changes made in one tab are reflected immediately instead of waiting for focus.
 */
export function revalidateAuthSession(): void {
  if (typeof window === "undefined") return
  ensureAttached()
  void revalidateSession()
}

function ensureAttached() {
  if (attached || typeof window === "undefined") return
  attached = true
  ensureHydration()
  window.addEventListener(AUTH_CHANGE_EVENT, notify)
  window.addEventListener("focus", revalidateSession)
  document.addEventListener("visibilitychange", revalidateVisibleSession)
}

function detachIfIdle() {
  if (!attached || typeof window === "undefined" || listeners.size > 0) return
  attached = false
  window.removeEventListener(AUTH_CHANGE_EVENT, notify)
  window.removeEventListener("focus", revalidateSession)
  document.removeEventListener("visibilitychange", revalidateVisibleSession)
}

/** True after the first /api/auth/session hydrate attempt finishes. */
export function isAuthSessionHydrated(): boolean {
  return hydrated
}

/** Subscribe to auth session changes. Focus/visibility revalidate the shared snapshot. */
export function subscribeAuth(onStoreChange: Listener): () => void {
  if (typeof window === "undefined") return () => {}
  ensureAttached()
  listeners.add(onStoreChange)
  return () => {
    listeners.delete(onStoreChange)
    detachIfIdle()
  }
}
