import { afterEach, describe, expect, it, vi } from "vitest"

const originalWindow = globalThis.window
const originalDocument = globalThis.document
const originalFetch = globalThis.fetch

function installBrowserGlobals() {
  const windowTarget = new EventTarget()
  const documentTarget = new EventTarget()
  Object.defineProperty(globalThis, "window", {
    value: windowTarget,
    configurable: true,
    writable: true,
  })
  Object.defineProperty(globalThis, "document", {
    value: documentTarget,
    configurable: true,
    writable: true,
  })
  return { windowTarget, documentTarget }
}

function sessionResponse(role: string, username: string) {
  return new Response(
    JSON.stringify({ authenticated: true, role, username }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  )
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.resetModules()
  Object.defineProperty(globalThis, "window", {
    value: originalWindow,
    configurable: true,
    writable: true,
  })
  Object.defineProperty(globalThis, "document", {
    value: originalDocument,
    configurable: true,
    writable: true,
  })
  Object.defineProperty(globalThis, "fetch", {
    value: originalFetch,
    configurable: true,
    writable: true,
  })
})

describe("auth store hydration", () => {
  it("re-fetches the server session when the window regains focus", async () => {
    const { windowTarget } = installBrowserGlobals()
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(sessionResponse("admin", "alice"))
      .mockResolvedValueOnce(sessionResponse("user", "bob"))
    Object.defineProperty(globalThis, "fetch", {
      value: fetchMock,
      configurable: true,
      writable: true,
    })

    const store = await import("./auth-store")
    const session = await import("./auth-session")
    const unsubscribe = store.subscribeAuth(() => {})

    await vi.waitFor(() => {
      expect(session.getClientSession()).toEqual({ role: "admin", username: "alice" })
    })

    windowTarget.dispatchEvent(new Event("focus"))

    await vi.waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2)
      expect(session.getClientSession()).toEqual({ role: "user", username: "bob" })
    })
    unsubscribe()
  })

  it("preserves an established session when hydration fails transiently", async () => {
    installBrowserGlobals()
    const fetchMock = vi.fn().mockRejectedValue(new Error("temporary network failure"))
    Object.defineProperty(globalThis, "fetch", {
      value: fetchMock,
      configurable: true,
      writable: true,
    })

    const session = await import("./auth-session")
    const store = await import("./auth-store")
    session.establishSession({ role: "admin", username: "alice" })
    const unsubscribe = store.subscribeAuth(() => {})

    await vi.waitFor(() => {
      expect(store.isAuthSessionHydrated()).toBe(true)
    })
    expect(session.getClientSession()).toEqual({ role: "admin", username: "alice" })
    unsubscribe()
  })
})
