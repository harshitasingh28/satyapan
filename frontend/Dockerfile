# syntax=docker/dockerfile:1
# Satyapan frontend: Next.js standalone server for Cloud Run.
# Build:  docker build --build-arg NEXT_PUBLIC_API_BASE_URL=https://api.example.run.app -t satyapan-frontend .
# The API URL is public and is inlined into the browser bundle at build time.

FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json .npmrc ./
RUN npm ci --no-audit --no-fund

FROM node:22-alpine AS build
WORKDIR /app
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL} \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build && npm run check-bundle

FROM node:22-alpine AS run
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=8080 \
    HOSTNAME=0.0.0.0
RUN addgroup -S -g 1001 satyapan && adduser -S -u 1001 -G satyapan satyapan
COPY --from=build --chown=satyapan:satyapan /app/.next/standalone ./
COPY --from=build --chown=satyapan:satyapan /app/.next/static ./.next/static
USER satyapan
EXPOSE 8080
# server.js reads PORT (Cloud Run sets it) and HOSTNAME.
CMD ["node", "server.js"]
