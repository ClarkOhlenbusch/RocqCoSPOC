"""Stage 3: Fill — iteratively fill each admit. with real tactics."""

import re
from pathlib import Path
from typing import Optional

from pipeline.coq import run_check_target, run_get_proof_state
from pipeline.errors import build_structured_feedback_context, parse_structured_error
from pipeline.model import generate_with_format_retries
from pipeline.proof_file import (
    capture_goal_state_after_replacement, find_admits, format_proof_file_content,
    proof_body_line_to_file_cursor, should_snapshot_before_line, write_proof_to_file,
)
from pipeline.proof_template import count_rendered_admits, find_marked_admit_line
from pipeline.utils import focused_proof_state, preview_text, split_goal_state, trim_terminal_tactic_suffix


# ---------------------------------------------------------------------------
# Tactic availability checks
# ---------------------------------------------------------------------------

def _source_contains_any_marker(*sources: str, markers: tuple[str, ...]) -> bool:
    return any(any(marker in source for marker in markers) for source in sources if source)


def _custom_tactics_available(*sources: str) -> bool:
    require_markers = (
        "Require Import Angelito.", "Require Import RocqCoSPOC.Angelito.",
        "From RocqCoSPOC Require Import Angelito.",
    )
    return _source_contains_any_marker(*sources, markers=require_markers) and any(
        "Import Angelito.Ltac1." in source for source in sources if source
    )


def _lra_tactic_available(*sources: str) -> bool:
    markers = (
        "Require Import Lra.", "From Coq Require Import Lra.",
        "Require Import Psatz.", "From Coq Require Import Psatz.",
        "Require Import Fourier.", "From Coq Require Import Fourier.",
    )
    return _source_contains_any_marker(*sources, markers=markers)


def _field_tactic_available(*sources: str) -> bool:
    markers = (
        "Require Import Field.", "From Coq Require Import Field.",
        "Require Import Ring.", "From Coq Require Import Ring.",
        "Require Import SetoidRing.Field.", "From Coq Require Import SetoidRing.Field.",
    )
    return _source_contains_any_marker(*sources, markers=markers)


# ---------------------------------------------------------------------------
# Parse and validate fill output
# ---------------------------------------------------------------------------

def _parse_tactic_output(raw_output: str) -> str:
    from pipeline.tactic_parser import extract_tactics
    from pipeline.utils import truncate_for_error

    tactics = extract_tactics(raw_output)
    if not tactics:
        raise ValueError(
            "Model did not return a valid Coq tactic block.\n"
            f"Raw output:\n{truncate_for_error(raw_output)}"
        )
    return tactics


def _validate_fill_tactics(
    tactics: str, *, formal_statement: str, current_proof: str, current_goal_state: str,
) -> None:
    lines = [line.strip() for line in tactics.splitlines() if line.strip()]
    bare_lines = [re.sub(r"^(?:[-+*]\s+)?(?:(?:\d+|all)\s*:\s*)?", "", line).strip() for line in lines]

    if not _custom_tactics_available(formal_statement, current_proof):
        forbidden = [line for line in bare_lines if re.match(r"^(?:simplify|assert_goal|pick)\b", line, re.IGNORECASE)]
        if forbidden:
            examples = "\n".join(forbidden[:3])
            raise ValueError(
                "Current proof does not import Angelito Ltac1 tactics, but the fill used high-level Angelito tactics.\n"
                "Do not emit `simplify ...`, `assert_goal`, or `pick` unless the proof source imports "
                "`From RocqCoSPOC Require Import Angelito.` together with `Import Angelito.Ltac1.`.\n"
                f"Examples:\n{examples}"
            )

    invalid_simplify = [
        line for line in bare_lines if re.match(r"^simplify\b", line, re.IGNORECASE)
        and not re.match(r"^simplify\s+(?:lhs|rhs)\s*\(", line, re.IGNORECASE)
    ]
    if invalid_simplify:
        examples = "\n".join(invalid_simplify[:3])
        raise ValueError(
            "Fill used invalid `simplify` syntax.\n"
            "Use `simplify lhs (a = b) ...` or `simplify rhs (a = b) ...` exactly, or use standard Rocq tactics instead.\n"
            f"Examples:\n{examples}"
        )

    if not _lra_tactic_available(formal_statement, current_proof):
        forbidden = [line for line in bare_lines if re.match(r"^(?:lra|nra)\b", line, re.IGNORECASE)]
        if forbidden:
            examples = "\n".join(forbidden[:3])
            raise ValueError(
                "Current proof does not import `Lra`/`Psatz`, but the fill used `lra.` or `nra.`.\n"
                f"Examples:\n{examples}"
            )

    if not _field_tactic_available(formal_statement, current_proof):
        forbidden = [line for line in bare_lines if re.match(r"^(?:field|field_simplify)\b", line, re.IGNORECASE)]
        if forbidden:
            examples = "\n".join(forbidden[:3])
            raise ValueError(
                "Current proof does not visibly import field support, but the fill used `field.` or `field_simplify`.\n"
                f"Examples:\n{examples}"
            )

    _, goal_text = split_goal_state(current_goal_state)
    if re.search(r"\bforall\b|->", goal_text):
        if bare_lines and all(re.match(r"^(?:intro|intros|pick)\b", line, re.IGNORECASE) for line in bare_lines):
            raise ValueError(
                "Fill only introduces binders and does not solve the residual goal.\n"
                "Continue after `intros` until the marked subgoal is fully discharged."
            )


