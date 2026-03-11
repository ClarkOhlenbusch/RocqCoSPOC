"""
Load prompts from prompts/ and substitute placeholders.
Placeholders: {informal_proof}, {coq_formal_statement}, {coq_friendly_proof},
{state_p}, {state_n}, {failed_tactics}, {error_message}, {state_a}, {state_b}, {state_c}.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = REPO_ROOT / "prompts"

PROMPT_FILES = {
    "rewrite": "01_rewrite.txt",
    "cos": "02_chain_of_states.txt",
    "tactic": "03_tactic_generator.txt",
    "etr": "04_etr.txt",
    "esr": "05_esr.txt",
}


def _load_raw(name: str) -> str:
    fname = PROMPT_FILES.get(name)
    if not fname:
        raise ValueError(f"Unknown prompt name: {name}")
    path = PROMPTS_DIR / fname
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


def fill(template: str, **kwargs) -> str:
    """Replace {key} with kwargs[key]; leave unknown placeholders as-is."""
    out = template
    for k, v in kwargs.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def get_prompt(name: str, **kwargs) -> str:
    """Load prompt by name and substitute placeholders. Extra kwargs are ignored for missing placeholders."""
    template = _load_raw(name)
    return fill(template, **kwargs)


def get_rewrite(informal_proof: str) -> str:
    return get_prompt("rewrite", informal_proof=informal_proof)


def get_cos(coq_formal_statement: str, coq_friendly_proof: str) -> str:
    return get_prompt(
        "cos",
        coq_formal_statement=coq_formal_statement,
        coq_friendly_proof=coq_friendly_proof,
    )


def get_tactic(state_p: str, state_n: str) -> str:
    return get_prompt("tactic", state_p=state_p, state_n=state_n)


def get_etr(
    state_p: str,
    state_n: str,
    failed_tactics: str,
    error_message: str,
) -> str:
    return get_prompt(
        "etr",
        state_p=state_p,
        state_n=state_n,
        failed_tactics=failed_tactics,
        error_message=error_message,
    )


def get_esr(state_a: str, state_b: str, state_c: str) -> str:
    return get_prompt(
        "esr",
        state_a=state_a,
        state_b=state_b,
        state_c=state_c,
    )
