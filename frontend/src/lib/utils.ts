import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function decodeJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const parts = token.split(".")
    if (parts.length < 2) return null
    const payload = parts[1]
    const base64 = payload.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((payload.length + 3) % 4)
    const json = typeof atob === "function" ? atob(base64) : Buffer.from(base64, "base64").toString()
    const obj = JSON.parse(json)
    return typeof obj === "object" && obj !== null ? (obj as Record<string, unknown>) : null
  } catch {
    return null
  }
}

export function initialFromUsername(username?: string) {
  const s = (username || "").trim()
  if (!s) return "U"
  return s[0].toUpperCase()
}
