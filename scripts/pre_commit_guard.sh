#!/usr/bin/env bash

# Installed by scripts/install_dev_hooks.sh into the clone's Git hooks dir.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
scripts/check_no_raw_fixtures.sh

# Keep the existing .pre-commit-config.yaml lint hooks when the optional
# pre-commit CLI is installed. The privacy guard itself never depends on it.
if command -v pre-commit >/dev/null 2>&1; then
  pre-commit run --hook-type pre-commit
fi