def _parse_fill_output(raw_output: str, *, formal_statement: str, current_proof: str, current_goal_state: str) -> str:
    tactics = _parse_tactic_output(raw_output)
    _validate_fill_tactics(tactics, formal_statement=formal_statement, current_proof=current_proof, current_goal_state=current_goal_state)
    return tactics


# ---------------------------------------------------------------------------
# Retry guidance
# ---------------------------------------------------------------------------

def _retry_guidance(stage: str, error: str, *, formal_statement: str = "") -> str:
    lowered = error.lower()
    hints = [
        "Fill repair rules:",
        "- Output only valid Rocq tactics; no prose, no markdown, no Angelito keywords.",
        "- Fully discharge the marked goal in one replacement.",
        "- Use only tactics that are actually available from the current imports.",
    ]
    if "angelito ltac1 tactics" in lowered:
        hints.append("- Do not use `simplify ...`, `assert_goal`, or `pick` because this proof does not import Angelito Ltac1.")
        hints.append("- Use standard Rocq tactics instead: `rewrite`, `apply`, `exact`, `simpl`, `ring`, `lra`, `lia`, `field`, `reflexivity`.")
    if "`lra`" in lowered or "`nra`" in lowered or "lra" in lowered and "psatz" in lowered:
        hints.append("- Do not use `lra.` or `nra.` because the current proof does not import `Lra`/`Psatz`.")
    if "`field.`" in lowered or "field_simplify" in lowered:
        hints.append("- Do not use `field.` or `field_simplify` unless the current proof visibly imports field support.")
    if "introduces binders" in lowered:
        hints.append("- `intros` may be the first step, but it cannot be the whole answer; continue until the goal is solved.")
    if "invalid `simplify` syntax" in lowered:
        hints.append("- Either use standard Rocq tactics, or use exact Angelito Ltac1 syntax like `simplify lhs (a = b) by ...`.")
    return "\n".join(hints)


# ---------------------------------------------------------------------------
# Fill error hints (compile-error specific)
# ---------------------------------------------------------------------------

def _build_fill_error_hints(error_lower: str) -> list[str]:
    hints = []
    if "found no subterm matching" in error_lower:
        hints.append(
            "The `rewrite` tactic failed because the term you tried to rewrite does not appear "
            "syntactically in the goal or hypothesis. Try a completely different approach. "
            "If `lra` is available, it can often solve linear arithmetic goals directly from "
            "hypotheses without needing `rewrite` at all."
        )
    if "unable to unify" in error_lower:
        hints.append(
            "The tactic could not unify the expected and actual terms. "
            "The goal shape may differ from what you assumed. Use the goal state as ground truth. "
            "If the goal involves `^`, `x * y`, or other nonlinear terms over R, "
            "`lra` cannot handle it \u2014 use `nlra` or `nra` instead (available when Psatz is imported). "
            "Alternatively, `rewrite` the variables to concrete values first, then use `ring` or `nlra`."
        )
    if "not an equality" in error_lower or "not an equation" in error_lower:
        hints.append("`rewrite` requires an equality hypothesis. The hypothesis you used is not an equality.")
    if "no such goal" in error_lower or "no focused proof" in error_lower:
        hints.append(
            "A previous tactic already closed the goal, so the next tactic had nothing to work on. "
            "Remove the extra tactics after the goal-closing one."
        )
    if "cannot be unfocused" in error_lower:
        hints.append(
            "Your tactics opened multiple subgoals (e.g., via `induction`, `split`, or `field`) "
            "but only solved some of them. You must solve ALL subgoals within this single slot. "
            "If a tactic creates branches, use bullets (`-`, `+`, `*`) or braces (`{ }`) to handle each branch. "
            "Alternatively, avoid branching tactics and use a direct approach like `lra`, `nlra`, `lia`, or `ring`."
        )
    if "was not found in the current" in error_lower:
        hints.append(
            "You referenced a lemma or variable that does not exist. Do not invent lemma names. "
            "Use only hypotheses visible in the goal state and standard tactics like `lra`, `lia`, `ring`, `nlra`, `field`."
        )
    return hints


