"""Load prompt templates and substitute placeholders."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = REPO_ROOT / "prompts"

PROMPT_FILES = {
    "rewrite": "01_rewrite.txt",
    "skeleton": "02a_skeleton.txt",
    "fill_goal": "02b_fill_goal.txt",
}

TACTICS_REF_PATH = PROMPTS_DIR / "tactics_reference.md"
TRANSLATION_GUIDE_PATH = REPO_ROOT / "angelito-to-rocq.md"


def _load_raw(name: str) -> str:
    fname = PROMPT_FILES.get(name)
    if not fname:
        raise ValueError(f"Unknown prompt name: {name}")
    path = PROMPTS_DIR / fname
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


def _load_tactics_reference(*, custom_tactics_enabled: bool, lia_available: bool) -> str:
    if TACTICS_REF_PATH.exists():
        reference = TACTICS_REF_PATH.read_text(encoding="utf-8").strip()
    else:
        reference = "(no tactics reference available)"

    if custom_tactics_enabled:
        availability_note = (
            "Custom Angelito Ltac1 tactics are available because the current proof source imports "
            "an Angelito module together with `Import Angelito.Ltac1.`."
        )
    else:
        availability_note = (
            "Custom Angelito tactics are part of the project design vocabulary, but the current proof "
            "source does not import an Angelito module together with `Import Angelito.Ltac1.`. "
            "Do not emit `simplify lhs/rhs`, `assert_goal`, or `pick` unless those imports are present "
            "in the current proof source."
        )

    if lia_available:
        lia_note = "The current proof source imports `Lia`, so the `lia.` tactic is available."
    else:
        lia_note = (
            "The current proof source does not import `Lia`. Do not emit `lia.` unless the imports "
            "visible in the formal statement explicitly make it available."
        )

    return f"{availability_note}\n\n{lia_note}\n\n{reference}".strip()


def _load_translation_guide() -> str:
    if TRANSLATION_GUIDE_PATH.exists():
        return TRANSLATION_GUIDE_PATH.read_text(encoding="utf-8").strip()
    return "(no Angelito-to-Rocq translation guide available)"


def _custom_tactics_enabled(*sources: str) -> bool:
    require_markers = (
        "Require Import Angelito.",
        "Require Import RocqCoSPOC.Angelito.",
        "From RocqCoSPOC Require Import Angelito.",
    )
    saw_require = any(
        any(marker in source for marker in require_markers)
        for source in sources
        if source
    )
    saw_import = any("Import Angelito.Ltac1." in source for source in sources if source)
    return saw_require and saw_import


def _lia_available(*sources: str) -> bool:
    markers = (
        "Require Import Lia.",
        "From Coq Require Import Lia.",
        "Require Import Omega.",
    )
    return any(any(marker in source for marker in markers) for source in sources if source)


def fill(template: str, **kwargs) -> str:
    """Replace {key} with kwargs[key]; leave unknown placeholders as-is."""
    out = template
    for k, v in kwargs.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def get_prompt(name: str, **kwargs) -> str:
    template = _load_raw(name)
    return fill(template, **kwargs)


def get_rewrite(informal_proof: str, formal_statement: str, angelito_spec: str) -> str:
    return get_prompt(
        "rewrite",
        informal_proof=informal_proof,
        formal_statement=formal_statement,
        angelito_spec=angelito_spec,
    )


def get_skeleton(formal_statement: str, angelito_proof: str) -> str:
    custom_tactics_enabled = _custom_tactics_enabled(formal_statement, angelito_proof)
    lia_available = _lia_available(formal_statement, angelito_proof)
    return get_prompt(
        "skeleton",
        formal_statement=formal_statement,
        angelito_proof=angelito_proof,
        tactics_reference=_load_tactics_reference(
            custom_tactics_enabled=custom_tactics_enabled,
            lia_available=lia_available,
        ),
        translation_guide=_load_translation_guide(),
    )


def get_fill_goal(formal_statement: str, angelito_proof: str,
                  current_proof: str, current_goal_state: str = "", error_context: str = "",
                  structured_feedback: str = "") -> str:
    custom_tactics_enabled = _custom_tactics_enabled(formal_statement, current_proof)
    lia_available = _lia_available(formal_statement, current_proof)
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
        tactics_reference=_load_tactics_reference(
            custom_tactics_enabled=custom_tactics_enabled,
            lia_available=lia_available,
        ),
        translation_guide=_load_translation_guide(),
    )
