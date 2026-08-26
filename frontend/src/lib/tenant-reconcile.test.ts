/**
 * @vitest-environment jsdom
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest"

// Module-level state that reconcileTenant reaches through tenant-context.
const tenantState = vi.hoisted(() => ({
  activeTenantId: "t-active" as string | null,
  stored: {} as Record<string, string>,
}))

vi.mock("@/lib/tenant-context", () => ({
  getActiveTenantId: () => tenantState.activeTenantId,
  setActiveTenantId: (id: string | null) => {
    tenantState.activeTenantId = id
  },
  TENANT_HEADER_NAME: "X-Tenant-Id",
}))

import { reconcileTenant, TENANT_RECONCILED_EVENT, type TenantReconcileResult } from "./tenant-reconcile"

describe("tenant-reconcile", () => {
  let fetchMock: ReturnType<typeof vi.fn>
  let dispatchedEvents: CustomEvent[] = []

  beforeEach(() => {
    tenantState.activeTenantId = "t-active"
    dispatchedEvents = []

    fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)

    vi.spyOn(window, "dispatchEvent").mockImplementation((event: Event) => {
      dispatchedEvents.push(event as CustomEvent)
      return true
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  describe("when there is no active tenant", () => {
    it("returns switched=false with empty tenants and null id", async () => {
      tenantState.activeTenantId = null
      const result = await reconcileTenant()
      expect(result).toEqual<TenantReconcileResult>({
        switched: false,
        tenants: [],
        activeTenantId: null,
      })
      expect(fetchMock).not.toHaveBeenCalled()
    })
  })

  describe("when the tenant list fetch succeeds", () => {
    it("clears the invalid tenant, fetches, and selects the first available tenant", async () => {
      fetchMock.mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            code: "SUCCESS",
            data: [
              { id: "t-new", code: "new-tenant", name: "New Tenant", status: "active" },
              { id: "t-other", code: "other", name: "Other", status: "active" },
            ],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )

      const result = await reconcileTenant()

      expect(tenantState.activeTenantId).toBe("t-new")
      expect(result.switched).toBe(true)
      expect(result.tenants).toHaveLength(2)
      expect(result.activeTenantId).toBe("t-new")

      // Verify the fetch was called without X-Tenant-Id header
      expect(fetchMock).toHaveBeenCalledWith("/api/v1/rbac/me/tenants", {
        credentials: "include",
        headers: { "Content-Type": "application/json" },
      })
    })

    it("switched stays false when the previously active tenant is still first", async () => {
      tenantState.activeTenantId = "t-first"
      fetchMock.mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            code: "SUCCESS",
            data: [{ id: "t-first", code: "same", name: "Same", status: "active" }],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )

      const result = await reconcileTenant()

      expect(result.switched).toBe(false)
      expect(result.activeTenantId).toBe("t-first")
    })

    it("dispatches TENANT_RECONCILED_EVENT with the new state", async () => {
      fetchMock.mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            code: "SUCCESS",
            data: [{ id: "t-new", code: "new", name: "New", status: "active" }],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )

      await reconcileTenant()

      expect(dispatchedEvents).toHaveLength(1)
      const evt = dispatchedEvents[0]
      expect(evt.type).toBe(TENANT_RECONCILED_EVENT)
      expect(evt.detail).toEqual({
        tenants: [{ id: "t-new", code: "new", name: "New", status: "active" }],
        activeTenantId: "t-new",
      })
    })
  })

  describe("when the tenant list fetch returns empty data", () => {
    it("sets activeTenantId to null and returns switched=true", async () => {
      fetchMock.mockResolvedValueOnce(
        new Response(
          JSON.stringify({ code: "SUCCESS", data: [] }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )

      const result = await reconcileTenant()

      expect(tenantState.activeTenantId).toBeNull()
      expect(result.switched).toBe(true)
      expect(result.tenants).toEqual([])
      expect(result.activeTenantId).toBeNull()
    })
  })

  describe("when fetch fails with network error", () => {
    it("swallows the error, keeps activeTenantId cleared, and returns empty tenants", async () => {
      fetchMock.mockRejectedValueOnce(new Error("Network Error"))

      const result = await reconcileTenant()

      expect(tenantState.activeTenantId).toBeNull()
      expect(result.switched).toBe(true)
      expect(result.tenants).toEqual([])
      expect(result.activeTenantId).toBeNull()
    })
  })

  describe("when fetch returns non-ok status", () => {
    it("treats 403 as no tenants and returns empty", async () => {
      fetchMock.mockResolvedValueOnce(
        new Response("Forbidden", { status: 403 }),
      )

      const result = await reconcileTenant()

      expect(tenantState.activeTenantId).toBeNull()
      expect(result.switched).toBe(true)
      expect(result.tenants).toEqual([])
      expect(result.activeTenantId).toBeNull()
    })

    it("treats 500 as no tenants and returns empty", async () => {
      fetchMock.mockResolvedValueOnce(
        new Response("Internal Server Error", { status: 500 }),
      )

      const result = await reconcileTenant()

      expect(tenantState.activeTenantId).toBeNull()
      expect(result.switched).toBe(true)
      expect(result.tenants).toEqual([])
      expect(result.activeTenantId).toBeNull()
    })
  })

  describe("when fetch response has no data field", () => {
    it("falls back to empty tenants array", async () => {
      fetchMock.mockResolvedValueOnce(
        new Response(
          JSON.stringify({ code: "SUCCESS" }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )

      const result = await reconcileTenant()

      expect(result.tenants).toEqual([])
      expect(result.activeTenantId).toBeNull()
    })
  })
})