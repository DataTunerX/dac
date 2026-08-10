import axios, { type InternalAxiosRequestConfig } from "axios"
import {
  clearClientSession,
  isAuthRefreshPath,
  redirectToLogin,
  refreshAuthSession,
} from "@/lib/auth-session"

type RetryConfig = InternalAxiosRequestConfig & { _authRetry?: boolean }

// Axios instance for DAC API.
// - baseURL: /api/v1
// - withCredentials: send HttpOnly dac_token cookie
// - response: unwrap Go envelope { code, message, data } so res.data is the payload.
//   Use res.data only; do not double-unwrap (res.data.data). See docs/api-contract-go-frontend.md.
// - 401: single-flight /auth/refresh → retry once → else clear session + redirect
export const api = axios.create({
  baseURL: "/api/v1",
  withCredentials: true,
})

const SUCCESS_ENVELOPE_CODES = new Set(["SUCCESS", "CREATED", "ACCEPTED", "0", 0])

function redirectAfterAuthFailure() {
  if (typeof window === "undefined") return
  const path = window.location.pathname || "/"
  const search = window.location.search || ""
  const hash = window.location.hash || ""
  const next = `${path}${search}${hash}`
  if (!path.startsWith("/login") && !path.startsWith("/register")) {
    redirectToLogin(next)
  }
}

api.interceptors.response.use(
  (res) => {
    const body = res.data as unknown
    if (body && typeof body === "object") {
      const r = body as Record<string, unknown>
      // Reject business-error envelopes that arrived with HTTP 2xx.
      if ("code" in r && r.code != null && !SUCCESS_ENVELOPE_CODES.has(r.code as string | number)) {
        const message =
          typeof r.message === "string" && r.message.trim()
            ? r.message
            : "请求失败"
        return Promise.reject(
          new axios.AxiosError(
            message,
            String(r.code),
            res.config,
            res.request,
            {
              ...res,
              data: body,
              status: res.status,
              statusText: res.statusText,
              headers: res.headers,
              config: res.config,
            },
          ),
        )
      }
      if (r.data !== undefined) {
        return { ...res, data: r.data }
      }
    }
    return res
  },
  async (err) => {
    if (!axios.isAxiosError(err) || err.response?.status !== 401) {
      return Promise.reject(err)
    }

    const cfg = err.config as RetryConfig | undefined
    const url = `${cfg?.baseURL ?? ""}${cfg?.url ?? ""}`
    const canRefresh = cfg && !cfg._authRetry && !isAuthRefreshPath(url)

    if (canRefresh) {
      const refreshed = await refreshAuthSession()
      if (refreshed) {
        cfg._authRetry = true
        return api.request(cfg)
      }
    }

    clearClientSession()
    redirectAfterAuthFailure()
    return Promise.reject(err)
  },
)
