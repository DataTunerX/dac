import axios, { type InternalAxiosRequestConfig } from "axios"
import {
  clearClientSession,
  isAuthRefreshPath,
  redirectToLogin,
  refreshAuthSession,
} from "@/lib/auth-session"
import { getActiveTenantId, TENANT_HEADER_NAME } from "@/lib/tenant-context"
import { reconcileTenant } from "@/lib/tenant-reconcile"

type RetryConfig = InternalAxiosRequestConfig & { _authRetry?: boolean; _tenantRetry?: boolean }

// Axios instance for DAC API.
// - baseURL: /api/v1
// - withCredentials: send HttpOnly dac_token cookie
// - response: unwrap Go envelope { code, message, data } so res.data is the payload.
//   Use res.data only; do not double-unwrap (res.data.data). See docs/api-contract-go-frontend.md.
// - 401: single-flight /auth/refresh → retry once → else clear session + redirect
// - 403: when the active tenant is invalid, reconcile → retry once
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

/** Whether a URL is a tenant-scoped API call that carries X-Tenant-Id. */
function isTenantScoped(url: string): boolean {
  return url.startsWith("/api/v1/") && !isAuthRefreshPath(url) && !url.includes("/rbac/me/tenants")
}

api.interceptors.request.use(function onRequest(config) {
  const tenantId = getActiveTenantId()
  if (tenantId && config.headers) {
    config.headers.set(TENANT_HEADER_NAME, tenantId)
  }
  return config
})

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
    if (!axios.isAxiosError(err)) {
      return Promise.reject(err)
    }

    // ---- 401: session expired → refresh → retry once ----
    if (err.response?.status === 401) {
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
    }

    // ---- 403: active tenant may be invalid → reconcile → retry once ----
    if (err.response?.status === 403) {
      const cfg = err.config as RetryConfig | undefined
      const url = `${cfg?.baseURL ?? ""}${cfg?.url ?? ""}`
      const tenantId = getActiveTenantId()
      if (tenantId && cfg && !cfg._tenantRetry && isTenantScoped(url)) {
        const result = await reconcileTenant()
        if (result.switched || result.activeTenantId !== tenantId) {
          cfg._tenantRetry = true
          return api.request(cfg)
        }
      }
    }

    return Promise.reject(err)
  },
)
