"""
Load prompts from prompts/ and substitute placeholders.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = REPO_ROOT / "prompts"

PROMPT_FILES = {
    "rewrite": "01_rewrite.txt",
    "skeleton": "02a_skeleton.txt",
    "fill_goal": "02b_fill_goal.txt",
    # legacy
    "direct_prove": "02_direct_prove.txt",
    "tactic": "03_tactic_generator.txt",
    "etr": "04_etr.txt",
    "esr": "05_esr.txt",
}

TACTICS_REF_PATH = PROMPTS_DIR / "tactics_reference.md"


def _load_raw(name: str) -> str:
    fname = PROMPT_FILES.get(name)
    if not fname:
        raise ValueError(f"Unknown prompt name: {name}")
    path = PROMPTS_DIR / fname
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


def _load_tactics_reference() -> str:
    if TACTICS_REF_PATH.exists():
        return TACTICS_REF_PATH.read_text(encoding="utf-8").strip()
    return "(no tactics reference available)"


def fill(template: str, **kwargs) -> str:
    """Replace {key} with kwargs[key]; leave unknown placeholders as-is."""
    out = template
    for k, v in kwargs.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def get_prompt(name: str, **kwargs) -> str:
    template = _load_raw(name)
    return fill(template, **kwargs)


def get_rewrite(informal_proof: str, angelito_spec: str) -> str:
    return get_prompt(
        "rewrite",
        informal_proof=informal_proof,
        angelito_spec=angelito_spec,
    )


def get_skeleton(formal_statement: str, angelito_proof: str) -> str:
    return get_prompt(
        "skeleton",
        formal_statement=formal_statement,
        angelito_proof=angelito_proof,
        tactics_reference=_load_tactics_reference(),
    )


def get_fill_goal(formal_statement: str, angelito_proof: str,
                  current_proof: str, current_goal_state: str = "", error_context: str = "",
                  structured_feedback: str = "") -> str:
    structured_feedback_context = ""
    if structured_feedback.strip():
        structured_feedback_context = (
            "**Structured Compiler Feedback (preferred over raw Coq errors when present):**\n"
            "```xml\n"
            f"{structured_feedback.strip()}\n"
            "```\n"
        )
    return get_prompt(
        "fill_goal",
        formal_statement=formal_statement,
        angelito_proof=angelito_proof,
        current_proof=current_proof,
        current_goal_state=current_goal_state,
        error_context=error_context,
        structured_feedback_context=structured_feedback_context,
        tactics_reference=_load_tactics_reference(),
    )


# -- legacy helpers (kept for manual workflows) --

def get_direct_prove(formal_statement: str, coq_friendly_proof: str, error_context: str = "") -> str:
    return get_prompt(
        "direct_prove",
        formal_statement=formal_statement,
        coq_friendly_proof=coq_friendly_proof,
        error_context=error_context,
    )


def get_tactic(state_p: str, state_n: str, coq_friendly_proof: str) -> str:
    return get_prompt(
        "tactic",
        state_p=state_p,
        state_n=state_n,
        coq_friendly_proof=coq_friendly_proof,
    )


def get_etr(state_p: str, state_n: str, failed_tactics: str,
            error_message: str, coq_friendly_proof: str) -> str:
    return get_prompt(
        "etr",
        state_p=state_p,
        state_n=state_n,
        failed_tactics=failed_tactics,
        error_message=error_message,
        coq_friendly_proof=coq_friendly_proof,
    )


def get_esr(state_a: str, state_b: str, state_c: str, coq_friendly_proof: str) -> str:
    return get_prompt(
        "esr",
        state_a=state_a,
        state_b=state_b,
        state_c=state_c,
        coq_friendly_proof=coq_friendly_proof,
    )
