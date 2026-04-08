"""Helpers for extracting structured tactic feedback from compiler output."""

from __future__ import annotations

import re
from html import unescape

XML_FRAGMENT_RE = re.compile(
    r"<(?P<tag>[A-Za-z_][\w:.-]*)>(?P<content>.*?)</(?P=tag)>",
    re.DOTALL,
)
LTAC2_FAIL_WITH_RE = re.compile(
    r"API\.Fail_with message:\((?P<message>.*?)(?=\)\r?\n(?:\r?\n|File |C:\\|At |$))",
    re.DOTALL,
)

ASSERT_GOAL_RE = re.compile(
    r"Expected goal:\s*\n(?P<expected>.*?)(?:\r?\n)?Got:\s*\n(?P<got>.*)$",
    re.DOTALL,
)
ASSERT_LHS_RE = re.compile(
    r"assert_lhs:\s*Expected LHS:\s*\n(?P<expected>.*?)(?:\r?\n)?but got:\s*\n(?P<got>.*)$",
    re.DOTALL | re.IGNORECASE,
)
ASSERT_RHS_RE = re.compile(
    r"assert_rhs:\s*Expected RHS:\s*\n(?P<expected>.*?)(?:\r?\n)?but got:\s*\n(?P<got>.*)$",
    re.DOTALL | re.IGNORECASE,
)
PICK_RE = re.compile(
    r"pick\s*\((?P<binder>.*?)\)\s*\nUnexpec(?:t)?ed type got:\s*\n(?P<got>.*)$",
    re.DOTALL | re.IGNORECASE,
)
SIMPLIFY_EXPECTED_EQUATION_RE = re.compile(
    r"ltac1_simplify_(?P<side>lhs|rhs)(?:_by)?: expected equation",
    re.IGNORECASE,
)


def extract_compiler_feedback(stdout: str, stderr: str) -> list[dict[str, str]]:
    """Return structured feedback extracted from stderr first, then XML stdout fallback."""
    feedback = extract_tactic_feedback(stderr or "")
    if feedback:
        return feedback
    return extract_xml_feedback(stdout or "")


def extract_tactic_feedback(text: str) -> list[dict[str, str]]:
    feedback: list[dict[str, str]] = []
    if not text:
        return feedback

    seen: set[tuple[tuple[str, str], ...]] = set()
    for candidate in _feedback_candidates(text):
        for match in ASSERT_GOAL_RE.finditer(candidate):
            _append_unique(
                feedback,
                seen,
                {
                    "tag": "assert_goal",
                    "expected": _clean(match.group("expected")),
                    "got": _clean(match.group("got")),
                },
            )

        for match in ASSERT_LHS_RE.finditer(candidate):
            _append_unique(
                feedback,
                seen,
                {
                    "tag": "assert_lhs",
                    "expected": _clean(match.group("expected")),
                    "got": _clean(match.group("got")),
                },
            )

        for match in ASSERT_RHS_RE.finditer(candidate):
            _append_unique(
                feedback,
                seen,
                {
                    "tag": "assert_rhs",
                    "expected": _clean(match.group("expected")),
                    "got": _clean(match.group("got")),
                },
            )

        for match in PICK_RE.finditer(candidate):
            _append_unique(
                feedback,
                seen,
                {
                    "tag": "pick",
                    "binder": _clean(match.group("binder")),
                    "got": _clean(match.group("got")),
                },
            )

        for match in SIMPLIFY_EXPECTED_EQUATION_RE.finditer(candidate):
            side = match.group("side").lower()
            _append_unique(
                feedback,
                seen,
                {
                    "tag": f"simplify_{side}_expected_equation",
                    "content": (
                        f"`simplify {side}` requires a parenthesized equality argument "
                        "of the form `(a = b)`."
                    ),
                },
            )

    return feedback


def extract_xml_feedback(text: str) -> list[dict[str, str]]:
    feedback: list[dict[str, str]] = []
    if not text:
        return feedback

    for match in XML_FRAGMENT_RE.finditer(text):
        feedback.append(
            {
                "tag": match.group("tag"),
                "content": _clean(match.group("content")),
            }
        )
    return feedback


def format_compiler_feedback(feedback: list[dict[str, str]]) -> str:
    if not feedback:
        return ""

    blocks: list[str] = []
    for entry in feedback:
        tag = entry["tag"]
        if tag in {"assert_goal", "assert_lhs", "assert_rhs"}:
            blocks.append(
                f"<{tag}>\nexpected:\n{entry['expected']}\n\ngot:\n{entry['got']}\n</{tag}>"
            )
        elif tag == "pick":
            blocks.append(
                f"<pick>\nbinder:\n{entry['binder']}\n\ngot:\n{entry['got']}\n</pick>"
            )
        elif tag in {"simplify_lhs_expected_equation", "simplify_rhs_expected_equation"}:
            blocks.append(f"<{tag}>\n{entry.get('content', '')}\n</{tag}>")
        else:
            blocks.append(f"<{tag}>\n{entry.get('content', '')}\n</{tag}>")
    return "\n\n".join(blocks).strip()


def _clean(text: str) -> str:
    cleaned = unescape(text).strip()
    cleaned = re.sub(r"\r\n?", "\n", cleaned)
    return cleaned


def _feedback_candidates(text: str) -> list[str]:
    extracted = [match.group("message").strip() for match in LTAC2_FAIL_WITH_RE.finditer(text)]
    candidates = [] if extracted else [text]
    for raw_message in extracted:
        candidates.append(raw_message)
        candidates.append(raw_message.replace("\\n", "\n"))
    if not extracted:
        normalized = text.replace("\\n", "\n")
        if normalized != text:
            candidates.append(normalized)
    return candidates


def _append_unique(
    feedback: list[dict[str, str]],
    seen: set[tuple[tuple[str, str], ...]],
    entry: dict[str, str],
) -> None:
    key = tuple(sorted(entry.items()))
    if key in seen:
        return
    seen.add(key)
    feedback.append(entry)
