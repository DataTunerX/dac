"use client"

import { useSyncExternalStore } from "react"
import { getClientSession } from "@/lib/auth-session"
import { isAuthSessionHydrated, subscribeAuth } from "@/lib/auth-store"

// Stable server snapshots for useSyncExternalStore's third argument.
// React requires getServerSnapshot to return a stable reference;
// returning anonymous objects/arrays inline causes infinite re-renders.
const SERVER_HYDRATED = false as const
const SERVER_USERNAME = "" as const
const SERVER_PERM_CODES: string[] = []
const SERVER_SUPER = false as const

function getServerHydrated(): boolean {
  return SERVER_HYDRATED
}
function getServerUsername(): string {
  return SERVER_USERNAME
}
function getServerPermCodes(): string[] {
  return SERVER_PERM_CODES
}
function getServerSuper(): boolean {
  return SERVER_SUPER
}

// Memoised getSnapshot helpers — React requires both getSnapshot and
// getServerSnapshot to return stable references across calls with the
// same underlying state. Inline objects/arrays trigger infinite loops.
let cachedPermCodes: string[] = []
let cachedPermCodesSession: unknown = undefined

function getPermissionCodesSnapshot(): string[] {
  const session = getClientSession()
  if (session === cachedPermCodesSession) return cachedPermCodes
  cachedPermCodesSession = session
  cachedPermCodes = session?.permissionCodes ?? []
  return cachedPermCodes
}

let cachedSuper = false
let cachedSuperSession: unknown = undefined

function getSuperSnapshot(): boolean {
  const session = getClientSession()
  if (session === cachedSuperSession) return cachedSuper
  cachedSuperSession = session
  cachedSuper = Boolean(session?.isSuper)
  return cachedSuper
}

/**
 * False during SSR / until /api/auth/session hydrate completes;
 * true afterward so cookie-backed permission gates are safe to apply.
 */
export function useAuthHydrated(): boolean {
  return useSyncExternalStore(subscribeAuth, isAuthSessionHydrated, getServerHydrated)
}

function getAuthUsername(): string {
  return getClientSession()?.username || ""
}

/** Username from in-memory session; empty on server / when logged out. */
export function useAuthUsername(): string {
  return useSyncExternalStore(subscribeAuth, getAuthUsername, getServerUsername)
}

/** Every permission code in the session snapshot (reactive). */
export function usePermissionCodes(): string[] {
  return useSyncExternalStore(subscribeAuth, getPermissionCodesSnapshot, getServerPermCodes)
}

/** True after hydration when the user holds the permission (super admins pass all). */
export function useHasPermission(requiredPermission?: string): boolean {
  const codes = usePermissionCodes()
  const isSuper = useSyncExternalStore(subscribeAuth, getSuperSnapshot, getServerSuper)
  if (!requiredPermission) return true
  if (isSuper) return true
  return codes.includes(requiredPermission)
}

/** True when the session user is a super admin (reactive). */
export function useIsSuper(): boolean {
  return useSyncExternalStore(subscribeAuth, getSuperSnapshot, getServerSuper)
}
