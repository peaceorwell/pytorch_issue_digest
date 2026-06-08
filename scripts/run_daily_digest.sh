#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

REQUEST_PYTHON_BIN="${PYTHON_BIN-}"
REQUEST_CODEX_BIN="${CODEX_BIN-}"
REQUEST_CODEX_MODEL="${CODEX_MODEL-}"
REQUEST_LOOKBACK_HOURS="${LOOKBACK_HOURS-}"
REQUEST_TIMEZONE="${TIMEZONE-}"
REQUEST_MAX_COMMENTS="${MAX_COMMENTS-}"
REQUEST_PUSH="${PUSH-}"

if [[ -f "$REPO_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.env"
  set +a
fi

PYTHON_BIN="${REQUEST_PYTHON_BIN:-${PYTHON_BIN:-/usr/bin/python3}}"
CODEX_BIN="${REQUEST_CODEX_BIN:-${CODEX_BIN:-/Applications/Codex.app/Contents/Resources/codex}}"
CODEX_MODEL="${REQUEST_CODEX_MODEL:-${CODEX_MODEL:-}}"
LOOKBACK_HOURS="${REQUEST_LOOKBACK_HOURS:-${LOOKBACK_HOURS:-24}}"
TIMEZONE="${REQUEST_TIMEZONE:-${TIMEZONE:-Asia/Shanghai}}"
MAX_COMMENTS="${REQUEST_MAX_COMMENTS:-${MAX_COMMENTS:-20}}"
PUSH="${REQUEST_PUSH:-${PUSH:-1}}"

cd "$REPO_ROOT"

DATA_FILE="$("$PYTHON_BIN" scripts/fetch_pytorch_issues.py \
  --hours "$LOOKBACK_HOURS" \
  --timezone "$TIMEZONE" \
  --max-comments "$MAX_COMMENTS" \
  --print-output-path)"

REPORT_DATE="$(basename "$(dirname "$DATA_FILE")")"
REPORT_FILE="reports/${REPORT_DATE}.md"
PROMPT_FILE="$(mktemp)"
CODEX_DATA_FILE="$(mktemp)"

cleanup() {
  rm -f "$PROMPT_FILE" "$CODEX_DATA_FILE"
}
trap cleanup EXIT

"$PYTHON_BIN" scripts/compact_issues_for_codex.py "$DATA_FILE" "$CODEX_DATA_FILE"

sed \
  -e "s|{{DATA_FILE}}|${CODEX_DATA_FILE}|g" \
  -e "s|{{REPORT_DATE}}|${REPORT_DATE}|g" \
  prompts/analyze_daily_issues.md > "$PROMPT_FILE"

CODEX_ARGS=(
  exec
  --cd "$REPO_ROOT"
  --sandbox workspace-write
  -o "$REPORT_FILE"
)

if [[ -n "$CODEX_MODEL" && "$CODEX_MODEL" != "auto" ]]; then
  CODEX_ARGS+=(-m "$CODEX_MODEL")
fi

if ! "$CODEX_BIN" "${CODEX_ARGS[@]}" - < "$PROMPT_FILE"; then
  echo "warning: Codex report generation failed; falling back to local renderer" >&2
  "$PYTHON_BIN" scripts/render_report.py "$DATA_FILE" "$REPORT_FILE"
fi

if [[ ! -s "$REPORT_FILE" ]]; then
  "$PYTHON_BIN" scripts/render_report.py "$DATA_FILE" "$REPORT_FILE"
fi

git add "$DATA_FILE" "$REPORT_FILE"

if git diff --cached --quiet; then
  echo "No digest changes to commit."
  exit 0
fi

git commit -m "Add PyTorch issue digest for ${REPORT_DATE}"

if [[ "$PUSH" == "1" ]]; then
  git push origin HEAD
fi
