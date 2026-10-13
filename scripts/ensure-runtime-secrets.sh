#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

ENV_FILE=".env"
REQUIRED_SECRETS=(
  "GATEWAY_INTERNAL_TOKEN"
  "SESSION_JWT_SECRET"
  "DECISION_PROVIDER_ENCRYPTION_SECRET"
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

# 後台存的模型供應商金鑰是用 DECISION_PROVIDER_ENCRYPTION_SECRET 加密的。資料庫裡已經有
# 加密金鑰、這個值卻不見時（.env 被覆蓋、還原了舊版），自動補一個新的會讓那些金鑰全部
# 解不開，而且沒有人會發現。這種情況停下來，讓人把原本的值找回來。
# 資料庫在、但從沒存過金鑰（只靠 watchtower 部署、沒跑過這支腳本的機器）就照常產生。
auth_database_path() {
  local configured
  configured="$(awk -F= '$1 == "AUTH_DATABASE_PATH" { sub(/^[^=]*=/, ""); sub(/[[:space:]]+#.*$/, ""); gsub(/^[[:space:]]+|[[:space:]]+$/, ""); print; exit }' "$ENV_FILE")"
  configured="${configured:-/data/auth/accounts.db}"
  # compose 把 ./data 掛到容器的 /data；其他位置從主機這邊看不到，就不檢查。
  case "$configured" in
    /data/*) printf 'data/%s\n' "${configured#/data/}" ;;
  esac
}

# 印出資料庫裡已加密的金鑰筆數；讀不了（沒有 python3、檔案損壞）時印 unknown，當成有。
stored_credentials() {
  python3 - "$1" <<'PY' 2>/dev/null || printf 'unknown\n'
import sqlite3, sys
connection = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
print(sum(
    connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    for table in ("model_provider_secrets", "decision_provider_secrets") if table in tables
))
PY
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

  if [ "$key" = "DECISION_PROVIDER_ENCRYPTION_SECRET" ]; then
    database="$(auth_database_path)"
    if [ -n "$database" ] && [ -f "$database" ]; then
      stored="$(stored_credentials "$database")"
      if [ "$stored" != "0" ]; then
        printf '%s is missing but %s already holds %s encrypted API key(s).\n' "$key" "$database" "$stored" >&2
        printf 'Restore the original value from your .env backup; a new one would make every API key saved in the Admin unreadable.\n' >&2
        exit 1
      fi
    fi
  fi

  replace_or_append "$key" "$(openssl rand -hex 32)"
  generated+=("$key")
done

if [ "${#generated[@]}" -eq 0 ]; then
  printf 'Runtime secrets already configured.\n'
else
  printf 'Generated missing runtime secrets: %s\n' "${generated[*]}"
fi
