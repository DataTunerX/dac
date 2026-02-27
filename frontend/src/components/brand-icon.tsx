"use client"

import type { ComponentProps } from "react"
import {
  siAlibabacloud,
  siAnthropic,
  siGit,
  siGitea,
  siGitee,
  siGithub,
  siGoogle,
  siMinio,
  siMysql,
  siNginx,
  siOpenai,
  siOpenssl,
  siPostgresql,
  siRedis,
} from "simple-icons/icons"

type SimpleIcon = {
  title: string
  hex: string
  path: string
}

export type BrandSlug =
  | "mysql"
  | "postgresql"
  | "minio"
  | "git"
  | "github"
  | "gitea"
  | "gitee"
  | "redis"
  | "nginx"
  | "openssh"
  | "openai"
  | "anthropic"
  | "google"
  | "alibabacloud"

const ICONS: Record<BrandSlug, SimpleIcon> = {
  mysql: siMysql,
  postgresql: siPostgresql,
  minio: siMinio,
  git: siGit,
  github: siGithub,
  gitea: siGitea,
  gitee: siGitee,
  redis: siRedis,
  nginx: siNginx,
  // simple-icons doesn't ship OpenSSH in this version; use OpenSSL as a close substitute.
  openssh: siOpenssl,
  openai: siOpenai,
  anthropic: siAnthropic,
  google: siGoogle,
  alibabacloud: siAlibabacloud,
}

export function BrandIcon({
  slug,
  size = 16,
  color,
  title,
  className,
  ...rest
}: {
  slug: BrandSlug
  size?: number
  color?: string
  title?: string
  className?: string
} & Omit<ComponentProps<"svg">, "color">) {
  const icon = ICONS[slug]
  const fill = color || `#${icon.hex}`
  const label = title || icon.title
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      aria-label={label}
      role="img"
      className={className}
      {...rest}
    >
      <title>{label}</title>
      <path d={icon.path} fill={fill} />
    </svg>
  )
}

