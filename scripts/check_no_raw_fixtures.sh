#!/usr/bin/env bash

set -euo pipefail

raw_fixtures="$(git ls-files -- tests/fixtures/raw)"

if [[ -n "${raw_fixtures}" ]]; then
  echo "ERROR: raw fixtures must never be committed to this public repository." >&2
  echo "Remove these tracked files and add only redacted copies under tests/fixtures/anonymized/:" >&2
  printf '%s\n' "${raw_fixtures}" >&2
  exit 1
fi
