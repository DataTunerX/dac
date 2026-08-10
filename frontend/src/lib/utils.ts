import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** @deprecated Prefer `@/lib/jwt-client` — kept as a thin re-export for existing imports. */
export { decodeJwtPayload } from "@/lib/jwt-client"

export function initialFromUsername(username?: string) {
  const s = (username || "").trim()
  if (!s) return "U"
  return s[0].toUpperCase()
}
