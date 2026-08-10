"use client"

import { Button, type ButtonProps } from "@/components/ui/button"
import { useAuthHydrated, useHasRole, useUserRole } from "@/lib/use-user-role"

interface RbacButtonProps extends ButtonProps {
  requiredRole?: string
  fallbackTitle?: string
}

/**
 * UX-only role gate. Does not verify JWT signatures — API must enforce authz.
 *
 * Hydration strategy (rendering-hydration-no-flicker):
 * - SSR / pre-hydration: inert button (no unauthorized interaction or role flash).
 * - After hydration: apply in-memory session role gate.
 */
export function RbacButton({
  requiredRole = "admin",
  fallbackTitle = "无权限",
  disabled,
  title,
  ...props
}: RbacButtonProps) {
  const hydrated = useAuthHydrated()
  const role = useUserRole()

  if (!hydrated) {
    return <Button {...props} disabled title={title} />
  }

  if (role !== requiredRole) {
    return <Button {...props} disabled title={fallbackTitle} />
  }

  return <Button {...props} disabled={disabled} title={title} />
}

export function RbacWrapper({
  children,
  requiredRole = "admin",
  inverse = false,
}: {
  children: React.ReactNode
  requiredRole?: string
  inverse?: boolean
}) {
  const hydrated = useAuthHydrated()
  const hasRole = useHasRole(requiredRole)

  if (!hydrated) return null

  const shouldRender = inverse ? !hasRole : hasRole
  if (!shouldRender) return null

  return <>{children}</>
}
