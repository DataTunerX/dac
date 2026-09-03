"use client"

import { useAuthHydrated } from "@/lib/use-user-role"
import { hasAnyPermission, hasPermissions } from "@/lib/auth"

export type PageGateResult =
  | { status: "loading" }
  | { status: "denied" }
  | { status: "allowed" }

/**
 * Returns the page-level auth gate status as a discriminated union so the
 * calling component can branch cleanly without imperative boolean flags.
 *
 * - "loading"  → auth session is not yet hydrated (show skeleton / spinner)
 * - "denied"   → session is hydrated but the user lacks the required permission
 * - "allowed"  → session is hydrated and the user passes the gate
 *
 * When `anyOf` is set, the user needs at least one of the listed codes.
 * Otherwise the user must hold every code in `required`.
 */
export function usePageGate(opts: {
  required?: string[]
  anyOf?: string[]
}): PageGateResult {
  const hydrated = useAuthHydrated()

  if (!hydrated) return { status: "loading" }

  const passes = opts.anyOf
    ? hasAnyPermission(opts.anyOf)
    : hasPermissions(opts.required ?? [])

  return passes ? { status: "allowed" } : { status: "denied" }
}