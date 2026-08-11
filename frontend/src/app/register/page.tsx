"use client"

import { useState } from "react"
import Link from "next/link"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import axios from "axios"
import { api } from "@/lib/api"
import { establishSession, navigateAfterAuth } from "@/lib/auth-session"
import { toast } from "sonner"
import { Loader2, GalleryVerticalEnd } from "lucide-react"

export default function RegisterPage() {
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [loading, setLoading] = useState(false)

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!username || !password || !confirmPassword) {
      toast.error("请填写所有字段")
      return
    }
    if (password !== confirmPassword) {
      toast.error("两次输入的密码不一致")
      return
    }

    setLoading(true)
    try {
      // Register returns user info (no token). Login sets HttpOnly dac_token via Set-Cookie.
      await api.post("/auth/register", { username, password })
      const loginRes = await api.post("/auth/login", { username, password })
      const user = loginRes.data?.user
      if (!user) {
        toast.success("注册成功，请登录")
        navigateAfterAuth("/login")
        return
      }
      establishSession(user)
      toast.success("注册成功")
      navigateAfterAuth("/")
    } catch (err: unknown) {
      console.error("Register failed", err)
      const message =
        axios.isAxiosError(err) && err.response?.data && typeof err.response.data === "object" && "message" in err.response.data
          ? String((err.response.data as { message?: unknown }).message)
          : "注册失败，请稍后重试"
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
            <CardTitle className="text-2xl font-bold">创建新账号</CardTitle>
            <CardDescription className="text-center text-sm text-content-muted">
              注册 DAC 智能体管理平台
            </CardDescription>
          </CardHeader>
          
          <CardContent>
            <form onSubmit={handleRegister}>
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
                    autoComplete="new-password"
                    placeholder="请输入密码…"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    disabled={loading}
                    required
                  />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="confirmPassword">确认密码</Label>
                  <Input
                    id="confirmPassword"
                    name="confirmPassword"
                    type="password"
                    autoComplete="new-password"
                    placeholder="请再次输入密码…"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    disabled={loading}
                    required
                  />
                </div>
                
                <Button type="submit" className="w-full" disabled={loading}>
                  {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                  注册
                </Button>
              </div>
            </form>

            <div className="mt-6 text-center text-sm text-content-muted">
              已有账号？{" "}
              <Link href="/login" className="underline underline-offset-4 hover:text-primary">
                去登录
              </Link>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
