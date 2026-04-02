"""Helpers for extracting structured XML feedback from coqc stdout."""

from __future__ import annotations

import re
from html import unescape

XML_FRAGMENT_RE = re.compile(
    r"<(?P<tag>[A-Za-z_][\w:.-]*)>(?P<content>.*?)</(?P=tag)>",
    re.DOTALL,
)


def extract_xml_feedback(text: str) -> list[dict[str, str]]:
    """Return inline XML fragments like <goal>...</goal> in source order."""
    feedback: list[dict[str, str]] = []
    if not text:
        return feedback

    for match in XML_FRAGMENT_RE.finditer(text):
        tag = match.group("tag")
        content = unescape(match.group("content")).strip()
        feedback.append({"tag": tag, "content": content})
    return feedback


def format_xml_feedback(feedback: list[dict[str, str]]) -> str:
    """Render parsed feedback into a prompt-friendly xml-ish block."""
    if not feedback:
        return ""
    return "\n\n".join(
        f"<{entry['tag']}>\n{entry['content']}\n</{entry['tag']}>"
        for entry in feedback
    ).strip()
