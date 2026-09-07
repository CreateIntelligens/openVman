#!/usr/bin/env bash
# Bring the stack up with its host-side preconditions already satisfied.
#
# Both preconditions fail in ways that are hard to read after the fact — a
# bind mount Docker created as root surfaces much later as a permission error
# deep inside a service, and a missing secret as a startup failure — so they
# are enforced here rather than documented as steps to remember.
#
#   ./scripts/up.sh              # up -d
#   ./scripts/up.sh backend      # pass anything through to `compose up`
#
# Both steps are idempotent and quiet when there is nothing to do; run them
# directly if you want them without starting anything.
set -euo pipefail

cd "$(dirname "$0")/.."

./scripts/ensure-data-dirs.sh
./scripts/ensure-runtime-secrets.sh >/dev/null

exec docker compose up -d "$@"
