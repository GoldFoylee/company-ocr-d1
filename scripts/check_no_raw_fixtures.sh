#!/usr/bin/env bash

set -euo pipefail

tracked_sensitive_data="$(git ls-files -- tests/fixtures/raw data)"

if [[ -n "${tracked_sensitive_data}" ]]; then
  echo "ERROR: raw fixtures and real upload data must never be committed to this public repository." >&2
  echo "Remove these tracked files. Only redacted copies belong under tests/fixtures/anonymized/:" >&2
  printf '%s\n' "${tracked_sensitive_data}" >&2
  exit 1
fi
