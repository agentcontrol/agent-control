# Dockerfile for Agent Control UI
#
# Build from repository root:
#   docker build -t agent-control-ui -f ui/Dockerfile ui
#
# Run:
#   docker run -p 4000:4000 agent-control-ui

FROM node:20-alpine AS base

WORKDIR /app

ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH

RUN corepack enable && corepack prepare pnpm@9 --activate

FROM base AS deps

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

FROM base AS builder

# Next.js NEXT_PUBLIC_* values are bundled at build time.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG NEXT_PUBLIC_AGENT_CONTROL_API_KEY=
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_AGENT_CONTROL_API_KEY=$NEXT_PUBLIC_AGENT_CONTROL_API_KEY
ENV NEXT_TELEMETRY_DISABLED=1

COPY --from=deps /app/node_modules ./node_modules
COPY . .

RUN pnpm build && pnpm prune --prod

FROM base AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=4000

COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules

EXPOSE 4000

CMD ["pnpm", "start", "-p", "4000"]
