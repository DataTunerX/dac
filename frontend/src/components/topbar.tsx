"use client"

import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Button } from "@/components/ui/button"
import { logout, navigateAfterAuth } from "@/lib/auth-session"
import { useAuthHydrated, useAuthUsername } from "@/lib/use-user-role"
import { initialFromUsername } from "@/lib/utils"
import { TenantSwitcher } from "@/components/tenant-switcher"

export function Topbar() {
  const hydrated = useAuthHydrated()
  const username = useAuthUsername()
  const displayName = username === "admin" ? "管理员" : username
  const initial = initialFromUsername(username)

  const handleLogout = () => {
    void logout().finally(() => {
      navigateAfterAuth("/login")
    })
  }

  return (
    <header className="h-14 shrink-0 bg-[#0f172a] border-b border-white/5">
      <div className="h-full flex items-center w-full">
        <div className="hidden lg:flex w-64 h-full items-center px-6 gap-3">
          <div className="w-7 h-7 rounded-lg flex items-center justify-center text-white text-sm font-bold bg-[#4f46e5] shadow-sm" aria-hidden="true">
            D
          </div>
          <span className="text-content-inverse font-bold text-base tracking-wide">DAC Platform</span>
        </div>

        <div className="flex-1 flex items-center justify-end px-4 lg:px-6">
          {hydrated ? (
            <>
              <TenantSwitcher className="mr-2 text-content-inverse" />
              <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="rounded-full hover:bg-surface/10 text-content-inverse min-w-[44px] min-h-[44px] w-10 h-10 touch-manipulation"
                  aria-label="账户菜单"
                >
                  <span className="relative flex shrink-0 overflow-hidden rounded-full h-8 w-8">
                    <span className="flex size-full items-center justify-center rounded-full bg-surface/10 text-content-inverse">
                      {initial}
                    </span>
                  </span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                <DropdownMenuLabel>账户: {displayName}</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  className="text-red-600 focus:text-red-700"
                  onSelect={handleLogout}
                >
                  退出登录
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            </>
          ) : (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="rounded-full hover:bg-surface/10 text-content-inverse min-w-[44px] min-h-[44px] w-10 h-10 touch-manipulation"
              aria-label="账户"
            >
              <span className="relative flex shrink-0 overflow-hidden rounded-full h-8 w-8">
                <span className="flex size-full items-center justify-center rounded-full bg-surface/10 text-content-inverse">
                  {initial || "U"}
                </span>
              </span>
            </Button>
          )}
        </div>
      </div>
    </header>
  )
}
