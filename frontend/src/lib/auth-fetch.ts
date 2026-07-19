import { clearAuthToken, getAuthToken, redirectToLogin } from "@/lib/auth-session"

export type AuthFetchInit = RequestInit & {
  /** Skip global 401 → login redirect (e.g. login form itself). */
  skipAuthRedirect?: boolean
}

/**
 * fetch wrapper shared by chat streaming and other non-axios calls.
 * Attaches Bearer from dac_token and mirrors api.ts 401 handling.
 */
export async function authFetch(input: string | URL, init: AuthFetchInit = {}): Promise<Response> {
  const { skipAuthRedirect, headers: initHeaders, ...rest } = init
  const headers = new Headers(initHeaders)
  const token = getAuthToken()
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`)
  }

  const res = await fetch(input, { ...rest, headers })

  if (res.status === 401 && !skipAuthRedirect && typeof window !== "undefined") {
    clearAuthToken()
    const path = window.location.pathname || "/"
    const search = window.location.search || ""
    const hash = window.location.hash || ""
    if (!path.startsWith("/login") && !path.startsWith("/register")) {
      redirectToLogin(`${path}${search}${hash}`)
    }
  }

  return res
}
