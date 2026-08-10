import { NextResponse } from "next/server"
import type { NextRequest } from "next/server"
import { buildLoginRedirectUrl, isPublicPath, requiresAuth } from "@/lib/auth-redirect"
import {
  isPayloadAcceptable,
  readJwtPayload,
} from "@/lib/jwt-edge"

export async function middleware(request: NextRequest) {
  const pathname = request.nextUrl.pathname

  if (isPublicPath(pathname) || !requiresAuth(pathname)) {
    return NextResponse.next()
  }

  const token = request.cookies.get("dac_token")?.value
  const payload = token ? await readJwtPayload(token) : null

  if (!payload || !isPayloadAcceptable(payload)) {
    const res = NextResponse.redirect(buildLoginRedirectUrl(request.headers, request.nextUrl))
    if (token) {
      // Clear unusable cookie so the client does not loop on stale JWT
      res.cookies.set("dac_token", "", { path: "/", maxAge: 0 })
    }
    return res
  }

  return NextResponse.next()
}

export const config = {
  matcher: [
    /*
     * Match all pathnames except:
     * - _next/static (static files)
     * - _next/image (image optimization)
     * - favicon.ico
     */
    "/((?!_next/static|_next/image|favicon.ico).*)",
  ],
}
