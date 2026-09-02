#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

ENV_FILE=".env"
REQUIRED_SECRETS=(
  "GATEWAY_INTERNAL_TOKEN"
  "SESSION_JWT_SECRET"
  "GRAFANA_PASSWORD"
)

if ! command -v openssl >/dev/null 2>&1; then
  printf 'openssl is required to generate runtime secrets.\n' >&2
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  cp .env.example "$ENV_FILE"
fi
chmod 600 "$ENV_FILE"

replace_or_append() {
  local key="$1"
  local value="$2"
  local temporary
  temporary="$(mktemp "${ENV_FILE}.XXXXXX")"

  awk -v key="$key" -v value="$value" '
    BEGIN { replaced = 0 }
    index($0, key "=") == 1 {
      if (!replaced) {
        print key "=" value
        replaced = 1
      }
      next
    }
    { print }
    END {
      if (!replaced) print key "=" value
    }
  ' "$ENV_FILE" > "$temporary"

  chmod --reference="$ENV_FILE" "$temporary"
  mv "$temporary" "$ENV_FILE"
}

generated=()
for key in "${REQUIRED_SECRETS[@]}"; do
  current="$(awk -F= -v key="$key" '
    $1 == key {
      sub(/^[^=]*=/, "")
      sub(/[[:space:]]+#.*$/, "")
      gsub(/^[[:space:]]+|[[:space:]]+$/, "")
      print
      exit
    }
  ' "$ENV_FILE")"
  if [ -n "$current" ]; then
    continue
  fi

  replace_or_append "$key" "$(openssl rand -hex 32)"
  generated+=("$key")
done

if [ "${#generated[@]}" -eq 0 ]; then
  printf 'Runtime secrets already configured.\n'
else
  printf 'Generated missing runtime secrets: %s\n' "${generated[*]}"
fi
