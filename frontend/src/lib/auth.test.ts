import { describe, expect, it, vi, beforeEach } from "vitest"

const mockSession = vi.hoisted(() => {
  let session: {
    username: string
    isSuper: boolean
    platformRoles: string[]
    permissionCodes: string[]
  } | null = null

  return {
    setSession: (s: typeof session) => {
      session = s
    },
    getSession: () => session,
  }
})

vi.mock("@/lib/auth-session", () => ({
  getClientSession: () => mockSession.getSession(),
}))

import { getPermissionCodes, isSuperAdmin, hasPermissions, hasAnyPermission } from "./auth"

describe("auth permission functions", () => {
  beforeEach(() => {
    mockSession.setSession(null)
  })

  describe("getPermissionCodes", () => {
    it("returns permission codes from session", () => {
      mockSession.setSession({
        username: "alice",
        isSuper: false,
        platformRoles: [],
        permissionCodes: ["tenant:manage", "user:manage"],
      })
      expect(getPermissionCodes()).toEqual(["tenant:manage", "user:manage"])
    })

    it("returns empty array when session is null", () => {
      expect(getPermissionCodes()).toEqual([])
    })
  })

  describe("isSuperAdmin", () => {
    it("returns true when isSuper is true", () => {
      mockSession.setSession({
        username: "super",
        isSuper: true,
        platformRoles: ["super_admin"],
        permissionCodes: [],
      })
      expect(isSuperAdmin()).toBe(true)
    })

    it("returns false when isSuper is false", () => {
      mockSession.setSession({
        username: "viewer",
        isSuper: false,
        platformRoles: [],
        permissionCodes: [],
      })
      expect(isSuperAdmin()).toBe(false)
    })

    it("returns false when session is null", () => {
      expect(isSuperAdmin()).toBe(false)
    })
  })

  describe("hasPermissions", () => {
    it("returns true when user has all required permissions", () => {
      mockSession.setSession({
        username: "alice",
        isSuper: false,
        platformRoles: [],
        permissionCodes: ["tenant:manage", "user:manage", "agent:read"],
      })
      expect(hasPermissions(["tenant:manage", "agent:read"])).toBe(true)
    })

    it("returns false when user is missing one required permission", () => {
      mockSession.setSession({
        username: "bob",
        isSuper: false,
        platformRoles: [],
        permissionCodes: ["agent:read"],
      })
      expect(hasPermissions(["agent:read", "tenant:manage"])).toBe(false)
    })

    it("returns true for empty required array", () => {
      mockSession.setSession({
        username: "user",
        isSuper: false,
        platformRoles: [],
        permissionCodes: [],
      })
      expect(hasPermissions([])).toBe(true)
    })

    it("returns true for non-array input", () => {
      mockSession.setSession({
        username: "bob",
        isSuper: false,
        platformRoles: [],
        permissionCodes: [],
      })
      expect(hasPermissions(null as unknown as string[])).toBe(true)
    })

    it("returns true for super admin regardless of requirements", () => {
      mockSession.setSession({
        username: "super",
        isSuper: true,
        platformRoles: ["super_admin"],
        permissionCodes: [],
      })
      expect(hasPermissions(["tenant:manage", "platform:role:manage"])).toBe(true)
    })

    it("returns false when session is null", () => {
      expect(hasPermissions(["tenant:manage"])).toBe(false)
    })
  })

  describe("hasAnyPermission", () => {
    it("returns true when user has at least one of the listed codes", () => {
      mockSession.setSession({
        username: "viewer",
        isSuper: false,
        platformRoles: [],
        permissionCodes: ["agent:read"],
      })
      expect(hasAnyPermission(["agent:read", "tenant:manage"])).toBe(true)
    })

    it("returns false when user has none of the listed codes", () => {
      mockSession.setSession({
        username: "newbie",
        isSuper: false,
        platformRoles: [],
        permissionCodes: [],
      })
      expect(hasAnyPermission(["agent:read", "tenant:manage"])).toBe(false)
    })

    it("returns true for empty anyOf array", () => {
      mockSession.setSession({
        username: "user",
        isSuper: false,
        platformRoles: [],
        permissionCodes: [],
      })
      expect(hasAnyPermission([])).toBe(true)
    })

    it("returns true for non-array input", () => {
      mockSession.setSession({
        username: "bob",
        isSuper: false,
        platformRoles: [],
        permissionCodes: [],
      })
      expect(hasAnyPermission(null as unknown as string[])).toBe(true)
    })

    it("returns true for super admin regardless of requirements", () => {
      mockSession.setSession({
        username: "super",
        isSuper: true,
        platformRoles: ["super_admin"],
        permissionCodes: [],
      })
      expect(hasAnyPermission(["tenant:manage"])).toBe(true)
    })

    it("returns false when session is null", () => {
      expect(hasAnyPermission(["tenant:manage"])).toBe(false)
    })
  })
})