#!/usr/bin/env bash

# One-time setup per clone; Git does not install tracked hooks automatically.
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
hook_dir="$(git rev-parse --git-path hooks)"
hook_path="$hook_dir/pre-commit"
source_path="$repo_root/scripts/pre_commit_guard.sh"

mkdir -p "$hook_dir"
if [[ -e "$hook_path" ]] && ! cmp -s "$hook_path" "$source_path"; then
  echo "Existing pre-commit hook at $hook_path; integrate the raw-fixture guard manually." >&2
  exit 1
fi

install -m 755 "$source_path" "$hook_path"
echo "Installed raw-fixture pre-commit hook at $hook_path"
