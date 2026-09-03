/**
 * Client JWT helpers. Does NOT verify signatures (no secret in the browser).
 * Used only to decode browser-visible JWT data for non-authoritative UX helpers.
 */
import { jwtDecode } from "jwt-decode"

export type JwtPayload = {
  exp?: number
  orig_iat?: number
  user_id?: string
  username?: string
}

export function decodeJwtPayload(token: string): JwtPayload | null {
  const trimmed = token.trim()
  if (!trimmed) return null
  const parts = trimmed.split(".")
  if (parts.length !== 3) return null
  try {
    const payload = jwtDecode<JwtPayload>(trimmed)
    if (!payload || typeof payload !== "object") return null
    return payload
  } catch {
    return null
  }
}

/** True when token has 3 segments and exp is missing or in the future (30s skew). */
export function isJwtUsable(token: string | undefined | null, nowMs = Date.now()): boolean {
  if (!token || !token.trim()) return false
  const payload = decodeJwtPayload(token)
  if (!payload) return false
  if (typeof payload.exp !== "number") return true
  return payload.exp * 1000 > nowMs - 30_000
}

export function getJwtUsername(token: string | undefined | null): string {
  if (!isJwtUsable(token)) return ""
  const payload = decodeJwtPayload(token!)
  const username = payload?.username
  return typeof username === "string" && username.trim() ? username.trim() : ""
}
