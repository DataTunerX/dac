"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import Cookies from "js-cookie"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import { api } from "@/lib/api"
import { toast } from "sonner"
import { Loader2, GalleryVerticalEnd } from "lucide-react"

export default function LoginPage() {
  const router = useRouter()
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [loading, setLoading] = useState(false)

  const getNextPath = () => {
    const raw = typeof window !== "undefined" ? new URLSearchParams(window.location.search || "").get("next") || "" : ""
    // Prevent open redirect: only allow relative paths.
    if (!raw || !raw.startsWith("/")) return "/"
    if (raw.startsWith("//")) return "/"
    return raw
  }

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
        Cookies.set("dac_token", token, { expires: 7 })
        toast.success("登录成功")
        router.replace(getNextPath())
      } else {
        toast.error("登录失败：未获取到 token")
      }
    } catch (err: any) {
      console.error("Login failed", err)
      toast.error(err.response?.data?.message || "登录失败，请检查用户名或密码")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 p-6 md:p-10">
      <div className="w-full max-w-sm md:max-w-md">
        <Card className="rounded-xl shadow-lg py-6">
          <CardHeader className="flex flex-col items-center gap-2 text-center space-y-0 pb-6">
            <a href="#" className="flex flex-col items-center gap-2 font-medium">
              <div className="flex h-8 w-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
                <GalleryVerticalEnd className="size-5" />
              </div>
              <span className="sr-only">DAC</span>
            </a>
            <CardTitle className="text-2xl font-bold">欢迎回来</CardTitle>
            <CardDescription className="text-center text-sm text-slate-500">
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
                    type="text"
                    placeholder="请输入用户名"
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
                    type="password"
                    placeholder="请输入密码"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    disabled={loading}
                    required
                  />
                </div>
                
                <Button type="submit" className="w-full" disabled={loading}>
                  {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  登录
                </Button>
              </div>
            </form>

            <div className="mt-6 text-center text-sm text-slate-500">
              未注册账号？{" "}
              <a href="/register" className="underline underline-offset-4 hover:text-primary">
                去注册
              </a>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
