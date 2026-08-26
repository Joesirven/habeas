#!/bin/sh
# Architecture B dual-run (rollback + SSE):
# - Browser JSON may call admin-api directly when VITE_ADMIN_API_URL is baked
#   to the real admin-api origin. That build arg is not used here.
# - Same-origin /api/* stays proxied to ADMIN_API_UPSTREAM so EventSource
#   (GET /api/live/events) still works, and so empty-VITE rollback images
#   keep using /api for all REST.
# IAP authenticates the human to this host. nginx mints a runtime SA identity
# token (invisible to the browser) and forwards IAP identity headers.
# Do not drop IAP header forwarding until the nginx session path is retired.
# Token failure must not crash the container: serve the SPA without /api.
set -eu

# Runtime proxy target only. Independent of baked VITE_ADMIN_API_URL.
API_URL="${ADMIN_API_UPSTREAM:-https://admin-api-dev-hsa55rg7ja-uk.a.run.app}"
API_HOST="${API_URL#https://}"
API_HOST="${API_HOST#http://}"
API_HOST="${API_HOST%%/*}"
CONF=/etc/nginx/conf.d/default.conf
TOKEN_FILE=/tmp/cloud-run-id-token

fetch_token() {
  # Write to a temp file so a failed fetch cannot clobber a last-known JWT.
  tmp="${TOKEN_FILE}.tmp"
  # curl --data-urlencode handles audience encoding (busybox wget does not).
  if ! curl -sS --fail -o "$tmp" \
    -H "Metadata-Flavor: Google" \
    -G "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity" \
    --data-urlencode "audience=${API_URL}"
  then
    echo "entrypoint: metadata identity fetch failed audience=${API_URL}" >&2
    rm -f "$tmp"
    return 1
  fi
  token=$(tr -d '\n\r\t ' <"$tmp" || true)
  rm -f "$tmp"
  dots=$(printf '%s' "$token" | awk -F. '{print NF-1}')
  if [ "$dots" -ne 2 ] || [ "${#token}" -lt 100 ]; then
    echo "entrypoint: metadata identity response is not a JWT (len=${#token})" >&2
    return 1
  fi
  printf '%s' "$token" >"$TOKEN_FILE"
  # Length only — decoded claims include email/sub (no PII in logs).
  echo "entrypoint: minted identity token len=${#token}" >&2
}

write_nginx_conf() {
  token=""
  if [ -s "$TOKEN_FILE" ]; then
    token=$(tr -d '\n\r\t ' <"$TOKEN_FILE" || true)
  fi

  if [ -n "$token" ]; then
    # proxy_pass_request_headers off: do not forward browser cookies / stray
    # Authorization (those produce Cloud Run "access token could not be verified").
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

    location /api/ {
        proxy_pass https://${API_HOST}/;
        proxy_http_version 1.1;
        proxy_ssl_server_name on;
        # Drop browser cookies / stray Authorization (Cloud Run rejects those),
        # but keep Content-Type so JSON mutation bodies validate (else HTTP 422).
        proxy_pass_request_headers off;
        proxy_set_header Host ${API_HOST};
        proxy_set_header Connection "";
        proxy_set_header Content-Type \$http_content_type;
        proxy_set_header Content-Length \$http_content_length;
        proxy_set_header Accept \$http_accept;
        proxy_set_header Authorization "Bearer ${token}";
        # Keep IAP identity forwarding for /api rollback + SSE (Architecture B
        # JSON may skip this hop; do not remove until the nginx session is retired).
        proxy_set_header X-Goog-Authenticated-User-Email \$http_x_goog_authenticated_user_email;
        proxy_set_header X-Goog-Authenticated-User-Id \$http_x_goog_authenticated_user_id;
        # Super-admin "View as" — browser sets this; Vite local proxy passes it through,
        # but proxy_pass_request_headers off would otherwise drop it here.
        proxy_set_header X-Dev-Simulate-Role \$http_x_dev_simulate_role;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
    }

    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, max-age=31536000, immutable";
    }

    location / {
        add_header Cache-Control "no-store";
        try_files \$uri \$uri/ /index.html;
    }
}
EOF
  else
    echo "entrypoint: writing static-only nginx conf (no /api proxy)" >&2
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

    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, max-age=31536000, immutable";
    }

    location / {
        add_header Cache-Control "no-store";
        try_files \$uri \$uri/ /index.html;
    }
}
EOF
  fi
}

fetch_token_with_retry() {
  attempt=1
  max_attempts=30
  while [ "$attempt" -le "$max_attempts" ]; do
    if fetch_token; then
      return 0
    fi
    echo "entrypoint: identity fetch attempt ${attempt}/${max_attempts} failed" >&2
    if [ "$attempt" -eq "$max_attempts" ]; then
      return 1
    fi
    sleep 2
    attempt=$((attempt + 1))
  done
  return 1
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

if ! fetch_token_with_retry; then
  if [ -s "$TOKEN_FILE" ]; then
    echo "entrypoint: identity fetch failed after 30 attempts; keeping last-known token for /api proxy" >&2
  else
    echo "entrypoint: could not obtain identity token after 30 attempts; serving static SPA without /api proxy" >&2
  fi
fi

write_nginx_conf
refresh_loop &

exec nginx -g "daemon off;"
