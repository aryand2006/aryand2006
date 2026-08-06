#!/usr/bin/env bash
# Install with: cp ci/pre-commit-hook.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
#
# Gates staged work against the last commit. Warn-only by default so it never
# blocks a work-in-progress commit; add --strict once the baseline is settled.

set -euo pipefail

if ! command -v sediment >/dev/null 2>&1; then
  exit 0
fi

if git rev-parse --verify HEAD >/dev/null 2>&1; then
  sediment gate --base HEAD --head HEAD || {
    echo
    echo "sediment: this change adds structural debt. Commit anyway with --no-verify."
    exit 1
  }
fi
