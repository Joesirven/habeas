#!/bin/sh
# IAP authenticates the browser to this host. Same-origin /api/* is proxied to
# admin-api with a runtime SA identity token (invisible to the browser).
# Forward only IAP identity headers — never mint/refresh tokens in the browser.
set -eu

API_URL="${ADMIN_API_UPSTREAM:-https://admin-api-dev-hsa55rg7ja-uk.a.run.app}"
API_HOST="${API_URL#https://}"
API_HOST="${API_HOST#http://}"
API_HOST="${API_HOST%%/*}"
CONF=/etc/nginx/conf.d/default.conf
TOKEN_FILE=/tmp/cloud-run-id-token

fetch_token() {
  # curl --data-urlencode handles audience encoding (busybox wget does not).
  if ! curl -sS --fail -o "$TOKEN_FILE" \
    -H "Metadata-Flavor: Google" \
    -G "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity" \
    --data-urlencode "audience=${API_URL}"
  then
    echo "entrypoint: metadata identity fetch failed audience=${API_URL}" >&2
    return 1
  fi
  token=$(tr -d '\n\r\t ' <"$TOKEN_FILE")
  dots=$(printf '%s' "$token" | awk -F. '{print NF-1}')
  if [ "$dots" -ne 2 ] || [ "${#token}" -lt 100 ]; then
    echo "entrypoint: metadata identity response is not a JWT (len=${#token})" >&2
    return 1
  fi
  printf '%s' "$token" >"$TOKEN_FILE"
  # Log aud/exp for Cloud Logging (no signature).
  echo "$token" | awk -F. '{print $2}' | {
    read -r payload || true
    # base64url → base64 + pad
    pad=$(( (4 - ${#payload} % 4) % 4 ))
    i=0
    while [ "$i" -lt "$pad" ]; do payload="${payload}="; i=$((i + 1)); done
    payload=$(printf '%s' "$payload" | tr '_-' '/+')
    claims=$(printf '%s' "$payload" | base64 -d 2>/dev/null || true)
    echo "entrypoint: minted identity token len=${#token} claims=${claims}" >&2
  }
}

write_nginx_conf() {
  token=$(cat "$TOKEN_FILE")
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
  echo "entrypoint: falling back to static nginx (no /api upstream auth)" >&2
  cp /etc/nginx/templates/default.conf.static "$CONF" 2>/dev/null || true
fi

exec nginx -g "daemon off;"
