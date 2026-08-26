"use client"

import { Button, type ButtonProps } from "@/components/ui/button"
import {
  useAuthHydrated,
  useHasPermission,
} from "@/lib/use-user-role"

interface RbacProps {
  /**
   * Gate on a permission code from the RBAC catalog (e.g. "tenant:manage").
   * Super admins always pass.
   */
  requiredPermission?: string
}

interface RbacButtonProps extends ButtonProps, RbacProps {}

function useRbacGate({ requiredPermission }: RbacProps) {
  const hydrated = useAuthHydrated()
  const permissionOk = useHasPermission(requiredPermission)
  if (!hydrated) return { hydrated: false, allowed: false }
  return { hydrated: true, allowed: permissionOk }
}

/**
 * UX-only permission gate. Does not verify JWT signatures — API must enforce authz.
 *
 * Hydration strategy (rendering-hydration-no-flicker):
 * - SSR / pre-hydration: inert button (no unauthorized interaction or flash).
 * - After hydration: apply in-memory session gate.
 */
export function RbacButton({
  requiredPermission,
  disabled,
  title,
  ...props
}: RbacButtonProps) {
  const gate = useRbacGate({ requiredPermission })

  if (!gate.hydrated) return null
  if (!gate.allowed) return null

  return <Button {...props} disabled={disabled} title={title} />
}

export function RbacWrapper({
  children,
  requiredPermission,
  inverse = false,
}: RbacProps & {
  children: React.ReactNode
  inverse?: boolean
}) {
  const gate = useRbacGate({ requiredPermission })

  if (!gate.hydrated) return null

  const shouldRender = inverse ? !gate.allowed : gate.allowed
  if (!shouldRender) return null

  return <>{children}</>
}