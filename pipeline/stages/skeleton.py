"""Stage 2: Skeleton — Angelito to Rocq with admit. placeholders, compile-retry loop."""

import re
from pathlib import Path
from typing import Optional

from pipeline.coq import run_check_target, run_get_proof_state
from pipeline.errors import build_structured_feedback_context, parse_structured_error
from pipeline.model import generate_with_format_retries
from pipeline.proof_file import (
    find_admits, format_proof_file_content, proof_body_line_to_file_cursor,
    should_snapshot_before_line, write_proof_to_file,
)
from pipeline.proof_template import build_proof_template
from pipeline.utils import focused_proof_state, preview_text, truncate_for_error

_ADMIT_LINE_RE = re.compile(r"^\s*[-+*{}]*\s*admit\.\s*$")


# ---------------------------------------------------------------------------
# Prebound name extraction
# ---------------------------------------------------------------------------

def _extract_prebound_names(formal_statement: str) -> list[str]:
    m = re.search(
        r"(?:Theorem|Lemma|Proposition|Corollary|Fact|Example)\s+(\S+?)\s*[:(]",
        formal_statement,
    )
    if not m:
        return []
    name = m.group(1)
    name_end = m.start(1) + len(name)
    rest = formal_statement[name_end:]
    stripped = rest.lstrip()
    if stripped.startswith(':'):
        return []
    depth = 0
    param_end = len(rest)
    for i, ch in enumerate(rest):
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif ch == ':' and depth == 0:
            param_end = i
            break
    param_text = rest[:param_end]
    names: list[str] = []
    for binder_match in re.finditer(r"\(([^)]+)\)", param_text):
        binder = binder_match.group(1)
        colon_idx = binder.find(":")
        if colon_idx == -1:
            continue
        name_part = binder[:colon_idx].strip()
        for n in name_part.split():
            if re.match(r"^[A-Za-z_][A-Za-z0-9_\']*$", n):
                names.append(n)
    return names


# ---------------------------------------------------------------------------
# Tactic availability checks (shared with fill)
# ---------------------------------------------------------------------------

def _source_contains_any_marker(*sources: str, markers: tuple[str, ...]) -> bool:
    return any(any(marker in source for marker in markers) for source in sources if source)


def _custom_tactics_available(*sources: str) -> bool:
    require_markers = (
        "Require Import Angelito.",
        "Require Import RocqCoSPOC.Angelito.",
        "From RocqCoSPOC Require Import Angelito.",
    )
    return _source_contains_any_marker(*sources, markers=require_markers) and any(
        "Import Angelito.Ltac1." in source for source in sources if source
    )


# ---------------------------------------------------------------------------
# Skeleton structure helpers
# ---------------------------------------------------------------------------

def _normalize_skeleton_structure(skeleton: str) -> str:
    lines = skeleton.splitlines()
    normalized: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        normalized.append(line)
        if re.match(r"^\s*induction\b.*\.\s*$", line):
            j = i + 1
            plain_admits: list[int] = []
            while j < len(lines) and re.match(r"^\s*admit\.\s*$", lines[j]):
                plain_admits.append(len(normalized))
                normalized.append(f"- {lines[j].strip()}")
                j += 1
            if plain_admits:
                i = j
                continue
        i += 1
    while normalized and normalized[-1].strip() == "":
        normalized.pop()
    last_admit_idx = next(
        (idx for idx in range(len(normalized) - 1, -1, -1) if _ADMIT_LINE_RE.match(normalized[idx])), -1,
    )
    if last_admit_idx >= 0:
        trailing_nonempty = [line for line in normalized[last_admit_idx + 1:] if line.strip()]
        structural_re = re.compile(
            r"^\s*(?:[-+*{}]+\s*$|}\s*$|exact\b|assumption\b|trivial\b|auto\b|Qed\b|Defined\b)",
            re.IGNORECASE,
        )
        if trailing_nonempty and not any(structural_re.match(l) for l in trailing_nonempty):
            normalized = normalized[:last_admit_idx + 1]
    return "\n".join(normalized)


