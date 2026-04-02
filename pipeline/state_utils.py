"""Utility helpers for comparing proof-state text."""


def normalize_state(state: str) -> str:
    """Normalize whitespace for proof-state comparison."""
    if state.strip() == "":
        return ""
    lines = [line.strip() for line in state.strip().splitlines() if line.strip()]
    return "\n".join(lines)


def states_match(expected: str, actual: str) -> bool:
    """Compare two proof states after normalizing whitespace."""
    return normalize_state(expected) == normalize_state(actual)
