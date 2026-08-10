import { cookies } from "next/headers"
import { NextResponse } from "next/server"
import {
  isPayloadAcceptable,
  readJwtPayload,
  roleFromPayload,
  usernameFromPayload,
} from "@/lib/jwt-edge"

export async function GET() {
  const cookieStore = await cookies()
  const token = cookieStore.get("dac_token")?.value

  if (!token) {
    return NextResponse.json({
      authenticated: false,
      role: "",
      username: "",
    })
  }

  const payload = await readJwtPayload(token)
  if (!payload || !isPayloadAcceptable(payload)) {
    return NextResponse.json({
      authenticated: false,
      role: "",
      username: "",
    })
  }

  return NextResponse.json({
    authenticated: true,
    role: roleFromPayload(payload),
    username: usernameFromPayload(payload),
  })
}
