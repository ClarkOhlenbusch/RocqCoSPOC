"""Extract and validate Coq tactic blocks from model responses."""

import re
from typing import Optional

TACTIC_START_RE = re.compile(
    r"^(?:"
    r"intro|intros|induction|destruct|simpl|cbn|rewrite|apply|eapply|exact|"
    r"reflexivity|assumption|auto|lia|nia|ring|nlinarith|easy|trivial|"
    r"subst|constructor|unfold|change|replace|assert|pose|specialize|"
    r"remember|clear|rename|exists|split|left|right|symmetry|"
    r"transitivity|inversion|discriminate|congruence|firstorder|now"
    r")\b",
    re.IGNORECASE,
)


def _normalize_candidate_line(raw: str) -> str:
    line = raw.strip().strip("`").strip()
    # Allow bullet-form scripts: "- intro x." / "+ split."
    line = re.sub(r"^[-+*]\s+", "", line)
    low = line.lower().rstrip(".")
    if low == "intron":
        line = "intro n."
    return line


def _looks_like_tactic_line(line: str) -> bool:
    if line in {"{", "}"}:
        return True
    if re.match(r"^(state\s+\d+|no\s+goals?)\b", line, re.IGNORECASE):
        return False
    # reject common prose patterns even when they end in periods
    if re.match(r"^(analysis|explanation|note)\s*:", line, re.IGNORECASE):
        return False
    # Accept tactic lines with or without trailing period; we normalize later.
    candidate = line[:-1] if line.endswith(".") else line
    if not candidate:
        return False
    if "," in candidate[:12]:
        return False
    return bool(TACTIC_START_RE.match(candidate))


def _extract_candidate_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = _normalize_candidate_line(raw)
        if not line:
            continue
        if line.startswith("```"):
            continue
        if not _looks_like_tactic_line(line):
            return []
        if line not in {"{", "}"} and not line.endswith("."):
            line = f"{line}."
        lines.append(line)
    return lines


def extract_coq_block(text: str) -> Optional[str]:
    """
    Extract the first ```coq ... ``` or ``` ... ``` block from text.
    Returns the inner content, stripped. Returns None if no block found.
    """
    # Prefer ```coq ... ```
    m = re.search(r"```(?:coq)?\s*\n(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # Fallback: any ``` ... ``` and hope it's Coq
    m = re.search(r"```\s*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return None


def extract_tactics(text: str) -> Optional[str]:
    """
    Extract tactic sequence from model output. Strips "Analysis: ..." prefix if present.
    Returns the Coq tactic block content or None.
    """
    block = extract_coq_block(text)
    candidate = block if block is not None else text

    # Remove common leading analysis line from ETR-like outputs.
    if candidate.lstrip().lower().startswith("analysis:"):
        idx = candidate.find("\n")
        if idx != -1:
            candidate = candidate[idx + 1 :].strip()

    lines = _extract_candidate_lines(candidate)
    if not lines:
        return None
    return "\n".join(lines).strip()
