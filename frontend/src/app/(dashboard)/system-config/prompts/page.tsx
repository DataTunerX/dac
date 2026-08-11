"use client"

import { useEffect } from "react"
import { useRouter } from "next/navigation"

export default function PromptsPage() {
  const router = useRouter()
  useEffect(() => { router.replace("/configmaps?type=prompts") }, [router])
  return null
}
