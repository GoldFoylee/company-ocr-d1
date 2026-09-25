#!/usr/bin/env bash

# Canonical local backend test command: guard first, then pytest in Docker.
# A linked worktree's .git is a pointer to metadata outside the bind-mounted
# source tree. Mount the common Git directory read-only and tell Git which
# worktree-specific index to use, so the in-container guard really runs.
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
git_dir="$(git rev-parse --absolute-git-dir)"
git_common_dir="$(git rev-parse --path-format=absolute --git-common-dir)"

if [[ "$git_dir" == "$git_common_dir" ]]; then
  container_git_dir=/git-metadata
elif [[ "$git_dir" == "$git_common_dir"/* ]]; then
  container_git_dir="/git-metadata/${git_dir#"$git_common_dir"/}"
else
  echo "Git metadata is outside the common Git directory: $git_dir" >&2
  exit 2
fi

cd "$repo_root"
docker_args=(
  run --rm -T
  -v "$git_common_dir:/git-metadata:ro"
  -e "GIT_DIR=$container_git_dir"
  -e GIT_WORK_TREE=/app
  -e GIT_CONFIG_COUNT=1
  -e GIT_CONFIG_KEY_0=safe.directory
  -e GIT_CONFIG_VALUE_0=/app
)

if [[ "${1:-}" == "--guard-only" ]]; then
  shift
  if [[ "$#" -ne 0 ]]; then
    echo "--guard-only takes no pytest arguments" >&2
    exit 2
  fi
  docker compose "${docker_args[@]}" --no-deps app scripts/check_no_raw_fixtures.sh
else
  docker compose "${docker_args[@]}" app \
    bash -c 'scripts/check_no_raw_fixtures.sh && unset GIT_DIR GIT_WORK_TREE GIT_CONFIG_COUNT GIT_CONFIG_KEY_0 GIT_CONFIG_VALUE_0 && exec pytest "$@"' bash "$@"
fi
