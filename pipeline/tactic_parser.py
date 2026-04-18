"""Extract and validate Coq tactic blocks from model responses."""

import re
from typing import Optional

TACTIC_START_RE = re.compile(
    r"^(?:"
    r"intro|intros|assume|induction|destruct|simpl|simplify|cbn|cbv|compute|vm_compute|"
    r"native_compute|lazy|rewrite|apply|eapply|exact|"
    r"reflexivity|assumption|auto|lia|nia|lra|nra|nlra|ring|ring_simplify|field|field_simplify|nlinarith|easy|trivial|"
    r"subst|constructor|unfold|change|replace|assert|pose|specialize|"
    r"remember|clear|rename|exists|split|left|right|symmetry|"
    r"assert_goal|pick|"
    r"transitivity|inversion|discriminate|congruence|firstorder|now|admit|fail"
    r")\b",
    re.IGNORECASE,
)
INLINE_TACTIC_SPLIT_RE = re.compile(
    r"(?<=\.)\s*(?=(?:[-+*]\s+)?(?:"
    r"intro|intros|assume|induction|destruct|simpl|simplify|cbn|cbv|compute|vm_compute|"
    r"native_compute|lazy|rewrite|apply|eapply|exact|"
    r"reflexivity|assumption|auto|lia|nia|lra|nra|nlra|ring|ring_simplify|field|field_simplify|nlinarith|easy|trivial|"
    r"subst|constructor|unfold|change|replace|assert|pose|specialize|"
    r"remember|clear|rename|exists|split|left|right|symmetry|"
    r"assert_goal|pick|transitivity|inversion|discriminate|congruence|firstorder|now|admit|fail|[{}]|\d+\s*:|all\s*:))",
    re.IGNORECASE,
)


_BULLET_PREFIX_RE = re.compile(r"^(?P<bullet>[-+*]\s+)(?P<body>.*)$")


def _normalize_candidate_line(raw: str, *, preserve_bullets: bool = False) -> str:
    line = raw.strip().strip("`").strip()
    bullet = ""
    if preserve_bullets:
        match = _BULLET_PREFIX_RE.match(line)
        if match:
            bullet = match.group("bullet")
            line = match.group("body").strip()
    else:
        # Allow bullet-form scripts: "- intro x." / "+ split."
        line = re.sub(r"^[-+*]\s+", "", line)
    low = line.lower().rstrip(".")
    if low == "intron":
        line = "intro n."
    return f"{bullet}{line}" if bullet else line


def _looks_like_tactic_line(line: str) -> bool:
    if line in {"{", "}"}:
        return True
    # Reject unreasonably long lines — no valid single tactic is this long
    if len(line) > 500:
        return False
    candidate_line = re.sub(r"^[-+*]\s+", "", line)
    selector_match = re.match(r"^(?P<selector>(?:\d+|all))\s*:\s*(?P<body>.*)$", candidate_line, re.IGNORECASE)
    if selector_match:
        selector_body = selector_match.group("body").strip()
        if not selector_body:
            return False
        candidate_line = selector_body
    if re.match(r"^(state\s+\d+|no\s+goals?)\b", candidate_line, re.IGNORECASE):
        return False
    # reject common prose patterns even when they end in periods
    if re.match(r"^(analysis|explanation|note)\s*:", candidate_line, re.IGNORECASE):
        return False
    # Accept tactic lines with or without trailing period; we normalize later.
    candidate = candidate_line[:-1] if candidate_line.endswith(".") else candidate_line
    if not candidate:
        return False
    if "..." in candidate_line:
        return False
    if re.search(r"\.\s+[A-Za-z_]", candidate_line):
        return False
    # Reject degenerate repetition (e.g., "rewrite rewrite rewrite...")
    words = candidate.split()
    if len(words) > 3 and len(set(words)) == 1:
        return False
    return bool(TACTIC_START_RE.match(candidate))


def _extract_candidate_lines(text: str, *, preserve_bullets: bool = False) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        expanded = raw.replace(". {", ".\n{").replace("{ ", "{\n").replace(" }", "\n}")
        parts = expanded.splitlines()
        queue = parts if parts else [raw]
        for part in queue:
            for chunk in INLINE_TACTIC_SPLIT_RE.split(part):
                line = _normalize_candidate_line(chunk, preserve_bullets=preserve_bullets)
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


def extract_tactics(text: str, *, preserve_bullets: bool = False) -> Optional[str]:
    """
    Extract tactic sequence from model output. Strips "Analysis: ..." prefix if present.
    Returns the Coq tactic block content or None.
    """
    block = extract_coq_block(text)
    candidate = block if block is not None else text

    # Strip a common leading analysis line when the model ignored the "code only" instruction.
    if candidate.lstrip().lower().startswith("analysis:"):
        idx = candidate.find("\n")
        if idx != -1:
            candidate = candidate[idx + 1 :].strip()

    lines = _extract_candidate_lines(candidate, preserve_bullets=preserve_bullets)
    if not lines:
        return None
    return "\n".join(lines).strip()
