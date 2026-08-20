#!/bin/sh
# One-time public HTTPS setup for a host that already runs the Compose stack.
# It bootstraps the ACME HTTP route before the certificate exists, then swaps
# in the full vhost and installs one idempotent renewal cron entry.
set -eu

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RENDER_SCRIPT="$REPO_ROOT/scripts/render-native-nginx.sh"
RENEW_SCRIPT="$REPO_ROOT/scripts/renew-letsencrypt.sh"
RENDERED_CONFIG="$REPO_ROOT/infra/nginx/native/openvman.conf"
ENV_FILE="${OPENVMAN_ENV_FILE:-$REPO_ROOT/.env}"

read_env_value() {
  [ -f "$ENV_FILE" ] || return 0
  awk -v wanted="$1" '
    function trim(value) {
      sub(/^[[:space:]]+/, "", value)
      sub(/[[:space:]]+$/, "", value)
      return value
    }
    /^[[:space:]]*#/ { next }
    {
      separator = index($0, "=")
      if (!separator) next
      key = trim(substr($0, 1, separator - 1))
      if (key != wanted) next
      value = trim(substr($0, separator + 1))
      first = substr(value, 1, 1)
      last = substr(value, length(value), 1)
      if (length(value) >= 2 && ((first == "\"" && last == "\"") || (first == "\047" && last == "\047"))) {
        value = substr(value, 2, length(value) - 2)
      }
      print value
      exit
    }
  ' "$ENV_FILE"
}

PUBLIC_DOMAIN="${PUBLIC_DOMAIN:-$(read_env_value PUBLIC_DOMAIN)}"
LETSENCRYPT_EMAIL="${LETSENCRYPT_EMAIL:-$(read_env_value LETSENCRYPT_EMAIL)}"
LETSENCRYPT_DIR="${LETSENCRYPT_DIR:-$REPO_ROOT/infra/nginx/certs/letsencrypt}"
ACME_WEBROOT="${ACME_WEBROOT:-/usr/share/nginx/html}"
EDGE_UPSTREAM="${EDGE_UPSTREAM:-127.0.0.1:8787}"
NGINX_CONFIG_PATH="${NGINX_CONFIG_PATH:-/etc/nginx/conf.d/openvman.conf}"
NGINX_BIN="${NGINX_BIN:-/usr/sbin/nginx}"
SYSTEMCTL_BIN="${SYSTEMCTL_BIN:-/usr/bin/systemctl}"
RENEW_LOG="${LETSENCRYPT_RENEW_LOG:-$REPO_ROOT/backend/logs/letsencrypt-renew.log}"
CRON_SCHEDULE="${LETSENCRYPT_CRON_SCHEDULE:-17 4 * * *}"
CERTBOT_IMAGE="${CERTBOT_IMAGE:-certbot/certbot@sha256:34ee91d2f43008eb78a007d22f23ed4b2eaa9a454cb27ca2c042b49527a695b4}"

usage() {
  printf '%s\n' \
    'Usage:' \
    '  Set PUBLIC_DOMAIN and LETSENCRYPT_EMAIL in .env, then run:' \
    '    ./scripts/setup-public-https.sh [--dry-run]' \
    '' \
    '  Or override them for one run:' \
    '  PUBLIC_DOMAIN=example.com LETSENCRYPT_EMAIL=ops@example.com \' \
    '    ./scripts/setup-public-https.sh [--dry-run]'
}

fail() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "$1 is required"
}

run_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  else
    sudo "$@"
  fi
}

reload_or_start_nginx() {
  if "$SYSTEMCTL_BIN" is-active --quiet nginx; then
    run_root "$SYSTEMCTL_BIN" reload nginx
  else
    run_root "$SYSTEMCTL_BIN" start nginx
  fi
}

quote_for_shell() {
  printf "'"
  printf '%s' "$1" | sed "s/'/'\\\\''/g"
  printf "'"
}

case "${1:-}" in
  "") ;;
  --dry-run) DRY_RUN=true ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