def _is_structural_skeleton_line(line: str, *, allows_split_apply: bool) -> bool:
    stripped = line.strip()
    if stripped in {"{", "}"}:
        return True
    bare = re.sub(r"^[-+*]\s+", "", stripped)
    if bare == "admit.":
        return True
    if re.match(r"^(?:intro|intros|pick|assert_goal|induction|destruct)\b.*\.\s*$", bare, re.IGNORECASE):
        return True
    if re.match(r"^(?:assert|enough)\b.*\.\s*$", bare, re.IGNORECASE):
        return True
    if re.match(r"^(?:pose proof|specialize)\b.*\.\s*$", bare, re.IGNORECASE):
        return True
    if re.match(r"^(?:split|left|right)\.\s*$", bare, re.IGNORECASE):
        return True
    if re.match(r"^(?:apply|eapply)\b.*\.\s*$", bare, re.IGNORECASE):
        return True
    return False


# ---------------------------------------------------------------------------
# Skeleton validation
# ---------------------------------------------------------------------------

def _validate_skeleton_tactics(skeleton: str, *, formal_statement: str) -> None:
    lines = [line.strip() for line in skeleton.splitlines() if line.strip()]
    bare_lines = [re.sub(r"^[-+*]\s+", "", line).strip() for line in lines]
    if not _custom_tactics_available(formal_statement):
        forbidden = [line for line in bare_lines if re.match(r"^(?:assert_goal|pick|simplify)\b", line, re.IGNORECASE)]
        if forbidden:
            examples = "\n".join(forbidden[:3])
            raise ValueError(
                "Skeleton used Angelito Ltac1 tactics, but the current proof source does not import them.\n"
                "Do not emit `assert_goal`, `pick`, or `simplify ...` unless the formal statement visibly imports "
                "`Angelito` together with `Import Angelito.Ltac1.`.\n"
                f"Examples:\n{examples}"
            )
    pseudo_math_lines = [
        line for line in bare_lines
        if any(token in line for token in ("\u2211", "sum_{", "card {")) or re.search(r"\{[^{}\n]*\|", line)
    ]
    if pseudo_math_lines:
        examples = "\n".join(pseudo_math_lines[:3])
        raise ValueError(
            "Skeleton contains pseudo-mathematical notation that is not valid Rocq syntax.\n"
            "Do not emit set-builder notation like `card {a | ...}` or sigma notation like `sum_{...}`. "
            "Translate the checkpoint into valid Rocq syntax or use a coarser valid intermediate assertion instead.\n"
            f"Examples:\n{examples}"
        )


# ---------------------------------------------------------------------------
# Parse skeleton output
# ---------------------------------------------------------------------------

