import {
  clearClientSession,
  isAuthRefreshPath,
  redirectToLogin,
  refreshAuthSession,
} from "@/lib/auth-session"

export type AuthFetchInit = RequestInit & {
  /** Skip global 401 → login redirect (e.g. login form itself / chat handlers). */
  skipAuthRedirect?: boolean
}

function resolveUrl(input: string | URL): string {
  if (typeof input === "string") return input
  return input.toString()
}

/**
 * fetch wrapper shared by chat streaming and other non-axios calls.
 * Sends cookies (credentials) — no Bearer from JS-readable token.
 * Mirrors api.ts 401 → single-flight refresh → retry once.
 */
export async function authFetch(input: string | URL, init: AuthFetchInit = {}): Promise<Response> {
  const { skipAuthRedirect, headers: initHeaders, credentials, ...rest } = init
  const headers = new Headers(initHeaders)
  const url = resolveUrl(input)

  const doFetch = () =>
    fetch(input, {
      ...rest,
      headers,
      credentials: credentials ?? "include",
    })

  let res = await doFetch()

  if (res.status === 401 && !isAuthRefreshPath(url)) {
    const refreshed = await refreshAuthSession()
    if (refreshed) {
      res = await doFetch()
    }
  }

  if (res.status === 401 && !skipAuthRedirect && typeof window !== "undefined") {
    clearClientSession()
    const path = window.location.pathname || "/"
    const search = window.location.search || ""
    const hash = window.location.hash || ""
    if (!path.startsWith("/login") && !path.startsWith("/register")) {
      redirectToLogin(`${path}${search}${hash}`)
    }
  }

  return res
}
