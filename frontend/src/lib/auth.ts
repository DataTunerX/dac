import { getClientSession } from "@/lib/auth-session"

export const getUserRole = (): string => {
  return getClientSession()?.role || "anonymous"
}

export const isAdmin = (): boolean => {
  return getUserRole() === "admin"
}
