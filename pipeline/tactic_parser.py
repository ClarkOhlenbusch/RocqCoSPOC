"""
Extract Coq tactic block from LLM response (markdown code fence ```coq ... ```).
"""

import re
from typing import Optional


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
    if block is None:
        # Fallback for models that return plain-text tactics without fences.
        lines = []
        for raw in text.splitlines():
            line = raw.strip().strip("`").strip()
            if not line:
                continue
            line = re.sub(r"^[-*]\s+", "", line)
            if not line.endswith("."):
                continue
            if re.match(r"^(state\s+\d+|no\s+goals?)\b", line, re.IGNORECASE):
                continue
            if re.search(
                r"\b("
                r"intro|intros|induction|destruct|simpl|cbn|rewrite|apply|exact|"
                r"reflexivity|assumption|auto|lia|ring|nlinarith|easy|trivial|"
                r"subst|constructor|unfold|change|replace|assert|pose|specialize|"
                r"remember|clear|rename|exists|split|left|right|symmetry|"
                r"transitivity|inversion|discriminate|congruence"
                r")\b",
                line,
                re.IGNORECASE,
            ):
                lines.append(line)
        if lines:
            return "\n".join(lines).strip()
        return None
    # Remove common leading analysis line
    if block.lower().startswith("analysis:"):
        idx = block.find("\n")
        if idx != -1:
            block = block[idx + 1 :].strip()
    return block
