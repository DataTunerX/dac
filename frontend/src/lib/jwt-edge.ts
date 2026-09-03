/**
 * Edge/server JWT helpers. Verification fails closed when no signing secret is set.
 */
import { errors, jwtVerify, type JWTPayload } from "jose"

const DEFAULT_JWT_MAX_REFRESH_MS = 7 * 24 * 60 * 60 * 1000
const DURATION_UNITS_MS = {
  ms: 1,
  s: 1000,
  m: 60 * 1000,
  h: 60 * 60 * 1000,
  d: 24 * 60 * 60 * 1000,
} as const

function getRuntimeEnv(name: string): string | undefined {
  // Dynamic lookup prevents Next.js from inlining deployment-specific values at build time.
  return process.env[name]
}

export function getJwtSecretKey(): Uint8Array | null {
  const secret = getRuntimeEnv("DAC_JWT_SECRET") || getRuntimeEnv("JWT_SECRET")
  if (!secret) return null
  return new TextEncoder().encode(secret)
}

export function getJwtMaxRefreshMs(
  raw = getRuntimeEnv("DAC_JWT_MAX_REFRESH"),
): number {
  if (!raw?.trim()) return DEFAULT_JWT_MAX_REFRESH_MS
  const match = raw.trim().match(/^(\d+(?:\.\d+)?)(ms|s|m|h|d)$/)
  if (!match) return 0
  const value = Number(match[1])
  const unit = match[2] as keyof typeof DURATION_UNITS_MS
  if (!Number.isFinite(value) || value <= 0) return 0
  return value * DURATION_UNITS_MS[unit]
}

/** Signature-verified when secret present; expired-but-signed tokens still return payload. */
export async function readJwtPayload(token: string): Promise<JWTPayload | null> {
  const trimmed = token.trim()
  if (!trimmed) return null

  const key = getJwtSecretKey()
  if (!key) return null

  try {
    const { payload } = await jwtVerify(trimmed, key)
    return payload
  } catch (err) {
    if (err instanceof errors.JWTExpired && err.payload) {
      return err.payload
    }
    return null
  }
}

export function isPayloadUsable(payload: JWTPayload, nowMs = Date.now()): boolean {
  if (typeof payload.exp !== "number") return true
  return payload.exp * 1000 > nowMs - 30_000
}

export function isPayloadRefreshable(payload: JWTPayload, nowMs = Date.now()): boolean {
  const origIat = payload.orig_iat
  if (typeof origIat !== "number") return false
  const maxRefreshMs = getJwtMaxRefreshMs()
  if (maxRefreshMs <= 0) return false
  return origIat * 1000 > nowMs - maxRefreshMs
}

export function isPayloadAcceptable(payload: JWTPayload, nowMs = Date.now()): boolean {
  return isPayloadUsable(payload, nowMs) || isPayloadRefreshable(payload, nowMs)
}

export function usernameFromPayload(payload: JWTPayload): string {
  const username = payload.username
  return typeof username === "string" ? username : ""
}
