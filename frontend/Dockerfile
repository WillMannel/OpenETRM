# Production image: static assets built by Vite, served by nginx as a non-root
# user. NOT used by docker-compose.yml (that's local-dev/demo -- see Dockerfile.dev
# for the hot-reloading dev-server image); this is what a real deployment builds
# and ships.
#
# VITE_API_BASE_URL is a *build-time* value -- Vite inlines import.meta.env.* into
# the compiled JS, there's no reading it from the container's environment at
# runtime (see src/api/client.ts). Build with:
#   docker build --build-arg VITE_API_BASE_URL=https://api.example.com -t openetrm-web ./frontend
# A different backend URL per environment means a separate image build per
# environment; see FUTURE_WORK.md for the runtime-config-injection alternative
# (an entrypoint script writing a small config.js from env vars) that would let one
# image serve every environment.
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

# nginx-unprivileged: runs as the non-root `nginx` user (UID 101) and listens on
# 8080 by default (binding <1024 needs root) -- no manual user/permission setup
# needed, unlike stock nginx:alpine.
FROM nginxinc/nginx-unprivileged:1.27-alpine
# Whatever Alpine package versions this tag happened to bundle at its own build
# time go stale the moment new CVEs land -- caught by this image's own Trivy scan
# in CI: 33 CRITICAL/HIGH OS-package CVEs (openssl, libxml2, libpng, libexpat,
# c-ares, musl, nghttp2, zlib), every one with a fix already published upstream.
# `apk upgrade` at build time (not just a fresher base tag, which would just go
# stale again) means every image build picks up whatever's currently patched,
# not whatever was current when this tag was last pushed. Needs root -- the base
# image already switched to the non-root nginx user (UID 101) in its own
# Dockerfile, so switch back before apk and forward again after.
USER root
RUN apk update && apk upgrade --no-cache
USER 101
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://localhost:8080/ || exit 1
