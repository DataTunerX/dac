import type { NextConfig } from "next"

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: "standalone",
  experimental: {
    optimizePackageImports: ["lucide-react"],
  },
  async rewrites() {
    // Production (Docker): nginx proxies `/api/v1/*` and `/v1/*` before traffic hits Next.js,
    // so these rewrites are inactive in the container. They apply for `next dev` / local runs
    // without nginx.
    // Proxy frontend -> backend, so browser always calls same-origin `/api/v1/*`.
    // Configure in `.env.local`:
    //   BACKEND_URL=http://10.17.0.41:31580
    const backendUrl = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || ""
    console.log(`[Next.js Rewrite] Configuring proxy to backend: ${backendUrl || 'NOT SET'}`)
    
    const backend = backendUrl.replace(/\/+$/, "")
    if (!backend) return []
    return [
      {
        source: "/api/v1/:path*",
        destination: `${backend}/api/v1/:path*`,
      },
      // OpenAI-compatible endpoints are mounted at `/v1/*` in dac-apiserver.
      // We proxy them too, otherwise `/v1/*` will hit Next.js and return 404.
      {
        source: "/v1/:path*",
        destination: `${backend}/v1/:path*`,
      },
    ]
  },
}

export default nextConfig

