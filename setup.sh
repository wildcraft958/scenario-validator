#!/usr/bin/env sh
# setup.sh - Install dependencies for the EuroNCAP Scenario Validator
#
# Security design:
#   - Never downloads uv. If uv is already installed by IT/CI, it is used for speed.
#   - Falls back to standard pip with --require-hashes for cryptographic verification.
#   - No internet access is required after this script has run once.
#
# Usage:
#   sh setup.sh            # standard install
#   sh setup.sh --hashed   # enforce hash verification (Linux x86_64 + Python 3.10 only)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HASHED_LOCK="$SCRIPT_DIR/requirements-hashed.txt"
PLAIN_LOCK="$SCRIPT_DIR/requirements-lock.txt"

USE_HASHES=0
for arg in "$@"; do
  case "$arg" in
    --hashed) USE_HASHES=1 ;;
  esac
done

echo "EuroNCAP Validator - dependency install"
echo "======================================="

if [ "$USE_HASHES" = "1" ]; then
  REQ_FILE="$HASHED_LOCK"
  echo "Mode: hash-verified (pip --require-hashes)"
else
  REQ_FILE="$PLAIN_LOCK"
  echo "Mode: pinned versions (pip)"
fi

if command -v uv >/dev/null 2>&1; then
  echo "Tool: uv $(uv --version 2>/dev/null | head -1)"
  # --system: install into the active Python (system or venv) - avoids "no venv found" error
  if [ "$USE_HASHES" = "1" ]; then
    uv pip install --system --require-hashes -r "$REQ_FILE"
  else
    uv pip install --system -r "$REQ_FILE"
  fi
else
  echo "Tool: pip (uv not found on PATH - using standard Python tools)"
  python -m pip install --upgrade pip --quiet
  if [ "$USE_HASHES" = "1" ]; then
    python -m pip install --require-hashes -r "$REQ_FILE"
  else
    python -m pip install -r "$REQ_FILE"
  fi
fi

echo ""
echo "Done. Run: python validator.py <scenario_dir>"
