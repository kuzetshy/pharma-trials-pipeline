#!/usr/bin/env bash
# ==============================================================================
# Install version-controlled Git pre-commit hooks
# ==============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOKS_DIR="${REPO_ROOT}/.git/hooks"
SOURCE_HOOK="${REPO_ROOT}/scripts/git-hooks/pre-commit"

if [ ! -d "${HOOKS_DIR}" ]; then
    echo "❌ Git directory not found at ${HOOKS_DIR}. Run inside a git repository."
    exit 1
fi

echo "📦 Installing pre-commit guard to ${HOOKS_DIR}/pre-commit..."
cp "${SOURCE_HOOK}" "${HOOKS_DIR}/pre-commit"
chmod +x "${HOOKS_DIR}/pre-commit"

echo "✅ Git pre-commit guard installed successfully!"
