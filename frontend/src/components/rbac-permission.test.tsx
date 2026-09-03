import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

const authState = vi.hoisted(() => ({
  hydrated: true,
  codes: [] as string[],
  isSuper: false,
}))

vi.mock("@/lib/use-user-role", () => ({
  useAuthHydrated: () => authState.hydrated,
  useIsSuper: () => authState.isSuper,
  useHasPermission: (requiredPermission?: string) => {
    if (!requiredPermission) return true
    if (authState.isSuper) return true
    return authState.codes.includes(requiredPermission)
  },
}))

import { RbacButton, RbacWrapper } from "./rbac"

describe("RbacButton with permission codes", () => {
  it("renders enabled when user has the required permission", () => {
    authState.hydrated = true
    authState.isSuper = false
    authState.codes = ["tenant:manage"]

    const html = renderToStaticMarkup(
      <RbacButton requiredPermission="tenant:manage">Manage</RbacButton>,
    )

    expect(html).not.toMatch(/ disabled=""/)
    expect(html).toMatch(/Manage/)
  })

  it("returns null when user lacks the required permission", () => {
    authState.hydrated = true
    authState.isSuper = false
    authState.codes = ["agent:read"]

    const html = renderToStaticMarkup(
      <RbacButton requiredPermission="tenant:manage">Manage</RbacButton>,
    )

    expect(html).toBe("")
  })

  it("super admin always passes permission check", () => {
    authState.hydrated = true
    authState.isSuper = true
    authState.codes = []

    const html = renderToStaticMarkup(
      <RbacButton requiredPermission="tenant:manage">Manage</RbacButton>,
    )

    expect(html).not.toMatch(/ disabled=""/)
    expect(html).toMatch(/Manage/)
  })
})

describe("RbacWrapper with permission codes", () => {
  it("renders children when user has the required permission", () => {
    authState.hydrated = true
    authState.isSuper = false
    authState.codes = ["tenant:manage"]

    const html = renderToStaticMarkup(
      <RbacWrapper requiredPermission="tenant:manage">
        <span>Admin Panel</span>
      </RbacWrapper>,
    )

    expect(html).toMatch(/Admin Panel/)
  })

  it("returns null when user lacks the required permission", () => {
    authState.hydrated = true
    authState.isSuper = false
    authState.codes = []

    const html = renderToStaticMarkup(
      <RbacWrapper requiredPermission="tenant:manage">
        <span>Admin Panel</span>
      </RbacWrapper>,
    )

    // Should render nothing (empty string from renderToStaticMarkup)
    expect(html).toBe("")
  })

  it("returns null when not hydrated", () => {
    authState.hydrated = false
    authState.codes = []

    const html = renderToStaticMarkup(
      <RbacWrapper requiredPermission="tenant:manage">
        <span>Admin Panel</span>
      </RbacWrapper>,
    )

    expect(html).toBe("")
  })

  it("inverse=true renders when user lacks permission", () => {
    authState.hydrated = true
    authState.isSuper = false
    authState.codes = []

    const html = renderToStaticMarkup(
      <RbacWrapper requiredPermission="tenant:manage" inverse={true}>
        <span>Not Admin</span>
      </RbacWrapper>,
    )

    expect(html).toMatch(/Not Admin/)
  })

  it("inverse=true hides when user has permission", () => {
    authState.hydrated = true
    authState.isSuper = false
    authState.codes = ["tenant:manage"]

    const html = renderToStaticMarkup(
      <RbacWrapper requiredPermission="tenant:manage" inverse={true}>
        <span>Not Admin</span>
      </RbacWrapper>,
    )

    expect(html).toBe("")
  })
})

describe("RbacButton hydration state", () => {
  it("returns null before hydration", () => {
    authState.hydrated = false
    authState.codes = []

    const html = renderToStaticMarkup(<RbacButton>Delete</RbacButton>)

    expect(html).toBe("")
  })
})