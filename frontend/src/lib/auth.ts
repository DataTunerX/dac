import { jwtDecode } from "jwt-decode"
import { getAuthToken } from "@/lib/auth-session"

interface DecodedToken {
  user_id: string
  username: string
  role: string
  exp: number
}

export const getUserRole = (): string => {
  const token = getAuthToken()
  if (!token) return "anonymous"

  try {
    const decoded = jwtDecode<DecodedToken>(token)
    return decoded.role || "user" // Default to "user" if role is missing but token is valid
  } catch (error) {
    console.error("Failed to decode token:", error)
    return "anonymous"
  }
}

export const isAdmin = (): boolean => {
  return getUserRole() === "admin"
}
