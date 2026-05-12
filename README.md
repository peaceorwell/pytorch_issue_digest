# PyTorch Issue Digest

Daily local automation for tracking recently updated `pytorch/pytorch` issues whose titles contain `compile`, `inductor`, or `dynamo`.

The workflow keeps Codex analysis on your own machine, so no OpenAI API key has to be stored in GitHub Actions secrets.

## What It Does

1. Fetches issues updated in the last 24 hours.
2. Filters to titles containing `compile`, `inductor`, or `dynamo`, case-insensitively.
3. Saves raw issue data to `data/YYYY-MM-DD/issues.json`.
4. Runs local `codex exec` to analyze the issues.
5. Writes the Markdown report to `reports/YYYY-MM-DD.md`.
6. Commits and pushes both files to this repository.

## Requirements

- Python 3.9 or newer.
- Git.
- Codex CLI available as `codex`.
- A local Codex login/session that can run `codex exec`.
- Optional but recommended: `GITHUB_TOKEN` in the environment to raise GitHub API rate limits.

## Run Manually

```bash
./scripts/run_daily_digest.sh
```

Useful overrides:

```bash
GITHUB_TOKEN=... LOOKBACK_HOURS=24 MAX_COMMENTS=20 ./scripts/run_daily_digest.sh
PUSH=0 ./scripts/run_daily_digest.sh
CODEX_MODEL=gpt-5.3-codex ./scripts/run_daily_digest.sh
```

For scheduled runs, put environment variables in `.env`:

```bash
GITHUB_TOKEN=github_pat_...
CODEX_MODEL=gpt-5.3-codex
LOOKBACK_HOURS=24
MAX_COMMENTS=20
PUSH=1
```

## macOS Daily Schedule

Install a daily 09:00 macOS `launchd` job:

```bash
./scripts/install_launchd.sh
```

Change the schedule:

```bash
HOUR=8 MINUTE=30 ./scripts/install_launchd.sh
```

## Fetch Only

```bash
python3 scripts/fetch_pytorch_issues.py
```
