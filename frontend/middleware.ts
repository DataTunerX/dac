import { NextResponse } from "next/server"
import type { NextRequest } from "next/server"
import { buildLoginRedirectUrl, isPublicPath, requiresAuth } from "@/lib/auth-redirect"

export function middleware(request: NextRequest) {
  const pathname = request.nextUrl.pathname

  if (isPublicPath(pathname) || !requiresAuth(pathname)) {
    return NextResponse.next()
  }

  const token = request.cookies.get("dac_token")?.value
  if (!token) {
    return NextResponse.redirect(buildLoginRedirectUrl(request.headers, request.nextUrl))
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
