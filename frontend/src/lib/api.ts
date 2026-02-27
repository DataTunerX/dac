import axios from "axios"
import Cookies from "js-cookie"

// Axios instance for DAC API.
// - baseURL: /api/v1
// - request: attach Bearer token if exists (dac_token)
// - response: unwrap standard envelope { code, message, data }
export const api = axios.create({
  baseURL: "/api/v1",
})

api.interceptors.request.use((config) => {
  const token = Cookies.get("dac_token")
  if (token) {
    config.headers = config.headers || {}
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ;(config.headers as any)["Authorization"] = `Bearer ${token}`
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
      Cookies.remove("dac_token")
      if (typeof window !== "undefined") {
        const path = window.location.pathname || "/"
        const search = window.location.search || ""
        const hash = window.location.hash || ""
        const next = `${path}${search}${hash}`

        // Avoid redirect loop on auth pages.
        if (!path.startsWith("/login") && !path.startsWith("/register")) {
          window.location.href = `/login?next=${encodeURIComponent(next)}`
        }
      }
    }
    return Promise.reject(err)
  }
)

