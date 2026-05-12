#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -f "$REPO_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.env"
  set +a
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
CODEX_BIN="${CODEX_BIN:-codex}"
CODEX_MODEL="${CODEX_MODEL:-gpt-5.3-codex}"
LOOKBACK_HOURS="${LOOKBACK_HOURS:-24}"
TIMEZONE="${TIMEZONE:-Asia/Shanghai}"
MAX_COMMENTS="${MAX_COMMENTS:-20}"
PUSH="${PUSH:-1}"

cd "$REPO_ROOT"

DATA_FILE="$("$PYTHON_BIN" scripts/fetch_pytorch_issues.py \
  --hours "$LOOKBACK_HOURS" \
  --timezone "$TIMEZONE" \
  --max-comments "$MAX_COMMENTS" \
  --print-output-path)"

REPORT_DATE="$(basename "$(dirname "$DATA_FILE")")"
REPORT_FILE="reports/${REPORT_DATE}.md"
PROMPT_FILE="$(mktemp)"

cleanup() {
  rm -f "$PROMPT_FILE"
}
trap cleanup EXIT

sed \
  -e "s|{{DATA_FILE}}|${DATA_FILE}|g" \
  -e "s|{{REPORT_DATE}}|${REPORT_DATE}|g" \
  prompts/analyze_daily_issues.md > "$PROMPT_FILE"

"$CODEX_BIN" exec \
  --cd "$REPO_ROOT" \
  --sandbox workspace-write \
  -m "$CODEX_MODEL" \
  -o "$REPORT_FILE" \
  - < "$PROMPT_FILE"

git add "$DATA_FILE" "$REPORT_FILE"

if git diff --cached --quiet; then
  echo "No digest changes to commit."
  exit 0
fi

git commit -m "Add PyTorch issue digest for ${REPORT_DATE}"

if [[ "$PUSH" == "1" ]]; then
  git push origin HEAD
fi
