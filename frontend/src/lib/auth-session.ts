import Cookies from "js-cookie"

const AUTH_COOKIE_NAME = "dac_token"
const AUTH_COOKIE_OPTIONS = {
  expires: 7,
  path: "/",
  sameSite: "lax" as const,
}

function normalizeRelativePath(rawPath: string): string {
  if (!rawPath || !rawPath.startsWith("/")) return "/"
  if (rawPath.startsWith("//")) return "/"
  return rawPath
}

export function getAuthToken(): string {
  return Cookies.get(AUTH_COOKIE_NAME) ?? ""
}

export function persistAuthToken(token: string): void {
  Cookies.set(AUTH_COOKIE_NAME, token, AUTH_COOKIE_OPTIONS)
}

export function clearAuthToken(): void {
  Cookies.remove(AUTH_COOKIE_NAME, { path: "/" })
  Cookies.remove(AUTH_COOKIE_NAME)
}

export function getSafeNextPath(search: string): string {
  return normalizeRelativePath(new URLSearchParams(search).get("next") || "")
}

export function redirectToLogin(nextPath: string): void {
  const safeNextPath = normalizeRelativePath(nextPath)
  window.location.replace(`/login?next=${encodeURIComponent(safeNextPath)}`)
}

export function navigateAfterAuth(nextPath: string): void {
  window.location.replace(normalizeRelativePath(nextPath))
}
