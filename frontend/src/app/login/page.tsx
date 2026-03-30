"use client"

import { useState } from "react"
import Link from "next/link"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import axios from "axios"
import { api } from "@/lib/api"
import { getSafeNextPath, navigateAfterAuth, persistAuthToken } from "@/lib/auth-session"
import { toast } from "sonner"
import { Loader2, GalleryVerticalEnd } from "lucide-react"

export default function LoginPage() {
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [loading, setLoading] = useState(false)

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!username || !password) {
      toast.error("请输入用户名和密码")
      return
    }

    setLoading(true)
    try {
      const res = await api.post("/auth/login", { username, password })
      const token = res.data?.token || res.data?.access_token
      if (token) {
        persistAuthToken(token)
        toast.success("登录成功")
        navigateAfterAuth(getSafeNextPath(window.location.search || ""))
      } else {
        toast.error("登录失败：未获取到 token")
      }
    } catch (err: unknown) {
      console.error("Login failed", err)
      const message =
        axios.isAxiosError(err) && err.response?.data && typeof err.response.data === "object" && "message" in err.response.data
          ? String((err.response.data as { message?: unknown }).message)
          : "登录失败，请检查用户名或密码"
      toast.error(message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-muted p-6 md:p-10">
      <div className="w-full max-w-sm md:max-w-md">
        <Card className="rounded-xl shadow-lg py-6">
          <CardHeader className="flex flex-col items-center gap-2 text-center space-y-0 pb-6">
            <Link href="/" className="flex flex-col items-center gap-2 font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2 rounded-md" aria-label="DAC 首页">
              <div className="flex h-8 w-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
                <GalleryVerticalEnd className="size-5" aria-hidden />
              </div>
            </Link>
            <CardTitle className="text-2xl font-bold">欢迎回来</CardTitle>
            <CardDescription className="text-center text-sm text-content-muted">
              登录 DAC 智能体管理平台
            </CardDescription>
          </CardHeader>
          
          <CardContent>
            <form onSubmit={handleLogin}>
              <div className="grid gap-6">
                <div className="grid gap-2">
                  <Label htmlFor="username">用户名</Label>
                  <Input
                    id="username"
                    name="username"
                    type="text"
                    autoComplete="username"
                    placeholder="请输入用户名…"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    disabled={loading}
                    required
                  />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="password">密码</Label>
                  <Input
                    id="password"
                    name="password"
                    type="password"
                    autoComplete="current-password"
                    placeholder="请输入密码…"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    disabled={loading}
                    required
                  />
                </div>
                
                <Button type="submit" className="w-full" disabled={loading}>
                  {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                  登录
                </Button>
              </div>
            </form>

            <div className="mt-6 text-center text-sm text-content-muted">
              未注册账号？{" "}
              <Link href="/register" className="underline underline-offset-4 hover:text-primary">
                去注册
              </Link>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
