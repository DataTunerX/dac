import "./globals.css"

import type { Metadata } from "next"
import { Fira_Code, Fira_Sans } from "next/font/google"
import { Toaster } from "sonner"

const firaCode = Fira_Code({
  subsets: ["latin"],
  variable: "--font-fira-code",
  display: "swap",
})
const firaSans = Fira_Sans({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  variable: "--font-fira-sans",
  display: "swap",
})

export const metadata: Metadata = {
  title: "DAC",
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" suppressHydrationWarning className={`${firaCode.variable} ${firaSans.variable}`}>
      <body className="min-h-screen font-sans antialiased">
        {children}
        <Toaster />
      </body>
    </html>
  )
}

