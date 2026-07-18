#!/bin/sh
# Refresh a Cloud Run identity token and rewrite nginx upstream auth.
# Browser calls same-origin /api/*; nginx proxies to admin-api with the SA token.
set -eu

API_URL="${ADMIN_API_UPSTREAM:-https://admin-api-dev-hsa55rg7ja-uk.a.run.app}"
API_HOST="${API_URL#https://}"
API_HOST="${API_HOST#http://}"
API_HOST="${API_HOST%%/*}"
CONF=/etc/nginx/conf.d/default.conf
TOKEN_FILE=/tmp/cloud-run-id-token

fetch_token() {
  wget -qO"$TOKEN_FILE" \
    --header="Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity?audience=${API_URL}" \
    || return 1
}

write_nginx_conf() {
  token=$(cat "$TOKEN_FILE")
  cat >"$CONF" <<EOF
server {
    listen 8080;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    gzip on;
    gzip_types text/css application/javascript application/json text/plain;

    location = /healthz {
        access_log off;
        default_type text/plain;
        return 200 "ok\\n";
    }

    # Same-origin API front door — IAP authenticates the browser to this host.
    # Forward IAP identity headers so admin-api can resolve roles.
    location /api/ {
        proxy_pass https://${API_HOST}/;
        proxy_http_version 1.1;
        proxy_ssl_server_name on;
        proxy_set_header Host ${API_HOST};
        proxy_set_header Authorization "Bearer ${token}";
        proxy_set_header X-Goog-Authenticated-User-Email \$http_x_goog_authenticated_user_email;
        proxy_set_header X-Goog-Authenticated-User-Id \$http_x_goog_authenticated_user_id;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 3600s;
    }

    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, max-age=31536000, immutable";
    }

    location / {
        try_files \$uri \$uri/ /index.html;
    }
}
EOF
}

refresh_loop() {
  while true; do
    sleep 2700
    if fetch_token; then
      write_nginx_conf
      nginx -s reload || true
    fi
  done
}

if fetch_token; then
  write_nginx_conf
  refresh_loop &
else
  # Local docker / missing metadata: serve SPA only (no /api proxy auth).
  cp /etc/nginx/templates/default.conf.static "$CONF" 2>/dev/null || true
fi

exec nginx -g "daemon off;"
