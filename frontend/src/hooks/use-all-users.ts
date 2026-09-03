"use client"

import { useCallback } from "react"
import useSWR from "swr"

import { listUsers } from "@/lib/rbac-api"
import type { UserResponse } from "@/lib/api-types"

const PAGE_SIZE = 100 // backend caps page_size at 100

export async function fetchAllUsers(): Promise<UserResponse[]> {
  const out: UserResponse[] = []
  let page = 1
  for (;;) {
    const res = await listUsers({ page, page_size: PAGE_SIZE })
    out.push(...(res.users ?? []))
    if (out.length >= (res.total ?? out.length) || (res.users ?? []).length === 0) break
    page += 1
    if (page > 200) break // hard safety cap
  }
  return out
}

/**
 * All registered users across pages, for client-side search / id→username
 * resolution. The backend only supports page/page_size, so the UI does the
 * rest without any backend change.
 */
export function useAllUsers(reloadKey?: number) {
  const { data, isLoading, mutate } = useSWR(
    ["rbac-all-users", reloadKey ?? 0],
    fetchAllUsers,
    { revalidateOnFocus: false, keepPreviousData: true },
  )

  const refresh = useCallback(() => {
    void mutate()
  }, [mutate])

  return { users: data ?? [], isLoading, refresh }
}
