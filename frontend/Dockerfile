# Build context is frontend/ itself (see docker-compose.yml) -- self-contained,
# no need to pull in the Python backend's files.
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
# `npm ci` (not used here) is strict about the lockfile listing every
# platform-specific optional dependency -- a lockfile generated on Windows
# is missing the Linux/musl variants needed inside this Alpine image (caught
# building this exact image). `npm install` resolves them correctly instead.
RUN npm install

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# BACKEND_URL/APP_PASSWORD are read at REQUEST time (Route Handlers/
# middleware), not baked in at build time -- no build-time env needed here.
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

EXPOSE 3000
CMD ["node", "server.js"]
