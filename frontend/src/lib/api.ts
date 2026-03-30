import axios, { type InternalAxiosRequestConfig } from "axios"
import { clearAuthToken, getAuthToken, redirectToLogin } from "@/lib/auth-session"

// Axios instance for DAC API.
// - baseURL: /api/v1
// - request: attach Bearer token if exists (dac_token)
// - response: unwrap Go envelope { code, message, data } so res.data is the payload.
//   Use res.data only; do not double-unwrap (res.data.data). See docs/api-contract-go-frontend.md.
export const api = axios.create({
  baseURL: "/api/v1",
})

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = getAuthToken()
  if (token) {
    config.headers = config.headers ?? {}
    const headers = config.headers as Record<string, string>
    headers["Authorization"] = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (res) => {
    const body = res.data as unknown
    if (body && typeof body === "object") {
      const r = body as Record<string, unknown>
      if (r.data !== undefined) {
        return { ...res, data: r.data }
      }
    }
    return res
  },
  (err) => {
    // Global 401 handling:
    // - clear token cookie
    // - redirect to login with next=...
    // IMPORTANT: must be safe in non-browser contexts.
    if (axios.isAxiosError(err) && err.response?.status === 401) {
      clearAuthToken()
      if (typeof window !== "undefined") {
        const path = window.location.pathname || "/"
        const search = window.location.search || ""
        const hash = window.location.hash || ""
        const next = `${path}${search}${hash}`

        // Avoid redirect loop on auth pages.
        if (!path.startsWith("/login") && !path.startsWith("/register")) {
          redirectToLogin(next)
        }
      }
    }
    return Promise.reject(err)
  }
)

