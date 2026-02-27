"use client"

import { useEffect, useState } from "react"
import Cookies from "js-cookie"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import { decodeJwtPayload, initialFromUsername } from "@/lib/utils"

export function Topbar() {
  const [mounted, setMounted] = useState(false)
  const [userInfo, setUserInfo] = useState({ username: "", initial: "U" })

  useEffect(() => {
    setMounted(true)
    const token = Cookies.get("dac_token") || ""
    const payload = token ? decodeJwtPayload(token) : null
    const username = typeof payload?.username === "string" ? payload.username : ""
    setUserInfo({ username, initial: initialFromUsername(username) })
  }, [])

  const { username, initial } = userInfo

  const handleLogout = () => {
    Cookies.remove("dac_token")
    window.location.href = "/login"
  }

  return (
    <header className="h-14 bg-[#2f3136] shrink-0">
      <div className="h-full flex items-center w-full">
        <div className="w-64 h-full flex items-center px-6 gap-2">
          <div className="w-6 h-6 bg-blue-600 rounded flex items-center justify-center text-white text-xs font-bold">
            D
          </div>
          <span className="text-white font-bold text-lg">DAC</span>
        </div>

        <div className="flex-1 flex items-center justify-end px-6">
          {mounted ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  id="radix-_r_0_"
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="rounded-full hover:bg-white/10 text-white"
                >
                  <span className="relative flex shrink-0 overflow-hidden rounded-full h-8 w-8">
                    <span className="flex size-full items-center justify-center rounded-full bg-white/10 text-white">
                      {initial}
                    </span>
                  </span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                <DropdownMenuLabel>账户: {username}</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  className="text-red-600 focus:text-red-700"
                  onSelect={handleLogout}
                >
                  退出登录
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="rounded-full hover:bg-white/10 text-white"
            >
              <span className="relative flex shrink-0 overflow-hidden rounded-full h-8 w-8">
                <span className="flex size-full items-center justify-center rounded-full bg-white/10 text-white">
                  {initial}
                </span>
              </span>
            </Button>
          )}
        </div>
      </div>
    </header>
  )
}