DRY_RUN="${DRY_RUN:-false}"

[ -n "$PUBLIC_DOMAIN" ] || fail "PUBLIC_DOMAIN is required"
printf '%s' "$PUBLIC_DOMAIN" | grep -Eq \
  '^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$' \
  || fail "PUBLIC_DOMAIN is not a valid DNS hostname"
[ -n "$LETSENCRYPT_EMAIL" ] || fail "LETSENCRYPT_EMAIL is required"

if [ "$DRY_RUN" = true ]; then
  printf 'render nginx vhost for %s\n' "$PUBLIC_DOMAIN"
  printf "issue initial Let's Encrypt certificate for %s\n" "$PUBLIC_DOMAIN"
  printf 'install and reload host nginx at %s\n' "$NGINX_CONFIG_PATH"
  printf 'install idempotent renewal cron: %s\n' "$CRON_SCHEDULE"
  exit 0
fi

for command_name in docker envsubst grep install mktemp sed awk crontab; do
  require_command "$command_name"
done
if [ "$(id -u)" -ne 0 ]; then
  require_command sudo
fi
[ -x "$NGINX_BIN" ] || fail "nginx binary not executable: $NGINX_BIN"
[ -x "$SYSTEMCTL_BIN" ] || fail "systemctl binary not executable: $SYSTEMCTL_BIN"

DOCKER_BIN="$(command -v docker)"
CRONTAB_BIN="$(command -v crontab)"
NGINX_CONFIG_DIR="$(dirname "$NGINX_CONFIG_PATH")"
FULLCHAIN="$LETSENCRYPT_DIR/live/$PUBLIC_DOMAIN/fullchain.pem"
PRIVATE_KEY="$LETSENCRYPT_DIR/live/$PUBLIC_DOMAIN/privkey.pem"

PUBLIC_DOMAIN="$PUBLIC_DOMAIN" \
LETSENCRYPT_DIR="$LETSENCRYPT_DIR" \
EDGE_UPSTREAM="$EDGE_UPSTREAM" \
ACME_WEBROOT="$ACME_WEBROOT" \
  "$RENDER_SCRIPT" "$RENDERED_CONFIG"

run_root install -d -m 0755 "$ACME_WEBROOT" "$NGINX_CONFIG_DIR"
mkdir -p "$LETSENCRYPT_DIR"

bootstrap_config=""
nginx_backup=""
nginx_had_config=false
nginx_restore_active=false
cron_current=""
cron_updated=""
cron_error=""

prepare_nginx_rollback() {
  [ "$nginx_restore_active" = false ] || return 0
  if run_root test -e "$NGINX_CONFIG_PATH"; then
    nginx_backup="$(mktemp)"
    run_root cp -p "$NGINX_CONFIG_PATH" "$nginx_backup"
    nginx_had_config=true
  fi
  nginx_restore_active=true
}

