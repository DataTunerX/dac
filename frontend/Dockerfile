FROM node:20-alpine AS base

# Install dependencies only when needed
FROM base AS deps
# Check https://github.com/nodejs/docker-node/tree/b4117f9333da4138b03a546ec926ef50a31506c3#nodealpine to understand why libc6-compat might be needed.
RUN apk add --no-cache libc6-compat
WORKDIR /app

# Install dependencies based on the preferred package manager
COPY package.json ./
# No lockfile present, so we use npm install to generate one and install
# RUN npm config set registry https://registry.npmmirror.com/
RUN npm install

# Rebuild the source code only when needed
FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Next.js collects completely anonymous telemetry data about general usage.
# Learn more here: https://nextjs.org/telemetry
# Uncomment the following line in case you want to disable telemetry during the build.
# ENV NEXT_TELEMETRY_DISABLED 1

RUN npm run build

# Production image, copy all the files and run next
FROM base AS runner
WORKDIR /app

ENV NODE_ENV=production
# Uncomment the following line in case you want to disable telemetry during runtime.
# ENV NEXT_TELEMETRY_DISABLED 1

RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs

# Nginx reverse proxy (runtime-configurable via BACKEND_URL).
# NOTE: `/v1/*` and `/api/v1/*` are proxied by nginx (see `nginx/default.conf.template`),
# so the browser can call same-origin endpoints.
USER root
RUN apk add --no-cache nginx gettext dumb-init
COPY ./nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY ./nginx/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh \
  && mkdir -p /etc/nginx/templates /etc/nginx/http.d /etc/nginx/conf.d \
  && mkdir -p /var/lib/nginx /var/log/nginx \
  && chown -R nextjs:nodejs /etc/nginx/templates /etc/nginx/http.d /etc/nginx/conf.d /var/lib/nginx /var/log/nginx

# Set the correct permission for prerender cache
RUN mkdir .next
RUN chown nextjs:nodejs .next

# Automatically leverage output traces to reduce image size
# https://nextjs.org/docs/advanced-features/output-file-tracing
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

ENV PORT=3000
# set hostname to localhost
ENV HOSTNAME="0.0.0.0"

CMD ["dumb-init", "/entrypoint.sh"]
