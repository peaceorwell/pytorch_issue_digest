#!/usr/bin/env python3
"""Create a smaller issue JSON for Codex analysis."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Input issues.json path.")
    parser.add_argument("output", help="Output compact JSON path.")
    parser.add_argument("--body-chars", type=int, default=1800)
    parser.add_argument("--comment-chars", type=int, default=700)
    parser.add_argument("--max-comments", type=int, default=3)
    return parser.parse_args()


def trim(value: str | None, limit: int) -> str:
    value = value or ""
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "\n...[truncated]"


def compact_issue(issue: dict[str, Any], body_chars: int, comment_chars: int, max_comments: int) -> dict[str, Any]:
    comments = issue.get("comments", [])[-max_comments:]
    return {
        "number": issue.get("number"),
        "title": issue.get("title"),
        "url": issue.get("url"),
        "state": issue.get("state"),
        "author": issue.get("author"),
        "created_at": issue.get("created_at"),
        "updated_at": issue.get("updated_at"),
        "labels": issue.get("labels", []),
        "matched_keywords": issue.get("matched_keywords", []),
        "comments_count": issue.get("comments_count", 0),
        "body_excerpt": trim(issue.get("body"), body_chars),
        "recent_comments": [
            {
                "author": comment.get("author"),
                "created_at": comment.get("created_at"),
                "body_excerpt": trim(comment.get("body"), comment_chars),
                "url": comment.get("url"),
            }
            for comment in comments
        ],
    }


def main() -> int:
    args = parse_args()
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    compacted = {
        "metadata": data.get("metadata", {}),
        "issues": [
            compact_issue(issue, args.body_chars, args.comment_chars, args.max_comments)
            for issue in data.get("issues", [])
        ],
    }
    Path(args.output).write_text(json.dumps(compacted, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