cleanup() {
  status=$?
  trap - EXIT HUP INT TERM

  # Restore the previous vhost unless the full config passed validation/reload.
  if [ "$nginx_restore_active" = true ]; then
    if [ "$nginx_had_config" = true ]; then
      run_root cp -p "$nginx_backup" "$NGINX_CONFIG_PATH" || :
    else
      run_root rm -f "$NGINX_CONFIG_PATH" || :
    fi
    if run_root "$NGINX_BIN" -t; then
      reload_or_start_nginx || :
    fi
  fi

  [ -z "$bootstrap_config" ] || rm -f "$bootstrap_config"
  [ -z "$nginx_backup" ] || run_root rm -f "$nginx_backup"
  [ -z "$cron_current" ] || rm -f "$cron_current"
  [ -z "$cron_updated" ] || rm -f "$cron_updated"
  [ -z "$cron_error" ] || rm -f "$cron_error"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

if ! run_root test -s "$FULLCHAIN" || ! run_root test -s "$PRIVATE_KEY"; then
  bootstrap_config="$(mktemp)"
  {
    printf 'server {\n'
    printf '    listen 80;\n'
    printf '    listen [::]:80;\n'
    printf '    server_name %s;\n' "$PUBLIC_DOMAIN"
    printf '    location ^~ /.well-known/acme-challenge/ {\n'
    printf '        root "%s";\n' "$ACME_WEBROOT"
    printf '        default_type text/plain;\n'
    printf '        try_files $uri =404;\n'
    printf '    }\n'
    printf '    location / { return 404; }\n'
    printf '}\n'
  } > "$bootstrap_config"

  prepare_nginx_rollback
  run_root install -m 0644 "$bootstrap_config" "$NGINX_CONFIG_PATH"
  run_root "$NGINX_BIN" -t
  reload_or_start_nginx

  "$DOCKER_BIN" run --rm \
    -v "$ACME_WEBROOT:/var/www/certbot" \
    -v "$LETSENCRYPT_DIR:/etc/letsencrypt" \
    "$CERTBOT_IMAGE" certonly \
    --webroot \
    --webroot-path /var/www/certbot \
    --domain "$PUBLIC_DOMAIN" \
    --email "$LETSENCRYPT_EMAIL" \
    --agree-tos \
    --non-interactive

  run_root test -s "$FULLCHAIN" \
    || fail "certbot completed without $FULLCHAIN"
  run_root test -s "$PRIVATE_KEY" \
    || fail "certbot completed without $PRIVATE_KEY"
else
  printf 'certificate already exists for %s; issuance skipped\n' "$PUBLIC_DOMAIN"
fi

prepare_nginx_rollback
run_root install -m 0644 "$RENDERED_CONFIG" "$NGINX_CONFIG_PATH"
run_root "$NGINX_BIN" -t
reload_or_start_nginx
nginx_restore_active=false

mkdir -p "$(dirname "$RENEW_LOG")"
touch "$RENEW_LOG"

cron_current="$(mktemp)"
cron_updated="$(mktemp)"
cron_error="$(mktemp)"
if ! LC_ALL=C "$CRONTAB_BIN" -l > "$cron_current" 2>"$cron_error"; then
  if ! grep -Fq "no crontab for" "$cron_error"; then
    cat "$cron_error" >&2
    fail "could not read the current crontab; existing jobs were not changed"
  fi
fi

cron_begin="# BEGIN openvman letsencrypt renewal: $REPO_ROOT"
cron_end="# END openvman letsencrypt renewal: $REPO_ROOT"
awk -v begin="$cron_begin" -v end="$cron_end" '
  $0 == begin { skip = 1; next }
  $0 == end { skip = 0; next }
  !skip { print }
' "$cron_current" > "$cron_updated"

docker_value="$(quote_for_shell "$DOCKER_BIN")"
webroot_value="$(quote_for_shell "$ACME_WEBROOT")"
letsencrypt_value="$(quote_for_shell "$LETSENCRYPT_DIR")"
renew_value="$(quote_for_shell "$RENEW_SCRIPT")"
log_value="$(quote_for_shell "$RENEW_LOG")"
{
  printf '\n%s\n' "$cron_begin"
  printf '%s DOCKER_BIN=%s CERTBOT_WEBROOT=%s LETSENCRYPT_DIR=%s %s >>%s 2>&1\n' \
    "$CRON_SCHEDULE" \
    "$docker_value" \
    "$webroot_value" \
    "$letsencrypt_value" \
    "$renew_value" \
    "$log_value"
  printf '%s\n' "$cron_end"
} >> "$cron_updated"
"$CRONTAB_BIN" "$cron_updated"

printf 'public HTTPS ready\n'
printf '  domain: https://%s/openvman/\n' "$PUBLIC_DOMAIN"
printf '  nginx:  %s\n' "$NGINX_CONFIG_PATH"
printf '  renew:  %s\n' "$CRON_SCHEDULE"
printf '  log:    %s\n' "$RENEW_LOG"
