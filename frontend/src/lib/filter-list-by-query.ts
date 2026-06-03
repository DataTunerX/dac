/** Client-side list search: case-insensitive match on joined string fields. */
export function filterListByQuery<T>(
  items: readonly T[],
  query: string,
  getSearchText: (item: T) => string
): T[] {
  const q = query.trim().toLowerCase()
  if (!q) return items as T[]
  return items.filter((item) => getSearchText(item).toLowerCase().includes(q))
}
