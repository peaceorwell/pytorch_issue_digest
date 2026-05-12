#!/usr/bin/env python3
"""Fetch recently updated PyTorch issues whose titles match compiler keywords."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


DEFAULT_REPO = "pytorch/pytorch"
DEFAULT_KEYWORDS = ("compile", "inductor", "dynamo")
GITHUB_API = "https://api.github.com"


class GitHubApiError(RuntimeError):
    def __init__(self, status: int, reason: str, url: str, body: str) -> None:
        super().__init__(f"GitHub API request failed: {status} {reason}\n{url}\n{body}")
        self.status = status
        self.reason = reason
        self.url = url
        self.body = body


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=DEFAULT_REPO, help="GitHub repo in owner/name form.")
    parser.add_argument(
        "--keyword",
        action="append",
        dest="keywords",
        help="Title keyword to match. Repeatable. Defaults to compile, inductor, dynamo.",
    )
    parser.add_argument("--hours", type=float, default=24.0, help="Lookback window in hours.")
    parser.add_argument("--timezone", default="Asia/Shanghai", help="Date timezone for output paths.")
    parser.add_argument("--output", help="Output JSON path. Defaults to data/YYYY-MM-DD/issues.json.")
    parser.add_argument("--max-comments", type=int, default=20, help="Maximum recent comments per issue.")
    parser.add_argument("--per-page", type=int, default=100, help="GitHub API page size.")
    parser.add_argument("--sleep", type=float, default=0.2, help="Delay between GitHub API calls.")
    parser.add_argument("--print-output-path", action="store_true", help="Print only the output path.")
    return parser.parse_args()


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def parse_github_time(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def request_json(url: str, token: str | None) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "pytorch-issue-digest",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise GitHubApiError(exc.code, exc.reason, url, body) from exc


def search_issues(
    repo: str,
    keyword: str,
    since: dt.datetime,
    token: str | None,
    per_page: int,
    sleep_seconds: float,
) -> list[dict[str, Any]]:
    # Search supports date granularity more reliably than exact timestamps; filter exact updated_at locally.
    search_from = since.date().isoformat()
    query = f"repo:{repo} is:issue in:title {keyword} updated:>={search_from}"
    encoded_query = urllib.parse.quote(query)
    items: list[dict[str, Any]] = []

    for page in range(1, 11):
        url = (
            f"{GITHUB_API}/search/issues?q={encoded_query}"
            f"&sort=updated&order=desc&per_page={per_page}&page={page}"
        )
        payload = request_json(url, token)
        batch = payload.get("items", [])
        items.extend(batch)
        if len(batch) < per_page:
            break
        time.sleep(sleep_seconds)

    return items


def fetch_comments(
    comments_url: str,
    token: str | None,
    max_comments: int,
    per_page: int,
    sleep_seconds: float,
) -> list[dict[str, Any]]:
    if max_comments <= 0:
        return []

    comments: list[dict[str, Any]] = []
    page = 1
    while len(comments) < max_comments:
        separator = "&" if "?" in comments_url else "?"
        url = f"{comments_url}{separator}per_page={min(per_page, max_comments)}&page={page}"
        try:
            batch = request_json(url, token)
        except GitHubApiError as exc:
            if exc.status == 403 and "rate limit" in exc.body.lower():
                print(f"warning: rate limited while fetching comments; keeping {len(comments)} comments", file=sys.stderr)
                break
            raise
        if not batch:
            break
        comments.extend(batch)
        if len(batch) < min(per_page, max_comments):
            break
        page += 1
        time.sleep(sleep_seconds)

    return comments[-max_comments:]


def compact_user(user: dict[str, Any] | None) -> str | None:
    if not user:
        return None
    return user.get("login")


def compact_issue(issue: dict[str, Any], keywords: list[str], comments: list[dict[str, Any]]) -> dict[str, Any]:
    title = issue.get("title") or ""
    matched_keywords = [keyword for keyword in keywords if keyword.lower() in title.lower()]
    return {
        "number": issue.get("number"),
        "title": title,
        "url": issue.get("html_url"),
        "api_url": issue.get("url"),
        "state": issue.get("state"),
        "author": compact_user(issue.get("user")),
        "created_at": issue.get("created_at"),
        "updated_at": issue.get("updated_at"),
        "closed_at": issue.get("closed_at"),
        "labels": [label.get("name") for label in issue.get("labels", [])],
        "comments_count": issue.get("comments", 0),
        "matched_keywords": matched_keywords,
        "body": issue.get("body") or "",
        "comments": [
            {
                "author": compact_user(comment.get("user")),
                "created_at": comment.get("created_at"),
                "updated_at": comment.get("updated_at"),
                "body": comment.get("body") or "",
                "url": comment.get("html_url"),
            }
            for comment in comments
        ],
    }


def main() -> int:
    args = parse_args()
    keywords = args.keywords or list(DEFAULT_KEYWORDS)
    keywords = [keyword.strip() for keyword in keywords if keyword.strip()]
    if not keywords:
        raise SystemExit("At least one keyword is required.")

    now = utc_now()
    since = now - dt.timedelta(hours=args.hours)
    report_date = now.astimezone(ZoneInfo(args.timezone)).date().isoformat()
    output = Path(args.output or f"data/{report_date}/issues.json")
    token = os.environ.get("GITHUB_TOKEN")

    by_number: dict[int, dict[str, Any]] = {}
    for keyword in keywords:
        for issue in search_issues(args.repo, keyword, since, token, args.per_page, args.sleep):
            if "pull_request" in issue:
                continue
            title = issue.get("title") or ""
            if not any(keyword.lower() in title.lower() for keyword in keywords):
                continue
            updated_at = parse_github_time(issue["updated_at"])
            if updated_at < since:
                continue
            by_number[issue["number"]] = issue
        time.sleep(args.sleep)

    compacted: list[dict[str, Any]] = []
    for issue in sorted(by_number.values(), key=lambda item: item["updated_at"], reverse=True):
        comments = fetch_comments(issue["comments_url"], token, args.max_comments, args.per_page, args.sleep)
        compacted.append(compact_issue(issue, keywords, comments))
        time.sleep(args.sleep)

    payload = {
        "metadata": {
            "repo": args.repo,
            "keywords": keywords,
            "generated_at": now.isoformat(),
            "since": since.isoformat(),
            "lookback_hours": args.hours,
            "timezone": args.timezone,
            "report_date": report_date,
            "issue_count": len(compacted),
        },
        "issues": compacted,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.print_output_path:
        print(output)
    else:
        print(f"Wrote {len(compacted)} issues to {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
