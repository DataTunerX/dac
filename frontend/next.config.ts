import type { NextConfig } from "next"

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: "standalone",
  experimental: {
    optimizePackageImports: [
      "lucide-react",
      "date-fns",
      "@radix-ui/react-accordion",
      "@radix-ui/react-dialog",
      "@radix-ui/react-dropdown-menu",
      "@radix-ui/react-label",
      "@radix-ui/react-select",
      "@radix-ui/react-slot",
    ],
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=()",
          },
          // CSP: allow same-origin + inline styles (Tailwind/runtime); block framing & unexpected scripts
          {
            key: "Content-Security-Policy",
            value: [
              "default-src 'self'",
              // Next/dev + some chart libs still need eval; tighten when bundles allow
              "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
              "style-src 'self' 'unsafe-inline'",
              "img-src 'self' data: blob:",
              "font-src 'self' data:",
              "connect-src 'self'",
              // Mermaid (and similar) may spawn blob workers
              "worker-src 'self' blob:",
              "child-src 'self' blob:",
              "frame-ancestors 'none'",
              "base-uri 'self'",
              "form-action 'self'",
            ].join("; "),
          },
        ],
      },
    ]
  },
  async rewrites() {
    // Production (Docker): nginx proxies `/api/v1/*` and `/v1/*` before traffic hits Next.js,
    // so these rewrites are inactive in the container. They apply for `next dev` / local runs
    // without nginx.
    // Proxy frontend -> backend, so browser always calls same-origin `/api/v1/*`.
    // Configure in `.env.local`:
    //   BACKEND_URL=http://10.17.0.41:31580
    const backendUrl = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || ""
    console.log(`[Next.js Rewrite] Configuring proxy to backend: ${backendUrl || "NOT SET"}`)

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
