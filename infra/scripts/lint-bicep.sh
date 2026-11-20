#!/usr/bin/env bash
# lint-bicep.sh: compile infra/main.bicep with the linter rules as hard failures (spec 25 §4; make infra-lint).
#
# Why it exists: `az bicep build` exits 0 on linter warnings; AC-25.8 asks for no
#   warning and no error under infra/bicepconfig.json, so this script fails on either.
# What it does: builds to stdout (discarded) and fails when a diagnostic line
#   "<file>(line,col) : Warning|Error <rule>" appears. Other az notices are ignored.
# Must not: deploy, or call Azure beyond what `az bicep build` needs (nothing).
# Acceptance criteria: AC-25.8.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
out="$(az bicep build --file "$ROOT/infra/main.bicep" --stdout 2>&1 >/dev/null)"
if grep -E ' : (Warning|Error) ' <<<"$out"; then
  exit 1
fi
echo "bicep: no warnings or errors"