# ---------------------------------------------------------------------------
# Model call
# ---------------------------------------------------------------------------

def _run_fill_model(
    formal_statement: str, angelito_proof: str, current_proof: str,
    current_goal_state: str, config: dict, error_context: str = "",
    structured_feedback: str = "",
    debug_attempts: Optional[list[dict]] = None, log_metadata: Optional[dict] = None,
) -> str:
    from pipeline.prompts import get_fill_goal

    prompt = get_fill_goal(
        formal_statement, angelito_proof, current_proof,
        current_goal_state, error_context, structured_feedback,
    )
    replacement = generate_with_format_retries(
        config["fill_model"], prompt, config,
        stage="fill_goal",
        parser=lambda raw: _parse_fill_output(
            raw, formal_statement=formal_statement,
            current_proof=current_proof, current_goal_state=current_goal_state,
        ),
        retry_guidance_fn=_retry_guidance,
        debug_attempts=debug_attempts,
        log_metadata=log_metadata,
        formal_statement=formal_statement,
    )
    return trim_terminal_tactic_suffix(replacement)


# ---------------------------------------------------------------------------
# Public API — full fill stage with retry loop
# ---------------------------------------------------------------------------

def run(
    formal_statement: str, angelito_proof: str, proof_template, slot_values: dict,
    config: dict, *, target_path: Path, repo_root: Path, target_rel: str,
    debug: bool = False, debug_char_limit: int = 500,
    persist_fn=None, trace: Optional[dict] = None,
) -> dict:
    """Run the fill stage. Returns result dict with final proof body, slot_values, summary."""
    max_fill = config.get("max_fill_attempts", 3)
    rendered_skeleton = proof_template.render(slot_values)
    proof_body = rendered_skeleton
    admits_filled = 0
    total_attempts = 0

    while True:
        current_slot = proof_template.next_unfilled_slot(slot_values)
        if current_slot is None:
            break

        proof_body = proof_template.render(slot_values)
        marked_proof = proof_template.render(slot_values, marked_slot=current_slot.name)
        admit_idx = find_marked_admit_line(marked_proof)
        remaining_admits = count_rendered_admits(proof_body)
        admits_filled += 1
        print(f"Step 3: Filling admit #{admits_filled} (line {admit_idx + 1}, {remaining_admits} remaining)...", flush=True)

        write_proof_to_file(target_path, formal_statement, proof_body, use_admitted=True)
        snapshot_before = should_snapshot_before_line(marked_proof, admit_idx)
        current_goal_state = focused_proof_state(run_get_proof_state(
            repo_root, target_rel,
            proof_body_line_to_file_cursor(formal_statement, admit_idx, target_path=target_path, before_line=snapshot_before),
        ))
        error_context = ""
        structured_feedback_context = ""
        filled = False
        if debug:
            print(f"[DEBUG] slot={current_slot.name}, admit_idx={admit_idx}, remaining={remaining_admits}, goal_chars={len(current_goal_state)}", flush=True)
            print(f"[DEBUG] goal preview:\n{preview_text(current_goal_state, limit=debug_char_limit)}", flush=True)

        for attempt in range(1, max_fill + 1):
            total_attempts += 1
            fill_trace: dict = {
                "slot_name": current_slot.name, "admit_index": admit_idx,
                "attempt": attempt, "current_goal_state": current_goal_state,
            }
            if trace is not None:
                trace["fills"].append(fill_trace)
                if persist_fn:
                    persist_fn()

            fill_config = config
            if attempt > 1:
                fill_config = dict(config)
                fill_config["temperature"] = max(config.get("temperature", 0.0), 0.4)

            fill_model_attempts: list[dict] = []
            try:
                replacement = _run_fill_model(
                    formal_statement, angelito_proof, marked_proof, current_goal_state,
                    fill_config, error_context, structured_feedback_context,
                    debug_attempts=fill_model_attempts,
                    log_metadata={"slot_name": current_slot.name, "fill_attempt": attempt, "admit_index": admit_idx},
                )
                fill_trace["source"] = "model"
                fill_trace["model_attempts"] = fill_model_attempts
            except Exception as e:
                fill_trace["status"] = "model_error"
                fill_trace["error"] = str(e)
                fill_trace["source"] = "model"
                fill_trace["model_attempts"] = fill_model_attempts
                if persist_fn:
                    persist_fn()
                raise RuntimeError(f"  Fill model error: {e}") from e

            fill_trace["replacement"] = replacement
            if debug:
                print(f"[DEBUG] fill attempt {attempt} replacement chars={len(replacement)}", flush=True)
                print(f"[DEBUG] replacement preview:\n{preview_text(replacement, limit=debug_char_limit)}", flush=True)

            candidate_slot_values = dict(slot_values)
            candidate_slot_values[current_slot.name] = replacement
            candidate = proof_template.render(candidate_slot_values)
            candidate_has_admits = proof_template.has_unfilled_slots(candidate_slot_values)
            write_proof_to_file(target_path, formal_statement, candidate, use_admitted=candidate_has_admits)

            exit_code, stdout, stderr = run_check_target(repo_root, target_rel)
            fill_trace["exit_code"] = exit_code
            fill_trace["check_stdout"] = stdout.strip()
            fill_trace["stdout"] = stdout.strip()
            fill_trace["check_stderr"] = stderr.strip()
            fill_trace["stderr"] = stderr.strip()
            feedback, formatted_feedback = build_structured_feedback_context(stdout, stderr)
            if feedback:
                fill_trace["compiler_feedback"] = feedback
            if debug:
                print(f"[DEBUG] fill compile exit_code={exit_code}, stderr_chars={len(stderr)}, feedback_items={len(feedback)}", flush=True)
                if stderr.strip():
                    print(f"[DEBUG] fill stderr preview:\n{preview_text(stderr, limit=debug_char_limit)}", flush=True)

            if exit_code == 0:
                fill_trace["status"] = "success"
                if persist_fn:
                    persist_fn()
                slot_values = candidate_slot_values
                proof_body = candidate
                filled = True
                print(f"    Attempt {attempt}: compiled OK.", flush=True)
                break

            parsed_error = parse_structured_error(stderr, stdout)
            failed_goal_state = capture_goal_state_after_replacement(
                repo_root=repo_root, target_rel=target_rel, target_path=target_path,
                formal_statement=formal_statement, admit_idx=admit_idx, replacement=replacement,
            )
            if failed_goal_state:
                fill_trace["post_replacement_goal_state"] = failed_goal_state
            fill_trace["status"] = "compile_error"
            if persist_fn:
                persist_fn()

            error_context = (
                f"The previous replacement failed to compile.\n\n"
                f"**Failed tactics:**\n```coq\n{replacement}\n```\n\n"
                f"**Coq compiler error:**\n```\n{parsed_error}\n```\n\n"
            )
            error_lower = (stderr or stdout or parsed_error).lower()
            error_hints = _build_fill_error_hints(error_lower)
            if error_hints:
                error_context += "**Repair guidance:**\n" + "\n".join(f"- {h}" for h in error_hints) + "\n\n"
            error_context += "Try a fundamentally different tactic approach instead of a small variation of the failed one."
            if failed_goal_state and failed_goal_state != current_goal_state:
                current_goal_state = failed_goal_state
                error_context += (
                    "\n\n**Residual Goal State After Running The Failed Tactics:**\n"
                    f"```text\n{failed_goal_state}\n```\n"
                )
            structured_feedback_context = formatted_feedback
            marked_proof = proof_template.render(slot_values, marked_slot=current_slot.name)
            print(f"    Attempt {attempt}: compile error, retrying...", flush=True)

        if not filled:
            write_proof_to_file(target_path, formal_statement, proof_template.render(slot_values), use_admitted=True)
            raise RuntimeError(f"Failed to fill admit #{admits_filled} after {max_fill} attempts.")

    return {
        "proof_body": proof_body,
        "slot_values": slot_values,
        "admits_filled": admits_filled,
        "total_attempts": total_attempts,
        "slot_count": len(proof_template.slots),
    }
