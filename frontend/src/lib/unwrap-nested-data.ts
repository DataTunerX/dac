/**
 * Unwrap Go DTOs shaped as `{ data: T }` after the axios envelope interceptor
 * already peeled `{ code, message, data: { data: T } }` → `{ data: T }`.
 */
export function unwrapNestedData<T extends object>(payload: unknown): T | null {
  if (!payload || typeof payload !== "object") return null
  const outer = payload as Record<string, unknown>
  const inner = outer.data
  if (inner && typeof inner === "object") return inner as T
  // Already flat (or missing nested wrapper)
  return outer as T
}
