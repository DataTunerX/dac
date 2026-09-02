import { cookies } from "next/headers"
import { NextResponse, type NextRequest } from "next/server"
import {
  isPayloadAcceptable,
  readJwtPayload,
  usernameFromPayload,
} from "@/lib/jwt-edge"

type MePayload = {
  authenticated: boolean
  username: string
  isSuper: boolean
  platformRoles: string[]
  permissionCodes: string[]
}

const EMPTY_ME: MePayload = {
  authenticated: false,
  username: "",
  isSuper: false,
  platformRoles: [],
  permissionCodes: [],
}

async function fetchMeFromBackend(request: NextRequest): Promise<MePayload | null> {
  try {
    // Prefer the configured backend address. Self-invoking our own origin is
    // unreliable in production: Next.js resolves same-origin fetches
    // in-process, where /api/v1/* has no route (rewrites are only active in
    // dev), so the call 404s before ever reaching nginx.
    const backend = (process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || "")
      .replace(/\/+$/, "")
    const base = backend || `${request.nextUrl.protocol}//${request.nextUrl.host}`
    const res = await fetch(`${base}/api/v1/users/me`, {
      headers: {
        // Forward the HttpOnly session cookie so the backend authenticates us.
        cookie: request.headers.get("cookie") ?? "",
      },
      credentials: "include",
      cache: "no-store",
    })
    if (!res.ok) return null
    const body = (await res.json()) as { code?: string; data?: unknown }
    if (body.code !== "SUCCESS") return null
    const data = body.data as {
      user?: { username?: string }
      isSuper?: boolean
      platformRoles?: string[]
      permissionCodes?: string[]
    }
    return {
      authenticated: true,
      username: typeof data.user?.username === "string" ? data.user.username : "",
      isSuper: Boolean(data.isSuper),
      platformRoles: Array.isArray(data.platformRoles)
        ? (data.platformRoles.filter((x): x is string => typeof x === "string") as string[])
        : [],
      permissionCodes: Array.isArray(data.permissionCodes)
        ? (data.permissionCodes.filter((x): x is string => typeof x === "string") as string[])
        : [],
    }
  } catch {
    return null
  }
}

export async function GET(request: NextRequest) {
  const cookieStore = await cookies()
  const token = cookieStore.get("dac_token")?.value

  if (!token) {
    return NextResponse.json(EMPTY_ME)
  }

  const me = await fetchMeFromBackend(request)
  if (me) {
    const payload = await readJwtPayload(token)
    if (payload?.username) {
      me.username = usernameFromPayload(payload)
    }
    return NextResponse.json(me)
  }

  // Fallback: the backend could not be reached or rejected the /users/me call.
  // Do NOT return a stale session with empty permissionCodes — that would wipe
  // the previously-fetched permissions and cause the sidebar menu to disappear.
  // Instead, signal a temporary unavailability so the client keeps its last
  // confirmed snapshot.
  const payload = await readJwtPayload(token)
  if (!payload || !isPayloadAcceptable(payload)) {
    return NextResponse.json(EMPTY_ME)
  }

  return NextResponse.json(
    { authenticated: false, username: "", isSuper: false, platformRoles: [], permissionCodes: [] },
    { status: 503 },
  )
}