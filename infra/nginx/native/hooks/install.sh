#!/bin/sh
# Install this directory's git hooks into .git/hooks/.
#
# Hooks live outside version control, so each clone installs them once:
#
#   ./infra/nginx/native/hooks/install.sh
#
# A global core.hooksPath (gitleaks, husky) keeps working: git runs the global
# hook, which chains into the repo-local one this installs.
set -eu

REPO_ROOT="$(git rev-parse --show-toplevel)"
SOURCE_DIR="$REPO_ROOT/infra/nginx/native/hooks"
TARGET_DIR="$REPO_ROOT/.git/hooks"

hook="pre-commit"
target="$TARGET_DIR/$hook"

if [ -e "$target" ] && ! cmp -s "$SOURCE_DIR/$hook" "$target"; then
  echo "error: $target already exists and differs from the one here." >&2
  echo "       Merge it by hand rather than losing the existing hook." >&2
  exit 1
fi

install -m 0755 "$SOURCE_DIR/$hook" "$target"
echo "installed $target"
