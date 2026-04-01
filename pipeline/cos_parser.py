"""
Parse Chain of States (CoS) string from LLM output into a list of state strings.
Expects "State 0:", "State 1:", ... and "No Goals" with optional leading explanation text.
"""

import re
from typing import List


def _strip_markdown_fence(text: str) -> str:
    """Remove a surrounding markdown fence if present."""
    t = text.strip()
    if not t.startswith("```"):
        return t
    lines = t.splitlines()
    if lines and lines[0].lstrip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def parse_chain_of_states(text: str) -> List[str]:
    """
    Parse CoS response into ordered list of state blocks.
    Each element is a string like "State 0:\na : R\n..." or "No Goals".
    """
    text = _strip_markdown_fence(text).replace("\r\n", "\n").strip()
    if not text:
        return []

    state_header_re = re.compile(
        r"^\s*(?:[#>*-]\s*)*\*{0,2}\s*State\s+(\d+)\s*\*{0,2}\s*[:\-]?\s*$",
        re.IGNORECASE,
    )
    no_goals_re = re.compile(
        r"^\s*(?:[#>*-]\s*)*\*{0,2}\s*No\s+Goals?\s*[\.\!\*]*\s*$",
        re.IGNORECASE,
    )

    lines = text.split("\n")
    states: List[str] = []
    current_lines: List[str] = []
    current_label = None

    def flush_current():
        nonlocal current_lines, current_label
        if current_label is None:
            current_lines = []
            return
        body = "\n".join(current_lines).strip()
        if current_label == "No Goals":
            states.append("No Goals")
        else:
            label = f"State {current_label}:"
            states.append(f"{label}\n{body}".strip())
        current_lines = []

    for line in lines:
        if no_goals_re.match(line):
            flush_current()
            current_label = "No Goals"
            flush_current()
            current_label = None
            continue

        m = state_header_re.match(line)
        if m:
            flush_current()
            current_label = m.group(1)
            continue

        if current_label is not None:
            current_lines.append(line)

    flush_current()

    # Fallback: some models return only a single unlabeled state block.
    if not states and "============================" in text:
        states.append(f"State 0:\n{text}".strip())

    best = _select_best_chain(states)
    cleaned = [_clean_state_block(s) for s in best]
    return _dedupe_consecutive_states(cleaned)


def _select_best_chain(states: List[str]) -> List[str]:
    """
    Choose the longest contiguous State 0..N chain.
    This filters out intermediate scratch chains from verbose model output.
    """
    if not states:
        return states

    indexed: List[tuple[int, str]] = []
    for s in states:
        m = re.match(r"^State\s+(\d+)\s*:", s, re.IGNORECASE)
        if m:
            indexed.append((int(m.group(1)), s))
        elif s.strip().lower() == "no goals":
            indexed.append((-1, "No Goals"))

    if not indexed:
        return states

    runs: List[tuple[List[str], bool]] = []
    for i, (idx, value) in enumerate(indexed):
        if idx != 0:
            continue
        current: List[str] = []
        expected = 0
        ended_with_no_goals = False
        for j in range(i, len(indexed)):
            jidx, jval = indexed[j]
            if jidx == -1:
                if current:
                    current.append("No Goals")
                    ended_with_no_goals = True
                break
            if jidx == expected:
                current.append(jval)
                expected += 1
                continue
            if jidx < expected:
                continue
            break
        if current:
            runs.append((current, ended_with_no_goals))

    if not runs:
        return states

    # Prefer the latest completed chain (State 0..N followed by No Goals).
    for run, completed in reversed(runs):
        if completed:
            return run
    # Otherwise prefer the latest run.
    return runs[-1][0]


def _clean_state_block(state: str) -> str:
    if state.strip().lower() == "no goals":
        return "No Goals"

    lines = state.replace("\r\n", "\n").split("\n")
    if not lines:
        return state.strip()

    header = lines[0].strip()
    body = []
    for line in lines[1:]:
        stripped = line.strip()
        # Drop model-added comments/explanations from state bodies.
        if stripped.startswith("(*") and stripped.endswith("*)"):
            continue
        body.append(line.rstrip())

    # Keep internal structure but trim trailing blank lines.
    while body and not body[-1].strip():
        body.pop()
    return "\n".join([header] + body).strip()


def _dedupe_consecutive_states(states: List[str]) -> List[str]:
    if not states:
        return states
    out = [states[0]]
    for s in states[1:]:
        if normalize_state(s) != normalize_state(out[-1]):
            out.append(s)
    return out


def normalize_state(s: str) -> str:
    """Normalize whitespace for state comparison (e.g. single newlines, strip)."""
    if s.strip() == "":
        return ""
    lines = [line.strip() for line in s.strip().splitlines() if line.strip()]
    return "\n".join(lines)


def states_match(expected: str, actual: str) -> bool:
    """Compare two state strings after normalizing."""
    return normalize_state(expected) == normalize_state(actual)
