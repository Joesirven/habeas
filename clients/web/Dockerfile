# syntax=docker/dockerfile:1
# Build context: clients/web/
# Static admin SPA for Cloud Run. Cloud Build bakes Architecture B via
# --build-arg (see infra/cloudbuild/admin-web-*.yaml):
#   VITE_ADMIN_API_URL     admin-api origin (empty = same-origin /api rollback)
#   VITE_GOOGLE_CLIENT_ID  public GIS / IAP OAuth client (required when URL is set)
# nginx /api stays at runtime for SSE (EventSource) — see docker-entrypoint.sh.

FROM oven/bun:1.3 AS build
WORKDIR /app
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile
COPY index.html ./
COPY public ./public
COPY src ./src
COPY tsconfig.json tsconfig.app.json tsconfig.node.json vite.config.ts ./
# Empty = same-origin /api (see api.ts). Absolute URL = Architecture B (direct admin-api).
ARG VITE_ADMIN_API_URL=
ENV VITE_ADMIN_API_URL=$VITE_ADMIN_API_URL
# Public GIS / IAP OAuth client. Required when VITE_ADMIN_API_URL is set.
ARG VITE_GOOGLE_CLIENT_ID=
ENV VITE_GOOGLE_CLIENT_ID=$VITE_GOOGLE_CLIENT_ID

# Labs are DEV-only. Default off so unlabeled / prod builds never bake /dev/*.
ARG VITE_ENABLE_LABS=
ENV VITE_ENABLE_LABS=$VITE_ENABLE_LABS
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
