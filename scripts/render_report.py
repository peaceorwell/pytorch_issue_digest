#!/usr/bin/env python3
"""Render a compact Chinese Markdown report from fetched issue JSON."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


NOISY_LABELS = {
    "bot-triaged",
    "bot-mislabeled",
    "triaged",
    "triage review",
    "oncall: pt2",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Input issues.json path.")
    parser.add_argument("output", help="Output Markdown path.")
    return parser.parse_args()


def important_labels(labels: list[str], limit: int = 5) -> list[str]:
    kept = [label for label in labels if label not in NOISY_LABELS and not label.startswith("oncall:")]
    return kept[:limit] if kept else labels[:limit]


def impact(issue: dict[str, Any]) -> tuple[str, str]:
    labels = set(issue.get("labels", []))
    title = (issue.get("title") or "").lower()
    if issue.get("state") == "closed":
        return "low", "issue 已关闭，暂不作为今日阻塞项"
    if "high priority" in labels or "module: correctness (silent)" in labels:
        return "high", "包含 high priority 或 silent correctness 信号"
    if "module: crash" in labels or "illegal memory access" in title or "wrong results" in title:
        return "high", "涉及 crash、非法内存访问或错误结果"
    if "feature" in labels or title.startswith("[rfc]"):
        return "low", "偏设计/优化提案，非即时故障"
    return "medium", "需要维护者确认或复现，但风险范围相对可控"


def area(issue: dict[str, Any]) -> str:
    labels = set(issue.get("labels", []))
    title = (issue.get("title") or "").lower()
    if "module: dynamo" in labels or "dynamo" in title:
        return "Dynamo"
    if "module: inductor" in labels or "inductor" in title:
        return "Inductor"
    if "module: aotdispatch" in labels or "functionalization" in labels:
        return "AOTAutograd"
    if "module: cuda graphs" in labels:
        return "CUDA graphs"
    if "triton" in title or "module: user triton" in labels:
        return "Triton"
    if "compile" in title:
        return "torch.compile"
    return "unclear"


def issue_type(issue: dict[str, Any]) -> str:
    labels = set(issue.get("labels", []))
    title = (issue.get("title") or "").lower()
    if "feature" in labels or title.startswith("[rfc]") or "support " in title:
        return "feature request"
    if "module: performance" in labels or "performance" in title:
        return "performance"
    if "module: regression" in labels:
        return "regression"
    if "wrong result" in title or "different result" in title or "correctness" in " ".join(labels):
        return "bug"
    if "crash" in title or "fails" in title or "error" in title:
        return "bug"
    return "bug"


def summarize(issue: dict[str, Any]) -> str:
    title = issue.get("title") or ""
    if "wrong" in title.lower() or "different result" in title.lower():
        return "编译路径与 eager 行为不一致，存在正确性风险。"
    if "crash" in title.lower() or "illegal memory access" in title.lower() or "fails" in title.lower():
        return "编译或运行阶段失败，需要定位具体 lowering/codegen 路径。"
    if title.lower().startswith("[rfc]") or "filter extremely bad" in title.lower():
        return "这是 Inductor/Triton 侧的优化或设计讨论。"
    if "support" in title.lower() or "doesn't support" in title.lower():
        return "这是 torch.compile 兼容性或功能覆盖缺口。"
    return "该 issue 与 PyTorch compiler 栈相关，需要结合复现和标签继续分流。"


def signal(issue: dict[str, Any]) -> str:
    body = issue.get("body") or ""
    comments = issue.get("comments") or []
    parts: list[str] = []
    if "reproducer" in body.lower() or "minimal" in body.lower():
        parts.append("包含复现代码")
    if "traceback" in body.lower() or "error" in body.lower():
        parts.append("包含错误栈/错误信息")
    if "workaround" in body.lower() or "has workaround" in issue.get("labels", []):
        parts.append("已有 workaround 信号")
    if comments:
        last = comments[-1]
        author = last.get("author") or "unknown"
        parts.append(f"最新评论来自 {author}")
    return "；".join(parts) if parts else "信息较少，需维护者补充复现或上下文"


def line_escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def render(data: dict[str, Any]) -> str:
    metadata = data["metadata"]
    issues = data["issues"]
    report_date = metadata["report_date"]
    open_count = sum(1 for issue in issues if issue["state"] == "open")
    closed_count = sum(1 for issue in issues if issue["state"] == "closed")
    keyword_counts = Counter(keyword for issue in issues for keyword in issue.get("matched_keywords", []))
    impacts = {issue["number"]: impact(issue) for issue in issues}
    high_issues = [issue for issue in issues if impacts[issue["number"]][0] == "high"]
    watchlist = high_issues[:5]

    lines: list[str] = [
        f"# PyTorch Compiler Issue Digest - {report_date}",
        "",
        "## 今日概览",
        "",
        f"- 本次共匹配 {len(issues)} 个 issue，其中 open {open_count} 个、closed {closed_count} 个。",
        f"- 今日主要风险集中在 silent correctness、Inductor/Triton crash、Dynamo tracing/兼容性缺口。",
        f"- 关键词分布：compile {keyword_counts['compile']} 个，inductor {keyword_counts['inductor']} 个，dynamo {keyword_counts['dynamo']} 个。",
        f"- 高优先级关注项 {len(high_issues)} 个，建议优先处理仍处于 open 状态且涉及错误结果、crash 或非法内存访问的 issue。",
        "",
        "## 重点关注",
        "",
    ]

    if not watchlist:
        lines.append("- 今天没有明显 high priority 关注项。")
    for issue in watchlist:
        level, reason = impacts[issue["number"]]
        lines.extend(
            [
                f"- [#{issue['number']} {issue['title']}]({issue['url']})",
                f"  - 关注原因: {reason}。",
                f"  - 建议动作: 优先复现并确认 owner；若已有修复线索，补充回归测试后关闭或降级。",
            ]
        )

    lines.extend(["", "## Issue 分析", ""])

    for issue in issues:
        level, reason = impacts[issue["number"]]
        labels = ", ".join(important_labels(issue.get("labels", []))) or "无"
        keywords = "/".join(issue.get("matched_keywords", []))
        lines.extend(
            [
                f"### #{issue['number']} {issue['title']}",
                "",
                f"- 链接: {issue['url']}",
                f"- 状态: {issue['state']}; 更新时间: {issue['updated_at']}; 关键词: {keywords}",
                f"- 标签: {labels}",
                f"- 摘要: {summarize(issue)}",
                f"- 领域: {area(issue)}",
                f"- 类型: {issue_type(issue)}",
                f"- 影响: {level}，{reason}",
                f"- 关键信号: {signal(issue)}",
                "- 建议跟进: 根据复现稳定性和标签 owner 进行分流；正确性和 crash 类优先补测试。",
                "",
            ]
        )

    overlap_compile_inductor = sum(
        1 for issue in issues if {"compile", "inductor"}.issubset(set(issue.get("matched_keywords", [])))
    )
    overlap_compile_dynamo = sum(
        1 for issue in issues if {"compile", "dynamo"}.issubset(set(issue.get("matched_keywords", [])))
    )
    overlap_inductor_dynamo = sum(
        1 for issue in issues if {"inductor", "dynamo"}.issubset(set(issue.get("matched_keywords", [])))
    )

    lines.extend(
        [
            "## 关键词分布",
            "",
            f"- compile: {keyword_counts['compile']}",
            f"- inductor: {keyword_counts['inductor']}",
            f"- dynamo: {keyword_counts['dynamo']}",
            f"- compile + inductor overlap: {overlap_compile_inductor}",
            f"- compile + dynamo overlap: {overlap_compile_dynamo}",
            f"- inductor + dynamo overlap: {overlap_inductor_dynamo}",
            "",
            "## 原始 Issue 表",
            "",
            "| Issue | 标题 | 状态 | 更新时间 | 标签 | 关键词 | 影响 |",
            "|---|---|---|---|---|---|---|",
        ]
    )

    for issue in issues:
        level, _ = impacts[issue["number"]]
        labels = ", ".join(important_labels(issue.get("labels", []), limit=3))
        keywords = "/".join(issue.get("matched_keywords", []))
        lines.append(
            f"| [#{issue['number']}]({issue['url']}) | {line_escape(issue['title'])} | "
            f"{issue['state']} | {issue['updated_at']} | {line_escape(labels)} | {keywords} | {level} |"
        )

    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    Path(args.output).write_text(render(data), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
