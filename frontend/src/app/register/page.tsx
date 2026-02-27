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

export default function RegisterPage() {
  const router = useRouter()
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
      // Register returns user info (no token). After registering, login once to obtain JWT.
      await api.post("/auth/register", { username, password })
      const loginRes = await api.post("/auth/login", { username, password })
      const token = loginRes.data?.token || loginRes.data?.access_token
      if (!token) {
        toast.success("注册成功，请登录")
        router.replace("/login")
        return
      }
      Cookies.set("dac_token", token, { expires: 7 })
      toast.success("注册成功")
      router.replace("/")
    } catch (err: any) {
      console.error("Register failed", err)
      toast.error(err.response?.data?.message || "注册失败，请稍后重试")
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
            <CardTitle className="text-2xl font-bold">创建新账号</CardTitle>
            <CardDescription className="text-center text-sm text-slate-500">
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
                <div className="grid gap-2">
                  <Label htmlFor="confirmPassword">确认密码</Label>
                  <Input
                    id="confirmPassword"
                    type="password"
                    placeholder="请再次输入密码"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    disabled={loading}
                    required
                  />
                </div>
                
                <Button type="submit" className="w-full" disabled={loading}>
                  {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  注册
                </Button>
              </div>
            </form>

            <div className="mt-6 text-center text-sm text-slate-500">
              已有账号？{" "}
              <a href="/login" className="underline underline-offset-4 hover:text-primary">
                去登录
              </a>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
