/**
 * SWR fetcher for DAC API. Uses existing api instance (auth, baseURL, unwrap).
 * Use with useSWR(key, apiFetcher) for request deduplication and cache (Vercel React Best Practices 4.3).
 */
import { api } from "@/lib/api"

export function apiFetcher<T = unknown>(url: string): Promise<T> {
  return api.get(url).then((res) => res.data as T)
}

/** Fetcher that supports [url, params] key for GET with query params (dedup by key). */
export function apiFetcherWithParams<T = unknown>(
  key: string | [string, Record<string, unknown>]
): Promise<T> {
  if (Array.isArray(key)) {
    const [url, params] = key
    return api.get(url, { params }).then((res) => res.data as T)
  }
  return api.get(key).then((res) => res.data as T)
}
