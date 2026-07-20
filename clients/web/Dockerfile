# syntax=docker/dockerfile:1
# Build context: clients/web/
# Static admin SPA for Cloud Run (admin-web-dev) and local nginx.

FROM oven/bun:1.3 AS build
WORKDIR /app
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile
COPY index.html ./
COPY public ./public
COPY src ./src
COPY tsconfig.json tsconfig.app.json tsconfig.node.json vite.config.ts ./
ARG VITE_ADMIN_API_URL=https://admin-api-dev-hsa55rg7ja-uk.a.run.app
ENV VITE_ADMIN_API_URL=$VITE_ADMIN_API_URL
RUN bun run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
ENV PORT=8080
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
