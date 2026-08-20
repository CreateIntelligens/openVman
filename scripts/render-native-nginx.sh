#!/bin/sh
# Render the host nginx vhost from its template.
#
# The host's own nginx terminates public TLS and proxies into the Docker edge
# nginx; that vhost is not managed by compose, so it has to be rendered and
# installed once per machine.
#
#   PUBLIC_DOMAIN=example.com ./scripts/render-native-nginx.sh
#   sudo cp infra/nginx/native/openvman.conf /etc/nginx/conf.d/
#   sudo nginx -t && sudo systemctl reload nginx
#
# Pass an output path to render somewhere else, e.g. to diff against what is
# currently installed:
#   PUBLIC_DOMAIN=example.com ./scripts/render-native-nginx.sh /tmp/rendered.conf
set -eu

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE="$REPO_ROOT/infra/nginx/native/openvman.conf.template"
OUTPUT="${1:-$REPO_ROOT/infra/nginx/native/openvman.conf}"

if [ -z "${PUBLIC_DOMAIN:-}" ]; then
  echo "error: PUBLIC_DOMAIN is required (the public hostname on the certificate)" >&2
  exit 1
fi

# 憑證預設放在 repo 內，因為 certbot 跑在容器裡而不是主機套件；詳見
# infra/nginx/certs/README.md。
export PUBLIC_DOMAIN
export LETSENCRYPT_DIR="${LETSENCRYPT_DIR:-$REPO_ROOT/infra/nginx/certs/letsencrypt}"
export EDGE_UPSTREAM="${EDGE_UPSTREAM:-127.0.0.1:8787}"
export ACME_WEBROOT="${ACME_WEBROOT:-/usr/share/nginx/html}"

if ! command -v envsubst >/dev/null 2>&1; then
  echo "error: envsubst not found (install gettext-base)" >&2
  exit 1
fi

# 只展開這幾個變數，否則 nginx 自己的 $host / $request_uri 會被吃掉。
envsubst '${PUBLIC_DOMAIN} ${LETSENCRYPT_DIR} ${EDGE_UPSTREAM} ${ACME_WEBROOT}' \
  < "$TEMPLATE" > "$OUTPUT"

echo "rendered $OUTPUT"
echo "  PUBLIC_DOMAIN   = $PUBLIC_DOMAIN"
echo "  LETSENCRYPT_DIR = $LETSENCRYPT_DIR"
echo "  EDGE_UPSTREAM   = $EDGE_UPSTREAM"
echo "  ACME_WEBROOT    = $ACME_WEBROOT"
