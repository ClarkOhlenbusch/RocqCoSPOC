"""Load prompt templates and substitute placeholders."""

from pathlib import Path
import re

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


def _load_tactics_reference(
    *,
    custom_tactics_enabled: bool,
    lia_available: bool,
    lra_available: bool,
    field_available: bool,
) -> str:
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

    if lra_available:
        lra_note = "The current proof source imports `Lra` or `Psatz`, so the `lra.` tactic is available."
    else:
        lra_note = (
            "The current proof source does not import `Lra` or `Psatz`. Do not emit `lra.` unless the "
            "visible imports explicitly make it available."
        )

    if field_available:
        field_note = "The current proof source imports field support, so `field.` and `field_simplify` are available."
    else:
        field_note = (
            "The current proof source does not visibly import field support. Avoid `field.` and "
            "`field_simplify` unless the formal statement explicitly imports the required libraries."
        )

    return f"{availability_note}\n\n{lia_note}\n\n{lra_note}\n\n{field_note}\n\n{reference}".strip()


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


def _lra_available(*sources: str) -> bool:
    markers = (
        "Require Import Lra.",
        "From Coq Require Import Lra.",
        "Require Import Psatz.",
        "From Coq Require Import Psatz.",
        "Require Import Fourier.",
        "From Coq Require Import Fourier.",
    )
    return any(any(marker in source for marker in markers) for source in sources if source)


def _field_available(*sources: str) -> bool:
    markers = (
        "Require Import Field.",
        "From Coq Require Import Field.",
        "Require Import Ring.",
        "From Coq Require Import Ring.",
        "Require Import SetoidRing.Field.",
        "From Coq Require Import SetoidRing.Field.",
    )
    return any(any(marker in source for marker in markers) for source in sources if source)


def fill(template: str, **kwargs) -> str:
    """Replace {key} with kwargs[key]; leave unknown placeholders as-is."""
    out = template
    for k, v in kwargs.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def _goal_strategy_hint(current_goal_state: str, *, lia_available: bool) -> str:
    lines = [line.strip() for line in current_goal_state.splitlines() if line.strip()]
    if not lines:
        return ""

    try:
        separator_idx = lines.index("============================")
    except ValueError:
        separator_idx = -1
    hypotheses = lines[1:separator_idx] if separator_idx >= 0 else []
    goal_lines = lines[separator_idx + 1 :] if separator_idx >= 0 else lines
    goal_text = "\n".join(goal_lines).strip()
    goal_line = goal_lines[-1] if goal_lines else lines[-1]
    hints: list[str] = []

    if lia_available and re.search(r"(<=|>=|<|>|=)", goal_line):
        if not re.search(r"\b(forall|exists|match|fun)\b", goal_line):
            hints.append(
                "This looks like a single linear arithmetic goal and `Lia` is imported. "
                "Prefer returning exactly `lia.` as the whole answer unless structured compiler "
                "feedback proves `lia.` is insufficient."
            )

    if "IHn :" in current_goal_state and re.search(r"\bS\s+\w+\s*\+\s*0\s*=\s*S\s+\w+\b", goal_line):
        hints.append(
            "This is the standard inductive `n + 0 = n` step. Prefer `simpl.` then "
            "`rewrite IHn.` then `reflexivity.`"
        )

    if re.search(r"\bforall\b|->", goal_text):
        hints.append(
            "If you start with `intros`, continue and solve the residual goal in the same script. "
            "Do not stop after introductions."
        )

    words = {token.lower() for token in re.findall(r"[A-Za-z_]+", goal_text)}
    if not hypotheses and "=" in goal_text and words.issubset({"mod"}):
        hints.append(
            "This is a closed arithmetic computation goal with no hypotheses. Prefer exactly "
            "`vm_compute.` then `reflexivity.`"
        )

    if not hints:
        return ""

    return "**Goal-Specific Strategy Hint:**\n- " + "\n- ".join(hints)


def get_prompt(name: str, **kwargs) -> str:
    template = _load_raw(name)
    return fill(template, **kwargs)


def _rewrite_shape_hint(informal_proof: str) -> str:
    lowered = informal_proof.lower()
    token_count = len(re.findall(r"\S+", informal_proof))
    answer_only = token_count <= 8 and len(informal_proof.strip().splitlines()) <= 2
    mentions_induction = any(token in lowered for token in ("induction", "inductive", "base case"))
    mentions_cases = any(token in lowered for token in ("case", "cases", "split into", "either", "or else"))

    hints = [
        "Preserve the proof shape from the informal proof. Do not invent a different strategy just to fit Angelito.",
    ]

    if answer_only:
        hints.append(
            "The informal proof is extremely short or answer-only. Prefer a compact direct Angelito proof and avoid invented branching structure."
        )

    if mentions_induction:
        hints.append("The informal proof explicitly mentions induction, so `INDUCTION` is allowed when it matches the theorem.")
    else:
        hints.append("The informal proof does not explicitly mention induction. Do not introduce `INDUCTION` unless the proof text clearly requires it.")

    if mentions_cases:
        hints.append("The informal proof mentions a real case distinction, so branch structure is allowed when needed.")
    else:
        hints.append("Do not invent `APPLY ... SPLIT INTO` branches or extra case analyses unless the informal proof clearly performs them.")

    hints.append(
        "Prefer the shortest faithful Angelito proof: keep only the structure and decisive intermediate facts needed later."
    )
    return "\n".join(f"- {hint}" for hint in hints)


def get_rewrite(informal_proof: str, formal_statement: str, angelito_spec: str) -> str:
    return get_prompt(
        "rewrite",
        informal_proof=informal_proof,
        formal_statement=formal_statement,
        angelito_spec=angelito_spec,
        rewrite_shape_hint=_rewrite_shape_hint(informal_proof),
    )


def get_skeleton(formal_statement: str, angelito_proof: str) -> str:
    custom_tactics_enabled = _custom_tactics_enabled(formal_statement, angelito_proof)
    lia_available = _lia_available(formal_statement, angelito_proof)
    lra_available = _lra_available(formal_statement, angelito_proof)
    field_available = _field_available(formal_statement, angelito_proof)
    return get_prompt(
        "skeleton",
        formal_statement=formal_statement,
        angelito_proof=angelito_proof,
        tactics_reference=_load_tactics_reference(
            custom_tactics_enabled=custom_tactics_enabled,
            lia_available=lia_available,
            lra_available=lra_available,
            field_available=field_available,
        ),
        translation_guide=_load_translation_guide(),
    )


def get_fill_goal(formal_statement: str, angelito_proof: str,
                  current_proof: str, current_goal_state: str = "", error_context: str = "",
                  structured_feedback: str = "") -> str:
    custom_tactics_enabled = _custom_tactics_enabled(formal_statement, current_proof)
    lia_available = _lia_available(formal_statement, current_proof)
    lra_available = _lra_available(formal_statement, current_proof)
    field_available = _field_available(formal_statement, current_proof)
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
        goal_strategy_hint=_goal_strategy_hint(current_goal_state, lia_available=lia_available),
        tactics_reference=_load_tactics_reference(
            custom_tactics_enabled=custom_tactics_enabled,
            lia_available=lia_available,
            lra_available=lra_available,
            field_available=field_available,
        ),
        translation_guide=_load_translation_guide(),
    )
