"use client"

import { useSyncExternalStore } from "react"
import { getUserRole } from "@/lib/auth"
import { getClientSession } from "@/lib/auth-session"
import { isAuthSessionHydrated, subscribeAuth } from "@/lib/auth-store"

/**
 * Client-side role for UX gates only (in-memory session snapshot).
 * Authorization must be enforced by dac-apiserver / Casbin.
 *
 * Uses useSyncExternalStore + shared auth-store listeners so login/logout/hydrate/focus
 * refresh the role without remount, and N components share one listener set.
 * Server snapshot is "anonymous" to keep SSR/hydration deterministic.
 */
export function useUserRole(): string {
  return useSyncExternalStore(subscribeAuth, getUserRole, () => "anonymous")
}

/**
 * False during SSR / until /api/auth/session hydrate completes;
 * true afterward so cookie-backed role gates are safe to apply.
 */
export function useAuthHydrated(): boolean {
  return useSyncExternalStore(subscribeAuth, isAuthSessionHydrated, () => false)
}

function getAuthUsername(): string {
  return getClientSession()?.username || ""
}

/** Username from in-memory session; empty on server / when logged out. */
export function useAuthUsername(): string {
  return useSyncExternalStore(subscribeAuth, getAuthUsername, () => "")
}

export function useHasRole(requiredRole = "admin"): boolean {
  return useUserRole() === requiredRole
}
