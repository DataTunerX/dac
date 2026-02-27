import "./globals.css"

import type { Metadata } from "next"
import { Toaster } from "sonner"

export const metadata: Metadata = {
  title: "DAC",
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen">
        {children}
        <Toaster />
      </body>
    </html>
  )
}

