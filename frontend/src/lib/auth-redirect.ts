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

function hostWithoutPort(host: string): string {
  if (host.startsWith("[")) {
    const end = host.indexOf("]")
    return end >= 0 ? host.slice(0, end + 1) : host
  }
  const idx = host.lastIndexOf(":")
  if (idx > 0 && /^\d+$/.test(host.slice(idx + 1))) return host.slice(0, idx)
  return host
}

function isPrivateOrLocalHost(host: string): boolean {
  const h = hostWithoutPort(host).toLowerCase()
  if (h === "localhost" || h === "127.0.0.1" || h === "::1" || h === "[::1]") return true
  if (h.startsWith("10.")) return true
  if (/^192\.168\./.test(h)) return true
  if (/^172\.(1[6-9]|2\d|3[01])\./.test(h)) return true
  return false
}

function parseAllowedHosts(): Set<string> {
  const raw = process.env.ALLOWED_HOSTS || process.env.NEXT_PUBLIC_ALLOWED_HOSTS || ""
  return new Set(
    raw
      .split(",")
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean)
      .map((h) => hostWithoutPort(h).toLowerCase()),
  )
}

function isHostAllowed(host: string, allowed: Set<string>): boolean {
  if (allowed.size === 0) return true
  return allowed.has(hostWithoutPort(host).toLowerCase())
}

/**
 * Resolve public Host for login redirects.
 * - Behind a reverse proxy (Host is loopback/private): prefer X-Forwarded-Host.
 * - When Host is a public name: do not trust a differing X-Forwarded-Host (spoofing).
 * - Optional ALLOWED_HOSTS allowlist further restricts accepted hosts.
 */
function resolveTrustedHost(headers: Headers, requestUrl: RequestUrlLike): string {
  const forwardedHost = sanitizeForwardedHost(pickForwardedValue(headers.get("x-forwarded-host")))
  const directHost = sanitizeForwardedHost(headers.get("host")?.trim() || null)
  const allowed = parseAllowedHosts()

  if (forwardedHost && !isHostAllowed(forwardedHost, allowed)) {
    // Spoofed / disallowed forwarded host
  } else if (forwardedHost && directHost && isPrivateOrLocalHost(directHost)) {
    return forwardedHost
  } else if (forwardedHost && directHost && hostWithoutPort(forwardedHost) === hostWithoutPort(directHost)) {
    return forwardedHost
  } else if (forwardedHost && !directHost && isHostAllowed(forwardedHost, allowed)) {
    return forwardedHost
  }

  if (directHost && isHostAllowed(directHost, allowed)) return directHost
  if (forwardedHost && isHostAllowed(forwardedHost, allowed) && allowed.size > 0) return forwardedHost
  return requestUrl.host
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
  const host = resolveTrustedHost(headers, requestUrl)
  const forwardedPort = pickForwardedValue(headers.get("x-forwarded-port"))
  const usedForwardedHost =
    sanitizeForwardedHost(pickForwardedValue(headers.get("x-forwarded-host"))) === host

  if (
    !usedForwardedHost ||
    !forwardedPort ||
    hasExplicitPort(host) ||
    isDefaultPort(protocol, forwardedPort)
  ) {
    return `${protocol}://${host}`
  }

  return `${protocol}://${host}:${forwardedPort}`
}

export function buildLoginRedirectUrl(headers: Headers, requestUrl: RequestUrlLike): URL {
  const next = encodeURIComponent(`${requestUrl.pathname}${requestUrl.search}`)
  return new URL(`${LOGIN_PATH}?next=${next}`, buildExternalOrigin(headers, requestUrl))
}
