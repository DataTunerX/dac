import axios from "axios"

/** Extract a user-facing message from axios / unknown errors. */
export function getApiErrorMessage(err: unknown, fallback = "请求失败"): string {
  if (axios.isAxiosError(err)) {
    const data = err.response?.data as unknown
    if (data && typeof data === "object") {
      const msg = (data as Record<string, unknown>).message
      if (typeof msg === "string" && msg.trim()) return msg.trim()
    }
    if (typeof err.message === "string" && err.message.trim()) return err.message.trim()
  }
  if (err instanceof Error && err.message.trim()) return err.message.trim()
  return fallback
}
