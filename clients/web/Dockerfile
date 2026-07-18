# syntax=docker/dockerfile:1
# Build context: clients/web/
# Static admin SPA for Cloud Run. Prefer empty VITE_ADMIN_API_URL so the
# browser uses same-origin /api (nginx proxies to admin-api with a SA token).

FROM oven/bun:1.3 AS build
WORKDIR /app
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile
COPY index.html ./
COPY public ./public
COPY src ./src
COPY tsconfig.json tsconfig.app.json tsconfig.node.json vite.config.ts ./
# Empty = same-origin /api (see api.ts). Cross-origin absolute URLs break under IAP.
ARG VITE_ADMIN_API_URL=
ENV VITE_ADMIN_API_URL=$VITE_ADMIN_API_URL
RUN bun run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/templates/default.conf.static
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh
COPY --from=build /app/dist /usr/share/nginx/html
ENV PORT=8080
ENV ADMIN_API_UPSTREAM=https://admin-api-dev-hsa55rg7ja-uk.a.run.app
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1
ENTRYPOINT ["/docker-entrypoint.sh"]
