"""Error parsing and structured feedback."""

import re


def parse_structured_error(stderr: str, stdout: str) -> str:
    """Extract useful error info from coqc output."""
    raw = (stderr or stdout).strip()
    if not raw:
        return ""
    lines = raw.splitlines()
    error_lines = []
    in_error = False
    for i, line in enumerate(lines):
        if "Error:" in line or "error:" in line.lower():
            start = max(0, i - 2)
            error_lines.extend(lines[start:i])
            in_error = True
        if in_error:
            error_lines.append(line)
            if line.strip() == "" or "Proof check failed" in line:
                error_lines.append("---")
                in_error = False
    if in_error:
        error_lines.append("---")
    if error_lines:
        return "\n".join(error_lines)
    return raw


def build_structured_feedback_context(stdout: str, stderr: str) -> tuple[list[dict[str, str]], str]:
    from pipeline.compiler_feedback import extract_compiler_feedback, format_compiler_feedback

    feedback = extract_compiler_feedback(stdout or "", stderr or "")
    return feedback, format_compiler_feedback(feedback)
