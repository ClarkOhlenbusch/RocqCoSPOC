"""Text utilities shared across pipeline stages."""

import re
import sys
from typing import Optional


def strip_fences(text: str) -> str:
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


def truncate_for_error(text: str, limit: int = 1200) -> str:
    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit] + "\n...[truncated]..."


def preview_text(text: str, limit: int = 500) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return "(empty)"
    if len(cleaned) <= limit:
        return console_safe(cleaned)
    return console_safe(cleaned[:limit] + "... [truncated]")


def console_safe(text: str) -> str:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return str(text).encode(encoding, errors="replace").decode(encoding, errors="replace")


def split_goal_state(state_text: str) -> tuple[list[str], str]:
    lines = [line.strip() for line in state_text.splitlines() if line.strip()]
    if not lines:
        return [], ""
    try:
        separator_idx = lines.index("============================")
    except ValueError:
        return [], "\n".join(lines)
    hypotheses = lines[1:separator_idx]
    goal = "\n".join(lines[separator_idx + 1:]).strip()
    return hypotheses, goal


def focused_proof_state(state_text: str) -> str:
    if not state_text.strip():
        return ""
    kept: list[str] = []
    for line in state_text.splitlines():
        if (
            "This subproof is complete" in line
            or "Focus next goal with bullet" in line
            or "No more goals, but there are some goals you gave up:" in line
            or "No more goals." in line
            or re.match(r"^\s*goal\s+\d+\s+is:\s*$", line, re.IGNORECASE)
        ):
            break
        kept.append(line)
    return "\n".join(kept).strip()


_TERMINAL_TACTIC_RE = re.compile(
    r"^(?:lia|nia|ring|reflexivity|easy|trivial|assumption|auto)\.\s*$"
    r"|^exact\b.*\.\s*$",
    re.IGNORECASE,
)


def trim_terminal_tactic_suffix(tactics: str) -> str:
    lines = [line.rstrip() for line in tactics.splitlines() if line.strip()]
    for idx, line in enumerate(lines):
        if _TERMINAL_TACTIC_RE.match(line.strip()):
            return "\n".join(lines[:idx + 1])
    return "\n".join(lines)
