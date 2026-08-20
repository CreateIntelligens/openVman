#!/bin/sh
# Renew the native nginx TLS certificate via a pinned certbot container.
#
# certbot is not installed on the host; it runs in Docker with the repo's
# cert directory bind-mounted at the standard /etc/letsencrypt path, so the
# renewal config inside it stays portable. The host nginx reads the same
# files through their real path, which is why REPO_ROOT must resolve to the
# checkout that nginx's ssl_certificate lines point at.
#
# Scheduled from cron, e.g.
#   17 4 * * * /path/to/repo/scripts/renew-letsencrypt.sh >>/var/log/openvman-certbot-renew.log 2>&1
set -eu

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

CERTBOT_IMAGE="${CERTBOT_IMAGE:-certbot/certbot@sha256:34ee91d2f43008eb78a007d22f23ed4b2eaa9a454cb27ca2c042b49527a695b4}"
WEBROOT="${CERTBOT_WEBROOT:-/usr/share/nginx/html}"
LETSENCRYPT_DIR="${LETSENCRYPT_DIR:-$REPO_ROOT/infra/nginx/certs/letsencrypt}"

# --dry-run 只模擬，不會動到現有憑證，適合驗證流程還通不通。
docker run --rm \
  -v "$WEBROOT:/var/www/certbot" \
  -v "$LETSENCRYPT_DIR:/etc/letsencrypt" \
  "$CERTBOT_IMAGE" renew \
  --webroot-path /var/www/certbot \
  --non-interactive "$@"

# 續期後讓 host nginx 重讀憑證。nginx 由 root 持有，而這支腳本以一般使用者
# 執行，所以借一個 --privileged 容器送 SIGHUP，避免整支腳本都要 sudo。
nginx_pid="$(ps -eo pid=,args= | awk '$0 ~ /nginx: master process \/usr\/sbin\/nginx -c \/etc\/nginx\/nginx\.conf/ {print $1; exit}')"
if [ -n "$nginx_pid" ]; then
  docker run --rm --pid=host --privileged alpine:3.20 kill -HUP "$nginx_pid"
else
  echo "warning: host nginx master process not found; certificate reload skipped" >&2
fi
