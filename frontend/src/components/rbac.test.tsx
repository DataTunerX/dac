import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

const authState = vi.hoisted(() => ({ hydrated: false }))

vi.mock("@/lib/use-user-role", () => ({
  useAuthHydrated: () => authState.hydrated,
  useHasPermission: () => true,
  useIsSuper: () => false,
}))

import { RbacButton } from "./rbac"

describe("RbacButton", () => {
  it("is hidden until the session role has hydrated", () => {
    authState.hydrated = false

    const html = renderToStaticMarkup(<RbacButton>Delete</RbacButton>)

    expect(html).toBe("")
  })
})
