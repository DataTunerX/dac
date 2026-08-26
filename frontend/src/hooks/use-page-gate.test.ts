import { describe, expect, it, vi, beforeEach } from "vitest"

const mockSession = vi.hoisted(() => {
  let session: {
    role: string
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

vi.mock("@/lib/use-user-role", () => ({
  useAuthHydrated: () => {
    const s = mockSession.getSession()
    return s !== null
  },
}))

import { usePageGate } from "./use-page-gate"

describe("usePageGate", () => {
  beforeEach(() => {
    mockSession.setSession(null)
  })

  describe("loading state", () => {
    it("returns loading when auth is not hydrated", () => {
      const result = usePageGate({})
      expect(result).toEqual({ status: "loading" })
    })
  })

  describe("allowed state with no requirements", () => {
    it("returns allowed when hydrated with no required or anyOf", () => {
      mockSession.setSession({
        role: "",
        username: "user",
        isSuper: false,
        platformRoles: [],
        permissionCodes: [],
      })
      const result = usePageGate({})
      expect(result).toEqual({ status: "allowed" })
    })
  })

  describe("required permissions", () => {
    it("returns allowed when user has all required permissions", () => {
      mockSession.setSession({
        role: "admin",
        username: "admin",
        isSuper: false,
        platformRoles: ["ops"],
        permissionCodes: ["tenant:manage", "user:manage"],
      })
      const result = usePageGate({ required: ["tenant:manage", "user:manage"] })
      expect(result).toEqual({ status: "allowed" })
    })

    it("returns denied when user is missing one required permission", () => {
      mockSession.setSession({
        role: "user",
        username: "viewer",
        isSuper: false,
        platformRoles: [],
        permissionCodes: ["agent:read"],
      })
      const result = usePageGate({ required: ["agent:read", "tenant:manage"] })
      expect(result).toEqual({ status: "denied" })
    })

    it("returns denied when user has no permissions", () => {
      mockSession.setSession({
        role: "",
        username: "newbie",
        isSuper: false,
        platformRoles: [],
        permissionCodes: [],
      })
      const result = usePageGate({ required: ["tenant:manage"] })
      expect(result).toEqual({ status: "denied" })
    })

    it("returns allowed for empty required array", () => {
      mockSession.setSession({
        role: "",
        username: "user",
        isSuper: false,
        platformRoles: [],
        permissionCodes: [],
      })
      const result = usePageGate({ required: [] })
      expect(result).toEqual({ status: "allowed" })
    })
  })

  describe("anyOf permissions", () => {
    it("returns allowed when user holds at least one of the anyOf codes", () => {
      mockSession.setSession({
        role: "user",
        username: "viewer",
        isSuper: false,
        platformRoles: [],
        permissionCodes: ["agent:read"],
      })
      const result = usePageGate({ anyOf: ["agent:read", "tenant:manage"] })
      expect(result).toEqual({ status: "allowed" })
    })

    it("returns denied when user holds none of the anyOf codes", () => {
      mockSession.setSession({
        role: "",
        username: "newbie",
        isSuper: false,
        platformRoles: [],
        permissionCodes: [],
      })
      const result = usePageGate({ anyOf: ["agent:read", "tenant:manage"] })
      expect(result).toEqual({ status: "denied" })
    })

    it("returns allowed for empty anyOf array", () => {
      mockSession.setSession({
        role: "",
        username: "user",
        isSuper: false,
        platformRoles: [],
        permissionCodes: [],
      })
      const result = usePageGate({ anyOf: [] })
      expect(result).toEqual({ status: "allowed" })
    })
  })

  describe("super admin bypass", () => {
    it("super admin bypasses required permissions", () => {
      mockSession.setSession({
        role: "admin",
        username: "super",
        isSuper: true,
        platformRoles: ["super_admin"],
        permissionCodes: [],
      })
      const result = usePageGate({ required: ["tenant:manage", "platform:role:manage"] })
      expect(result).toEqual({ status: "allowed" })
    })

    it("super admin bypasses anyOf permissions", () => {
      mockSession.setSession({
        role: "admin",
        username: "super",
        isSuper: true,
        platformRoles: ["super_admin"],
        permissionCodes: [],
      })
      const result = usePageGate({ anyOf: ["tenant:manage"] })
      expect(result).toEqual({ status: "allowed" })
    })
  })
})