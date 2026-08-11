import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

const authState = vi.hoisted(() => ({ hydrated: false, role: "anonymous" }))

vi.mock("@/lib/use-user-role", () => ({
  useAuthHydrated: () => authState.hydrated,
  useUserRole: () => authState.role,
  useHasRole: (requiredRole = "admin") => authState.role === requiredRole,
}))

import { RbacButton } from "./rbac"

describe("RbacButton", () => {
  it("is non-interactive until the session role has hydrated", () => {
    authState.hydrated = false
    authState.role = "anonymous"

    const html = renderToStaticMarkup(<RbacButton>Delete</RbacButton>)

    expect(html).toMatch(/<button[^>]*\sdisabled=""/)
  })
})
