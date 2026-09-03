"use client"

import { usePageGate } from "@/hooks/use-page-gate"
import { NotAuthorized } from "@/components/not-authorized"

/**
 * Permission codes that grant access to any RBAC management page.
 * A user who holds at least one of these may enter the /rbac section;
 * individual pages still use RbacWrapper for fine-grained button gating.
 */
const RBAC_ENTRY_CODES = [
  "tenant:manage",
  "platform:role:manage",
  "permission:read",
  "user:manage",
  "tenant:member:manage",
  "tenant:role:manage",
]

export default function RbacLayout({ children }: { children: React.ReactNode }) {
  const gate = usePageGate({ anyOf: RBAC_ENTRY_CODES })

  if (gate.status === "loading") {
    return (
      <div className="flex items-center justify-center min-h-[320px] p-8">
        <div className="flex flex-col items-center gap-4">
          <div
            className="w-10 h-10 rounded-full border-2 border-line border-t-cta animate-spin"
            aria-hidden
          />
          <p className="text-sm text-content-muted">加载中…</p>
        </div>
      </div>
    )
  }

  if (gate.status === "denied") {
    return <NotAuthorized />
  }

  return <>{children}</>
}