import { getAuthToken } from "@/lib/auth-session"
import { getJwtRole, isJwtUsable } from "@/lib/jwt-client"

export const getUserRole = (): string => {
  const token = getAuthToken()
  if (!token || !isJwtUsable(token)) return "anonymous"
  return getJwtRole(token)
}

export const isAdmin = (): boolean => {
  return getUserRole() === "admin"
}