def _parse_skeleton_output(raw_output: str, *, formal_statement: str, angelito_proof: str) -> str:
    from pipeline.tactic_parser import extract_tactics

    skeleton = extract_tactics(raw_output, preserve_bullets=True)
    if not skeleton:
        raise ValueError(
            "Skeleton model did not return a valid Coq tactic block.\n"
            f"Raw output:\n{truncate_for_error(raw_output)}"
        )
    skeleton = re.sub(
        r"^(\s*(?:[-+*]\s+)?)simplify\s+(?:lhs|rhs)\b.*$",
        r"\1admit.",
        skeleton, flags=re.MULTILINE | re.IGNORECASE,
    )
    prebound = set(_extract_prebound_names(formal_statement))
    if prebound:
        def _fix_intros_line(m: re.Match) -> str:
            prefix, names_str, dot = m.group(1), m.group(2), m.group(3)
            names = names_str.split()
            if all(n in prebound for n in names):
                return ""
            fixed = []
            for n in names:
                if n in prebound:
                    new_n = n + "_"
                    while new_n in prebound:
                        new_n += "_"
                    fixed.append(new_n)
                else:
                    fixed.append(n)
            return prefix + " ".join(fixed) + dot
        skeleton = re.sub(r"^(\s*intros\s+)(.*?)(\.\s*)$", _fix_intros_line, skeleton, flags=re.MULTILINE)

    has_binders = "forall " in formal_statement or "->" in formal_statement
    if not has_binders:
        skeleton = re.sub(r"^\s*intros\b.*\.\s*$", "", skeleton, flags=re.MULTILINE)

    skeleton = _normalize_skeleton_structure(skeleton)
    nonempty_lines = [line.strip() for line in skeleton.splitlines() if line.strip()]
    if not nonempty_lines:
        raise ValueError("Skeleton model returned an empty proof body.")

    first_line = nonempty_lines[0].lower()
    needs_intros = "forall " in formal_statement or "->" in formal_statement
    if needs_intros and first_line.startswith(("induction ", "destruct ", "split.", "left.", "right.")):
        raise ValueError(
            "Skeleton is missing introductions before opening proof structure.\n"
            f"Raw output:\n{truncate_for_error(raw_output)}"
        )
    if "admit." not in skeleton and len(nonempty_lines) == 1 and nonempty_lines[0].lower().startswith(
        ("induction ", "destruct ", "apply ", "split.")
    ):
        raise ValueError(
            "Skeleton opens subgoals but does not include any `admit.` placeholders.\n"
            f"Raw output:\n{truncate_for_error(raw_output)}"
        )

    inline_admit_lines = [
        line.strip() for line in skeleton.splitlines()
        if "admit." in line and not _ADMIT_LINE_RE.match(line)
    ]
    if inline_admit_lines:
        examples = "\n".join(inline_admit_lines[:3])
        raise ValueError(
            "Skeleton must use standalone `admit.` placeholder lines only.\n"
            "Do not place `admit.` inside another tactic line (for example, `simplify lhs ... by admit.`).\n"
            "Replace inner proof work such as `simpl`, `rewrite`, `exact`, `reflexivity`, or `simplify ...` with `admit.`.\n"
            f"Examples:\n{examples}\n\n"
            f"Raw output:\n{truncate_for_error(raw_output)}"
        )

    angelito_lines = [line.strip() for line in angelito_proof.splitlines() if line.strip()]
    allows_induction = any(line.startswith("INDUCTION ") for line in angelito_lines)
    allows_split_apply = any(line.startswith("APPLY ") and "SPLIT INTO:" in line for line in angelito_lines)

    if not allows_induction and any(re.sub(r"^[-+*]\s+", "", line).lower().startswith("induction ") for line in nonempty_lines):
        raise ValueError(
            "Skeleton introduced `induction` even though the Angelito proof has no `INDUCTION` step.\n"
            f"Raw output:\n{truncate_for_error(raw_output)}"
        )

    invalid_lines = [
        line.strip() for line in skeleton.splitlines()
        if line.strip() and not _is_structural_skeleton_line(line, allows_split_apply=allows_split_apply)
    ]
    if invalid_lines:
        examples = "\n".join(invalid_lines[:3])
        raise ValueError(
            "Skeleton must contain only outer proof structure and standalone `admit.` leaves.\n"
            "Replace inner proof work such as `simpl`, `rewrite`, `exact`, `reflexivity`, or `simplify ...` with `admit.`.\n"
            f"Examples:\n{examples}\n\n"
            f"Raw output:\n{truncate_for_error(raw_output)}"
        )

    _validate_skeleton_tactics(skeleton, formal_statement=formal_statement)
    return skeleton


# ---------------------------------------------------------------------------
# Retry guidance
# ---------------------------------------------------------------------------

