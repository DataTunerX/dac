const LOGIN_PATH = "/login"
const ROOT_PATH = "/"

const AUTH_REQUIRED_PREFIXES = [
  "/agents",
  "/semantic-groups",
  "/datasources",
  "/configmaps",
  "/system-config",
  "/observability",
  "/infra",
] as const
const PUBLIC_PATH_PREFIXES = [LOGIN_PATH, "/register"] as const

type RequestUrlLike = Pick<URL, "pathname" | "search" | "protocol" | "host">

function matchesPathPrefix(pathname: string, prefix: string): boolean {
  return pathname === prefix || pathname.startsWith(`${prefix}/`)
}

function pickForwardedValue(value: string | null): string | null {
  const candidate = value?.split(",")[0]?.trim()
  return candidate ? candidate : null
}

function sanitizeForwardedHost(host: string | null): string | null {
  if (!host) return null
  if (host.includes("://")) return null
  if (host.includes("/") || /\s/.test(host)) return null
  return host
}

function hasExplicitPort(host: string): boolean {
  if (host.startsWith("[")) return host.includes("]:")

  const colonCount = (host.match(/:/g) ?? []).length
  if (colonCount === 0) return false
  if (colonCount === 1) return true
  return false
}

function isDefaultPort(protocol: string, port: string): boolean {
  return (protocol === "http" && port === "80") || (protocol === "https" && port === "443")
}

export function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATH_PREFIXES.some((prefix) => matchesPathPrefix(pathname, prefix))
}

export function requiresAuth(pathname: string): boolean {
  if (pathname === ROOT_PATH || pathname === "") return true
  return AUTH_REQUIRED_PREFIXES.some((prefix) => matchesPathPrefix(pathname, prefix))
}

export function buildExternalOrigin(headers: Headers, requestUrl: RequestUrlLike): string {
  const protocol = pickForwardedValue(headers.get("x-forwarded-proto")) ?? requestUrl.protocol.replace(/:$/, "")
  const forwardedHost = sanitizeForwardedHost(pickForwardedValue(headers.get("x-forwarded-host")))
  const directHost = sanitizeForwardedHost(headers.get("host")?.trim() || null)
  const host = forwardedHost ?? directHost ?? requestUrl.host
  const forwardedPort = pickForwardedValue(headers.get("x-forwarded-port"))

  if (!forwardedPort || hasExplicitPort(host) || isDefaultPort(protocol, forwardedPort)) {
    return `${protocol}://${host}`
  }

  return `${protocol}://${host}:${forwardedPort}`
}

export function buildLoginRedirectUrl(headers: Headers, requestUrl: RequestUrlLike): URL {
  const next = encodeURIComponent(`${requestUrl.pathname}${requestUrl.search}`)
  return new URL(`${LOGIN_PATH}?next=${next}`, buildExternalOrigin(headers, requestUrl))
}
