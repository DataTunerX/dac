"use client"

import { useCallback } from "react"
import useSWR from "swr"

import { listTenants } from "@/lib/rbac-api"
import type { RbacTenant } from "@/lib/api-types"

const PAGE_SIZE = 100 // backend caps page_size at 100

export async function fetchAllTenants(): Promise<RbacTenant[]> {
  const out: RbacTenant[] = []
  let page = 1
  for (;;) {
    const res = await listTenants({ page, page_size: PAGE_SIZE })
    out.push(...(res.items ?? []))
    if (out.length >= (res.totalCount ?? out.length) || (res.items ?? []).length === 0) break
    page += 1
    if (page > 200) break // hard safety cap
  }
  return out
}

/**
 * All tenants across pages (backend only supports page/page_size, no search).
 * Client-side search filters operate on this list, so the UI scales to
 * thousands of tenants without any backend change.
 */
export function useAllTenants(reloadKey?: number) {
  const { data, isLoading, isValidating, mutate } = useSWR(
    ["rbac-all-tenants", reloadKey ?? 0],
    fetchAllTenants,
    { revalidateOnFocus: false, keepPreviousData: true },
  )

  const refresh = useCallback(() => {
    void mutate()
  }, [mutate])

  return { tenants: data ?? [], isLoading, isValidating, refresh }
}