def _retry_guidance(stage: str, error: str, *, formal_statement: str = "") -> str:
    lowered = error.lower()
    hints = [
        "Skeleton repair rules:",
        "- Preserve the proof scaffold and intermediate checkpoints, but output only valid Rocq syntax.",
        "- Use `assert (...) . { admit. }`, `destruct ... as ... .`, `intros`, and occasional `apply` when they match the Angelito proof plan.",
        "- Every leaf must still be a standalone `admit.` line.",
    ]
    if "angelito ltac1 tactics" in lowered:
        hints.append("- Do not use `assert_goal`, `pick`, or `simplify ...` because this proof source does not import Angelito Ltac1.")
    if "pseudo-mathematical notation" in lowered:
        hints.append("- Do not emit set-builder notation like `card {a | ...}` or sigma notation like `sum_{...}` / \u2211; use only valid Rocq terms.")
    if "standalone `admit.`" in lowered:
        hints.append("- Put `admit.` on its own line inside braces, not inline with another tactic.")
        hints.append("- For a simple computation goal, the entire skeleton can just be `admit.` on its own line.")
    if "already used" in lowered:
        prebound = _extract_prebound_names(formal_statement)
        hints.append(
            "- The Coq error `x is already used` means you tried to `intros` a name that is already "
            "bound in the theorem signature. Do NOT re-introduce names that appear as theorem parameters."
        )
        if prebound:
            hints.append(f"- These names are already in scope from the theorem statement: {', '.join(prebound)}")
            hints.append("- Your `intros` line must use FRESH names that do not collide with these.")
    if re.search(r"has type.*while.*expected", lowered):
        hints.append(
            "- There is a type mismatch in an assertion. Check that the types in your `assert` "
            "statements match the Coq functions involved. For example, `Int_part` returns `Z` not `nat`; "
            "`INR` takes `nat` and returns `R`. Ensure quantified variables have the correct type."
        )
    if "not a type" in lowered or "not a product" in lowered:
        hints.append(
            "- A term you used is not the right kind. Check that `assert` propositions are valid Prop-typed "
            "expressions and that function applications have the right number of arguments."
        )
    if "unable to unify" in lowered:
        hints.append(
            "- Coq could not unify two terms. The assertion or tactic argument does not match the actual goal shape. "
            "Simplify the skeleton \u2014 use fewer intermediate assertions if the types are hard to get right."
        )
    if "no product" in lowered:
        hints.append(
            "- `intros` failed because the goal has no `forall` or implication to introduce. "
            "If the goal is a ground computation, the skeleton can just be `admit.` on its own line."
        )
    return "\n".join(hints)


# ---------------------------------------------------------------------------
# Model call
# ---------------------------------------------------------------------------

def _run_skeleton_model(
    formal_statement: str, angelito_proof: str, config: dict,
    error_context: str = "", structured_feedback: str = "", goal_state: str = "",
    debug_attempts: Optional[list[dict]] = None, log_metadata: Optional[dict] = None,
) -> str:
    from pipeline.prompts import get_skeleton

    prompt = get_skeleton(formal_statement, angelito_proof)
    if goal_state.strip():
        prompt += (
            "\n\n**Proof state after `intros`** (use these exact types in your assertions):\n"
            f"```\n{goal_state.strip()}\n```\n"
        )
    if structured_feedback.strip():
        prompt += (
            "\n\nPrevious skeleton failed to compile. Use this structured compiler feedback to "
            "repair the scaffold while preserving the same theorem and imports.\n"
            f"```xml\n{structured_feedback.strip()}\n```\n"
        )
    if error_context.strip():
        prompt += (
            "\n\nPrevious skeleton failed to compile. Fix only the tactic scaffold.\n"
            f"{error_context.strip()}\n"
        )
    skeleton = generate_with_format_retries(
        config["skeleton_model"], prompt, config,
        stage="skeleton",
        parser=lambda raw: _parse_skeleton_output(raw, formal_statement=formal_statement, angelito_proof=angelito_proof),
        retry_guidance_fn=_retry_guidance,
        debug_attempts=debug_attempts,
        log_metadata=log_metadata,
        formal_statement=formal_statement,
    )
    return _normalize_skeleton_structure(skeleton)


# ---------------------------------------------------------------------------
# Public API — full skeleton stage with compile-retry loop
# ---------------------------------------------------------------------------

