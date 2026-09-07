#!/bin/sh
# Deploy the host nginx vhost from this repository to /etc/nginx/conf.d/.
#
# The host's own nginx is not managed by compose, so an edit to the template
# only reaches production through this script. It renders, backs up, validates
# and reloads — and rolls back if nginx rejects the new config.
#
#   PUBLIC_DOMAIN=146.5gao.ai ./infra/nginx/native/deploy.sh
#
# --check  render and diff against what is installed, changing nothing.
set -eu

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"

# 主機上實際生效的檔名帶 146- 前綴；工具鏈曾預設 openvman.conf，兩者對不上時
# 部署會寫到一個 nginx 根本沒載入的檔案，設定就這樣悄悄分岔。
# scripts/setup-public-https.sh 共用這個預設值。
NGINX_CONFIG_PATH="${NGINX_CONFIG_PATH:-/etc/nginx/conf.d/146-openvman.conf}"

CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

if [ -z "${PUBLIC_DOMAIN:-}" ] && [ -f "$REPO_ROOT/.env" ]; then
  PUBLIC_DOMAIN="$(sed -n 's/^PUBLIC_DOMAIN=//p' "$REPO_ROOT/.env" | tail -n 1)"
fi
if [ -z "${PUBLIC_DOMAIN:-}" ]; then
  echo "error: PUBLIC_DOMAIN is required (set it in .env or the environment)" >&2
  exit 1
fi
export PUBLIC_DOMAIN

run_root() {
  if [ "$(id -u)" = 0 ]; then "$@"; else sudo "$@"; fi
}

rendered="$(mktemp)"
trap 'rm -f "$rendered"' EXIT
"$REPO_ROOT/scripts/render-native-nginx.sh" "$rendered" >/dev/null

if [ -r "$NGINX_CONFIG_PATH" ]; then
  if diff -u "$NGINX_CONFIG_PATH" "$rendered"; then
    echo "already in sync: $NGINX_CONFIG_PATH"
    exit 0
  fi
else
  echo "not installed yet: $NGINX_CONFIG_PATH"
fi

if [ "$CHECK_ONLY" = 1 ]; then
  echo "drift detected (--check made no changes)" >&2
  exit 1
fi

backup=""
if [ -e "$NGINX_CONFIG_PATH" ]; then
  backup="$NGINX_CONFIG_PATH.bak-$(date +%Y%m%d-%H%M%S)"
  run_root cp -p "$NGINX_CONFIG_PATH" "$backup"
  echo "backed up to $backup"
fi

run_root install -m 0644 "$rendered" "$NGINX_CONFIG_PATH"

# nginx -t 檢查的是整個 conf.d，所以驗證失敗時必須把舊檔放回去再 reload，
# 否則下一次任何原因的 reload 都會拿新檔失敗。
if ! run_root nginx -t; then
  echo "error: nginx rejected the config, rolling back" >&2
  if [ -n "$backup" ]; then
    run_root cp -p "$backup" "$NGINX_CONFIG_PATH"
  else
    run_root rm -f "$NGINX_CONFIG_PATH"
  fi
  exit 1
fi

run_root systemctl reload nginx
echo "reloaded nginx with $NGINX_CONFIG_PATH"