def run(
    formal_statement: str, angelito_proof: str, config: dict,
    *, target_path: Path, repo_root: Path, target_rel: str,
    debug: bool = False, debug_char_limit: int = 500,
    persist_fn=None, trace: Optional[dict] = None,
) -> dict:
    """Run the skeleton stage. Returns result dict with skeleton, proof_template, slot_values, trace data."""
    max_attempts = int(config.get("max_skeleton_attempts", 3))
    trace_skeleton = trace.get("skeleton", {"compile_attempts": []}) if trace else {"compile_attempts": []}
    if trace is not None:
        trace["skeleton"] = trace_skeleton

    # Capture goal state after intros for the skeleton model
    skeleton_goal_state = ""
    has_binders = "forall " in formal_statement or "->" in formal_statement
    minimal_tactic = "intros.\nadmit." if has_binders else "admit."
    write_proof_to_file(target_path, formal_statement, minimal_tactic, use_admitted=True)
    _pre_exit, _pre_stdout, _pre_stderr = run_check_target(repo_root, target_rel)
    if _pre_exit == 0:
        _pre_admits = find_admits(minimal_tactic)
        if _pre_admits:
            _snap_before = should_snapshot_before_line(minimal_tactic, _pre_admits[0])
            _cursor = proof_body_line_to_file_cursor(
                formal_statement, _pre_admits[0], target_path=target_path, before_line=_snap_before,
            )
            skeleton_goal_state = focused_proof_state(run_get_proof_state(repo_root, target_rel, _cursor))
            if debug and skeleton_goal_state:
                print(f"[DEBUG] skeleton goal state captured ({len(skeleton_goal_state)} chars)", flush=True)

    error_context = ""
    structured_feedback = ""
    skeleton = ""
    rendered_skeleton = ""
    proof_template = None
    slot_values: dict[str, Optional[str]] = {}
    step_success = False
    last_output = ""

    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
            print(f"  Skeleton compile retry {attempt}/{max_attempts}...", flush=True)
        skel_config = config
        if attempt > 1:
            skel_config = dict(config)
            skel_config["temperature"] = max(config.get("temperature", 0.0), 0.4)
        model_attempts: list[dict] = []
        try:
            skeleton = _run_skeleton_model(
                formal_statement, angelito_proof, skel_config,
                error_context=error_context, structured_feedback=structured_feedback,
                goal_state=skeleton_goal_state,
                debug_attempts=model_attempts,
                log_metadata={"skeleton_compile_attempt": attempt},
            )
        except Exception as e:
            trace_skeleton["compile_attempts"].append({
                "attempt": attempt, "status": "model_error", "error": str(e), "model_attempts": model_attempts,
            })
            if persist_fn:
                persist_fn()
            error_context = (
                f"The previous skeleton attempt failed format validation: {e}\n\n"
                "Generate a corrected skeleton that uses only valid Rocq syntax."
            )
            continue

        proof_template = build_proof_template(skeleton, angelito_proof)
        slot_values = {slot.name: None for slot in proof_template.slots}
        rendered_skeleton = proof_template.render(slot_values)
        has_admits = proof_template.has_unfilled_slots(slot_values)
        write_proof_to_file(target_path, formal_statement, rendered_skeleton, use_admitted=has_admits)
        if debug:
            print(
                f"[DEBUG] skeleton attempt {attempt}: slots={len(proof_template.slots)}, "
                f"has_admits={has_admits}, rendered_chars={len(rendered_skeleton)}", flush=True,
            )
            print(f"[DEBUG] rendered skeleton preview:\n{preview_text(rendered_skeleton, limit=debug_char_limit)}", flush=True)

        exit_code, stdout, stderr = run_check_target(repo_root, target_rel)
        last_output = (stderr or stdout).strip()
        feedback, formatted_feedback = build_structured_feedback_context(stdout, stderr)
        if debug:
            print(f"[DEBUG] skeleton check exit_code={exit_code}, stderr_chars={len(stderr)}, feedback_items={len(feedback)}", flush=True)
            if stderr.strip():
                print(f"[DEBUG] skeleton stderr preview:\n{preview_text(stderr, limit=debug_char_limit)}", flush=True)

        attempt_trace: dict = {
            "attempt": attempt, "text": skeleton, "rendered_text": rendered_skeleton,
            "full_file_text": format_proof_file_content(formal_statement, rendered_skeleton, use_admitted=has_admits),
            "slot_names": [slot.name for slot in proof_template.slots],
            "model_attempts": model_attempts,
            "status": "compiled" if exit_code == 0 else "compile_error",
            "compiles": exit_code == 0,
            "check_stdout": stdout.strip(), "stdout": stdout.strip(),
            "check_stderr": stderr.strip(), "stderr": stderr.strip(),
        }
        if feedback:
            attempt_trace["compiler_feedback"] = feedback
        if exit_code == 0 and has_admits:
            admit_lines = find_admits(rendered_skeleton)
            if admit_lines:
                snap = should_snapshot_before_line(rendered_skeleton, admit_lines[0])
                cursor = proof_body_line_to_file_cursor(
                    formal_statement, admit_lines[0], target_path=target_path, before_line=snap,
                )
                attempt_trace["proof_state"] = focused_proof_state(run_get_proof_state(repo_root, target_rel, cursor))
        trace_skeleton["compile_attempts"].append(attempt_trace)
        if persist_fn:
            persist_fn()

        if exit_code == 0:
            step_success = True
            trace_skeleton.update({
                "text": skeleton, "rendered_text": rendered_skeleton,
                "full_file_text": format_proof_file_content(formal_statement, rendered_skeleton, use_admitted=has_admits),
                "slot_names": [slot.name for slot in proof_template.slots],
                "model_attempts": model_attempts, "compiles": True,
                "check_stdout": stdout.strip(), "stdout": stdout.strip(),
                "check_stderr": stderr.strip(), "stderr": stderr.strip(),
            })
            if feedback:
                trace_skeleton["compiler_feedback"] = feedback
            break

        # Build error context for retry
        error_context = (
            "The previous skeleton failed to compile.\n\n"
            f"**Failed skeleton tactics:**\n```coq\n{rendered_skeleton}\n```\n\n"
            f"**Coq compiler error:**\n```\n{parse_structured_error(stderr, stdout)}\n```\n\n"
        )
        if attempt >= 2 and trace_skeleton["compile_attempts"]:
            prev_attempts = []
            for prev in trace_skeleton["compile_attempts"][:-1]:
                if prev.get("status") == "compile_error":
                    prev_skel = prev.get("rendered_text", "")[:300]
                    prev_err = prev.get("stderr", prev.get("check_stderr", ""))[:200]
                    prev_attempts.append(f"```coq\n{prev_skel}\n```\nError: {prev_err}")
            if prev_attempts:
                error_context += "**Earlier failed attempts (do not repeat these):**\n" + "\n---\n".join(prev_attempts) + "\n\n"

        error_lower = (stderr + stdout).lower()
        prebound = _extract_prebound_names(formal_statement)
        if "already used" in error_lower and prebound:
            error_context += (
                f"**Important:** The theorem signature already binds these names: {', '.join(prebound)}. "
                "Do NOT re-introduce them with `intros`. Use fresh names or omit `intros` for parameters "
                "that are already in scope.\n\n"
            )
        if re.search(r"has type.*while.*expected", error_lower):
            error_context += (
                "**Important:** There is a type mismatch. Check that types in `assert` statements "
                "match the Coq functions used (e.g., `Int_part` returns `Z`, not `nat`).\n\n"
            )
        error_context += "Generate a corrected skeleton that compiles when wrapped with this theorem and imports."
        structured_feedback = formatted_feedback

    if not step_success:
        raise RuntimeError(
            "Skeleton does not compile after retrying scaffold generation. "
            "Refusing to start fill retries on an invalid proof scaffold.\n"
            f"{last_output}"
        )

    return {
        "skeleton": skeleton,
        "rendered_skeleton": rendered_skeleton,
        "proof_template": proof_template,
        "slot_values": slot_values,
        "has_admits": proof_template.has_unfilled_slots(slot_values) if proof_template else False,
    }
