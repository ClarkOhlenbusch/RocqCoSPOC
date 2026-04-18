#!/usr/bin/env python3
"""
Automated proof pipeline:
  Step 1: Rewrite informal proof -> strict Angelito syntax
  Step 2: Translate Angelito -> Rocq skeleton (with admit. placeholders)
  Step 3: Iteratively fill each admit., compile-checking after each fill

Uses Open Router API. Run from repo root.
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def load_config():
    import yaml
    config_path = Path(__file__).resolve().parent / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Step 1: Rewrite
# ---------------------------------------------------------------------------

def run_rewrite(
    informal_path: Path,
    formal_statement: str,
    config: dict,
    debug_attempts: Optional[list[dict]] = None,
    log_metadata: Optional[dict] = None,
) -> str:
    from pipeline.prompts import get_rewrite

    text = informal_path.read_text(encoding="utf-8").strip()
    angelito_spec_path = REPO_ROOT / "angelito-spec.md"
    if not angelito_spec_path.exists():
        raise FileNotFoundError(f"Angelito spec not found: {angelito_spec_path}")
    angelito_spec = angelito_spec_path.read_text(encoding="utf-8").strip()
    prompt = get_rewrite(text, formal_statement, angelito_spec)
    return _generate_with_format_retries(
        config["rewrite_model"],
        prompt,
        config,
        stage="rewrite",
        parser=lambda raw: _parse_rewrite_output(raw, informal_proof=text, formal_statement=formal_statement),
        debug_attempts=debug_attempts,
        log_metadata=log_metadata,
    )


# ---------------------------------------------------------------------------
# Step 2: Skeleton
# ---------------------------------------------------------------------------

def run_skeleton(
    formal_statement: str,
    angelito_proof: str,
    config: dict,
    error_context: str = "",
    structured_feedback: str = "",
    debug_attempts: Optional[list[dict]] = None,
    log_metadata: Optional[dict] = None,
) -> str:
    from pipeline.prompts import get_skeleton

    prompt = get_skeleton(formal_statement, angelito_proof)
    if structured_feedback.strip():
        prompt += (
            "\n\nPrevious skeleton failed to compile. Use this structured compiler feedback to "
            "repair the scaffold while preserving the same theorem and imports.\n"
            "```xml\n"
            f"{structured_feedback.strip()}\n"
            "```\n"
        )
    if error_context.strip():
        prompt += (
            "\n\nPrevious skeleton failed to compile. Fix only the tactic scaffold.\n"
            f"{error_context.strip()}\n"
        )
    skeleton = _generate_with_format_retries(
        config["skeleton_model"],
        prompt,
        config,
        stage="skeleton",
        parser=lambda raw: _parse_skeleton_output(
            raw,
            formal_statement=formal_statement,
            angelito_proof=angelito_proof,
        ),
        debug_attempts=debug_attempts,
        log_metadata=log_metadata,
        formal_statement=formal_statement,
    )
    return _normalize_skeleton_structure(skeleton)


# ---------------------------------------------------------------------------
# Step 3: Fill one admit
# ---------------------------------------------------------------------------

def run_fill_goal(formal_statement: str, angelito_proof: str,
                  current_proof: str, current_goal_state: str, config: dict, error_context: str = "",
                  structured_feedback: str = "", debug_attempts: Optional[list[dict]] = None,
                  log_metadata: Optional[dict] = None) -> str:
    from pipeline.prompts import get_fill_goal

    deterministic = _derive_deterministic_fill(current_goal_state)
    if deterministic is not None:
        if debug_attempts is not None:
            debug_attempts.append(
                {
                    "format_attempt": 0,
                    "model": "deterministic",
                    "raw_output": deterministic,
                    "status": "derived",
                    "parsed_output": deterministic,
                }
            )
        return deterministic

    prompt = get_fill_goal(
        formal_statement,
        angelito_proof,
        current_proof,
        current_goal_state,
        error_context,
        structured_feedback,
    )
    replacement = _generate_with_format_retries(
        config["fill_model"],
        prompt,
        config,
        stage="fill_goal",
        parser=lambda raw: _parse_fill_output(
            raw,
            formal_statement=formal_statement,
            current_proof=current_proof,
            current_goal_state=current_goal_state,
        ),
        debug_attempts=debug_attempts,
        log_metadata=log_metadata,
        formal_statement=formal_statement,
    )
    return _trim_terminal_tactic_suffix(replacement)


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------

def run_check_target(repo_root: Path, file_path_rel: str, *, timeout_sec: int = 60) -> tuple[int, str, str]:
    """Run check-target-proof.py. Returns (exit_code, stdout, stderr)."""
    script = repo_root / "scripts" / "check-target-proof.py"
    cmd = [
        sys.executable,
        str(script),
        "--file-path",
        file_path_rel,
    ]
    try:
        proc = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True, timeout=timeout_sec)
    except subprocess.TimeoutExpired as e:
        stdout = (e.stdout or "") if isinstance(e.stdout, str) else ""
        stderr = (e.stderr or "") if isinstance(e.stderr, str) else ""
        stderr = (
            (stderr + "\n") if stderr else ""
        ) + f"Proof check timed out after {timeout_sec} seconds for {file_path_rel}"
        return 124, stdout, stderr
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def run_get_proof_state(repo_root: Path, file_path_rel: str, cursor_line: int, *, timeout_sec: int = 60) -> str:
    """Run get-proof-state.py and return parsed proof state text, or empty string."""
    script = repo_root / "scripts" / "get-proof-state.py"
    cmd = [
        sys.executable,
        str(script),
        "--file-path",
        file_path_rel,
        "--cursor-line",
        str(cursor_line),
    ]
    try:
        proc = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True, timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


# ---------------------------------------------------------------------------
# admit. helpers
# ---------------------------------------------------------------------------

_ADMIT_LINE_RE = re.compile(r"^\s*[-+*{}]*\s*admit\.\s*$")


def _find_admits(proof_text: str) -> list[int]:
    """Return 0-based line indices of admit. lines (including bullet-prefixed)."""
    return [i for i, line in enumerate(proof_text.splitlines())
            if _ADMIT_LINE_RE.match(line)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_fences(text: str) -> str:
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


def _truncate_for_error(text: str, limit: int = 1200) -> str:
    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit] + "\n...[truncated]..."


def _preview_text(text: str, limit: int = 500) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return "(empty)"
    if len(cleaned) <= limit:
        return _console_safe(cleaned)
    return _console_safe(cleaned[:limit] + "... [truncated]")


def _console_safe(text: str) -> str:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return str(text).encode(encoding, errors="replace").decode(encoding, errors="replace")


def _split_goal_state(state_text: str) -> tuple[list[str], str]:
    lines = [line.strip() for line in state_text.splitlines() if line.strip()]
    if not lines:
        return [], ""
    try:
        separator_idx = lines.index("============================")
    except ValueError:
        return [], "\n".join(lines)
    hypotheses = lines[1:separator_idx]
    goal = "\n".join(lines[separator_idx + 1 :]).strip()
    return hypotheses, goal


def _derive_deterministic_fill(current_goal_state: str) -> Optional[str]:
    # Deterministic fills disabled — let the agent handle all goals.
    return None


def _parse_rewrite_output(raw_output: str, *, informal_proof: str = "", formal_statement: str = "") -> str:
    rewrite = _extract_angelito_block(_strip_fences(raw_output))
    _validate_angelito_rewrite(rewrite, informal_proof=informal_proof, formal_statement=formal_statement)
    return rewrite


def _parse_tactic_output(raw_output: str) -> str:
    from pipeline.tactic_parser import extract_tactics

    tactics = extract_tactics(raw_output)
    if not tactics:
        raise ValueError(
            "Model did not return a valid Coq tactic block.\n"
            f"Raw output:\n{_truncate_for_error(raw_output)}"
        )
    return tactics


def _source_contains_any_marker(*sources: str, markers: tuple[str, ...]) -> bool:
    return any(any(marker in source for marker in markers) for source in sources if source)


def _custom_tactics_available_in_proof(*sources: str) -> bool:
    require_markers = (
        "Require Import Angelito.",
        "Require Import RocqCoSPOC.Angelito.",
        "From RocqCoSPOC Require Import Angelito.",
    )
    return _source_contains_any_marker(*sources, markers=require_markers) and any(
        "Import Angelito.Ltac1." in source for source in sources if source
    )


def _lra_tactic_available(*sources: str) -> bool:
    markers = (
        "Require Import Lra.",
        "From Coq Require Import Lra.",
        "Require Import Psatz.",
        "From Coq Require Import Psatz.",
        "Require Import Fourier.",
        "From Coq Require Import Fourier.",
    )
    return _source_contains_any_marker(*sources, markers=markers)


def _field_tactic_available(*sources: str) -> bool:
    markers = (
        "Require Import Field.",
        "From Coq Require Import Field.",
        "Require Import Ring.",
        "From Coq Require Import Ring.",
        "Require Import SetoidRing.Field.",
        "From Coq Require Import SetoidRing.Field.",
    )
    return _source_contains_any_marker(*sources, markers=markers)


def _parse_fill_output(
    raw_output: str,
    *,
    formal_statement: str,
    current_proof: str,
    current_goal_state: str,
) -> str:
    tactics = _parse_tactic_output(raw_output)
    _validate_fill_tactics(
        tactics,
        formal_statement=formal_statement,
        current_proof=current_proof,
        current_goal_state=current_goal_state,
    )
    return tactics


def _validate_fill_tactics(
    tactics: str,
    *,
    formal_statement: str,
    current_proof: str,
    current_goal_state: str,
) -> None:
    lines = [line.strip() for line in tactics.splitlines() if line.strip()]
    bare_lines = [re.sub(r"^(?:[-+*]\s+)?(?:(?:\d+|all)\s*:\s*)?", "", line).strip() for line in lines]
    custom_tactics_available = _custom_tactics_available_in_proof(formal_statement, current_proof)
    lra_available = _lra_tactic_available(formal_statement, current_proof)
    field_available = _field_tactic_available(formal_statement, current_proof)

    if not custom_tactics_available:
        forbidden = [
            line for line in bare_lines if re.match(r"^(?:simplify|assert_goal|pick)\b", line, re.IGNORECASE)
        ]
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

    if not lra_available:
        forbidden = [line for line in bare_lines if re.match(r"^(?:lra|nra)\b", line, re.IGNORECASE)]
        if forbidden:
            examples = "\n".join(forbidden[:3])
            raise ValueError(
                "Current proof does not import `Lra`/`Psatz`, but the fill used `lra.` or `nra.`.\n"
                f"Examples:\n{examples}"
            )

    if not field_available:
        forbidden = [line for line in bare_lines if re.match(r"^(?:field|field_simplify)\b", line, re.IGNORECASE)]
        if forbidden:
            examples = "\n".join(forbidden[:3])
            raise ValueError(
                "Current proof does not visibly import field support, but the fill used `field.` or `field_simplify`.\n"
                f"Examples:\n{examples}"
            )

    _, goal_text = _split_goal_state(current_goal_state)
    if re.search(r"\bforall\b|->", goal_text):
        if bare_lines and all(re.match(r"^(?:intro|intros|pick)\b", line, re.IGNORECASE) for line in bare_lines):
            raise ValueError(
                "Fill only introduces binders and does not solve the residual goal.\n"
                "Continue after `intros` until the marked subgoal is fully discharged."
            )


def _parse_skeleton_output(raw_output: str, *, formal_statement: str, angelito_proof: str) -> str:
    from pipeline.tactic_parser import extract_tactics

    skeleton = extract_tactics(raw_output, preserve_bullets=True)
    if not skeleton:
        raise ValueError(
            "Skeleton model did not return a valid Coq tactic block.\n"
            f"Raw output:\n{_truncate_for_error(raw_output)}"
        )
    # Auto-fix: replace `simplify lhs/rhs ... by admit.` or bare `simplify ...`
    # with `admit.` — the model is trying to use Angelito custom tactics as placeholders.
    skeleton = re.sub(
        r"^(\s*(?:[-+*]\s+)?)simplify\s+(?:lhs|rhs)\b.*$",
        r"\1admit.",
        skeleton,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    skeleton = _normalize_skeleton_structure(skeleton)
    nonempty_lines = [line.strip() for line in skeleton.splitlines() if line.strip()]
    if not nonempty_lines:
        raise ValueError("Skeleton model returned an empty proof body.")

    first_line = nonempty_lines[0].lower()
    needs_intros = "forall " in formal_statement or "->" in formal_statement
    if needs_intros and first_line.startswith(("induction ", "destruct ", "split.", "left.", "right.")):
        raise ValueError(
            "Skeleton is missing introductions before opening proof structure.\n"
            f"Raw output:\n{_truncate_for_error(raw_output)}"
        )

    if "admit." not in skeleton and len(nonempty_lines) == 1 and nonempty_lines[0].lower().startswith(
        ("induction ", "destruct ", "apply ", "split.")
    ):
        raise ValueError(
            "Skeleton opens subgoals but does not include any `admit.` placeholders.\n"
            f"Raw output:\n{_truncate_for_error(raw_output)}"
        )

    inline_admit_lines = [
        line.strip()
        for line in skeleton.splitlines()
        if "admit." in line and not _ADMIT_LINE_RE.match(line)
    ]
    if inline_admit_lines:
        examples = "\n".join(inline_admit_lines[:3])
        raise ValueError(
            "Skeleton must use standalone `admit.` placeholder lines only.\n"
            "Do not place `admit.` inside another tactic line (for example, `simplify lhs ... by admit.`).\n"
            "Replace inner proof work such as `simpl`, `rewrite`, `exact`, `reflexivity`, or `simplify ...` with `admit.`.\n"
            f"Examples:\n{examples}\n\n"
            f"Raw output:\n{_truncate_for_error(raw_output)}"
        )

    angelito_lines = [line.strip() for line in angelito_proof.splitlines() if line.strip()]
    allows_induction = any(line.startswith("INDUCTION ") for line in angelito_lines)
    allows_split_apply = any(line.startswith("APPLY ") and "SPLIT INTO:" in line for line in angelito_lines)

    if not allows_induction and any(re.sub(r"^[-+*]\s+", "", line).lower().startswith("induction ") for line in nonempty_lines):
        raise ValueError(
            "Skeleton introduced `induction` even though the Angelito proof has no `INDUCTION` step.\n"
            f"Raw output:\n{_truncate_for_error(raw_output)}"
        )

    invalid_lines = [
        line.strip()
        for line in skeleton.splitlines()
        if line.strip() and not _is_structural_skeleton_line(line, allows_split_apply=allows_split_apply)
    ]
    if invalid_lines:
        examples = "\n".join(invalid_lines[:3])
        raise ValueError(
            "Skeleton must contain only outer proof structure and standalone `admit.` leaves.\n"
            "Replace inner proof work such as `simpl`, `rewrite`, `exact`, `reflexivity`, or `simplify ...` with `admit.`.\n"
            f"Examples:\n{examples}\n\n"
            f"Raw output:\n{_truncate_for_error(raw_output)}"
        )

    _validate_skeleton_tactics(
        skeleton,
        formal_statement=formal_statement,
    )

    return skeleton


def _extract_angelito_block(text: str) -> str:
    lines = [_normalize_angelito_line_wrappers(line) for line in text.splitlines()]
    prove_idx = next((i for i, line in enumerate(lines) if line.strip().startswith("PROVE ")), None)
    if prove_idx is not None:
        for end_idx in range(len(lines) - 1, prove_idx - 1, -1):
            if lines[end_idx].strip() == "END":
                return "\n".join(lines[prove_idx:end_idx + 1]).strip()
    return text.strip()


def _normalize_angelito_line_wrappers(line: str) -> str:
    stripped = line.strip()
    if stripped.startswith("[PROVE "):
        return line.replace("[PROVE ", "PROVE ", 1)
    if stripped == "END]":
        return line.replace("END]", "END")
    return line


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
        (idx for idx in range(len(normalized) - 1, -1, -1) if _ADMIT_LINE_RE.match(normalized[idx])),
        -1,
    )
    # Only strip trailing lines that are clearly not part of the proof
    # (e.g. model commentary). Keep structural lines like `}`, `exact`, `Qed.`.
    if last_admit_idx >= 0:
        trailing_nonempty = [line for line in normalized[last_admit_idx + 1 :] if line.strip()]
        structural_re = re.compile(
            r"^\s*(?:[-+*{}]+\s*$|}\s*$|exact\b|assumption\b|trivial\b|auto\b|Qed\b|Defined\b)",
            re.IGNORECASE,
        )
        if trailing_nonempty and not any(structural_re.match(l) for l in trailing_nonempty):
            normalized = normalized[: last_admit_idx + 1]

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


def _validate_skeleton_tactics(
    skeleton: str,
    *,
    formal_statement: str,
) -> None:
    lines = [line.strip() for line in skeleton.splitlines() if line.strip()]
    bare_lines = [re.sub(r"^[-+*]\s+", "", line).strip() for line in lines]

    custom_tactics_available = _custom_tactics_available_in_proof(formal_statement)
    if not custom_tactics_available:
        forbidden = [
            line for line in bare_lines if re.match(r"^(?:assert_goal|pick|simplify)\b", line, re.IGNORECASE)
        ]
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
        if any(token in line for token in ("∑", "sum_{", "card {"))
        or re.search(r"\{[^{}\n]*\|", line)
    ]
    if pseudo_math_lines:
        examples = "\n".join(pseudo_math_lines[:3])
        raise ValueError(
            "Skeleton contains pseudo-mathematical notation that is not valid Rocq syntax.\n"
            "Do not emit set-builder notation like `card {a | ...}` or sigma notation like `sum_{...}`. "
            "Translate the checkpoint into valid Rocq syntax or use a coarser valid intermediate assertion instead.\n"
            f"Examples:\n{examples}"
        )


def _focused_proof_state(state_text: str) -> str:
    if not state_text.strip():
        return ""
    kept: list[str] = []
    for line in state_text.splitlines():
        if (
            "This subproof is complete" in line
            or "Focus next goal with bullet" in line
            or "No more goals, but there are some goals you gave up:" in line
            or "No more goals." in line
            or re.match(r"^\s*goal\s+\d+\s+is:\s*$", line, re.IGNORECASE)
        ):
            break
        kept.append(line)
    return "\n".join(kept).strip()


_TERMINAL_TACTIC_RE = re.compile(
    r"^(?:lia|nia|ring|reflexivity|easy|trivial|assumption|auto)\.\s*$"
    r"|^exact\b.*\.\s*$",
    re.IGNORECASE,
)


def _trim_terminal_tactic_suffix(tactics: str) -> str:
    lines = [line.rstrip() for line in tactics.splitlines() if line.strip()]
    for idx, line in enumerate(lines):
        if _TERMINAL_TACTIC_RE.match(line.strip()):
            return "\n".join(lines[: idx + 1])
    return "\n".join(lines)


def _generate_with_format_retries(
    model_value: Union[str, list],
    prompt: str,
    config: dict,
    *,
    stage: str,
    parser,
    debug_attempts: Optional[list[dict]] = None,
    log_metadata: Optional[dict] = None,
    formal_statement: str = "",
) -> str:
    max_attempts = int(config.get("format_retries", 3))
    current_prompt = prompt
    errors: list[str] = []
    debug_enabled = bool(config.get("debug"))
    debug_limit = int(config.get("debug_char_limit", 500))
    if debug_enabled:
        print(
            f"[DEBUG:{stage}] format retries enabled, max_attempts={max_attempts}, "
            f"prompt_chars={len(prompt)}",
            flush=True,
        )
        print(f"[DEBUG:{stage}] prompt preview:\n{_preview_text(prompt, limit=debug_limit)}", flush=True)
    for attempt in range(1, max_attempts + 1):
        if debug_enabled:
            print(f"[DEBUG:{stage}] model-format attempt {attempt}/{max_attempts}", flush=True)
        # Use higher temperature on retries to avoid repeating the same output
        attempt_config = config
        if attempt > 1:
            attempt_config = dict(config)
            attempt_config["temperature"] = max(config.get("temperature", 0.0), 0.4)
        out, resolved_model = _chat_with_model_fallback(
            model_value,
            current_prompt,
            attempt_config,
            stage=stage,
            metadata={**(log_metadata or {}), "format_attempt": attempt},
        )
        attempt_info = {
            "format_attempt": attempt,
            "model": resolved_model,
            "raw_output": out,
        }
        if debug_enabled:
            print(
                f"[DEBUG:{stage}] model={resolved_model}, raw_chars={len(out)}",
                flush=True,
            )
            print(
                f"[DEBUG:{stage}] raw output preview:\n{_preview_text(out, limit=debug_limit)}",
                flush=True,
            )
        try:
            parsed = parser(out)
            attempt_info["status"] = "parsed"
            attempt_info["parsed_output"] = parsed
            if debug_enabled:
                print(
                    f"[DEBUG:{stage}] parser success, parsed_chars={len(parsed)}",
                    flush=True,
                )
                print(
                    f"[DEBUG:{stage}] parsed preview:\n{_preview_text(parsed, limit=debug_limit)}",
                    flush=True,
                )
            if debug_attempts is not None:
                debug_attempts.append(attempt_info)
            return parsed
        except Exception as e:
            attempt_info["status"] = "invalid_format"
            attempt_info["error"] = str(e)
            if debug_enabled:
                print(f"[DEBUG:{stage}] parser failure: {e}", flush=True)
            if debug_attempts is not None:
                debug_attempts.append(attempt_info)
            errors.append(f"Attempt {attempt}: {e}")
            if attempt == max_attempts:
                break
            retry_guidance = _retry_guidance_for_stage(stage, str(e), formal_statement=formal_statement)
            current_prompt = (
                prompt
                + "\n\nYour previous output was invalid.\n"
                + f"Reason: {e}\n"
                + (retry_guidance + "\n" if retry_guidance else "")
                + "Return a corrected answer from scratch that follows the required output format exactly.\n"
                + "Do not explain. Do not analyze. Output only the required final artifact.\n"
            )
            print(f"  Warning: {stage} output had invalid format, retrying ({attempt}/{max_attempts - 1})...", flush=True)
    raise RuntimeError(f"{stage} failed format validation:\n  - " + "\n  - ".join(errors))


_ANGELITO_KEYWORDS = {
    "PROVE",
    "BEGIN",
    "END",
    "ASSUME",
    "GOAL",
    "SIMPLIFY",
    "APPLY",
    "SPLIT",
    "INDUCTION",
    "FACT",
    "WITNESS_AT",
    "FOR_ALL",
    "EXTRACT",
    "SINCE",
    "THEREFORE",
    "CONCLUDE",
    "INDUCTIVE_HYPOTHESIS",
}


_FORBIDDEN_ANGELITO_CONTINUATION_RE = re.compile(
    r"^(?:```|~~~|#{1,6}\s|/\*|\*/|//)"
    r"|^(?:Proof|Qed|Admitted)\.\s*$"
    r"|^(?:intro|intros|rewrite|apply|eapply|exact|reflexivity|lia|nia|ring|"
    r"simpl|cbn|destruct|induction|split|left|right)\b",
    re.IGNORECASE,
)


def _is_angelito_continuation_line(line: str, *, continuation_mode: Optional[str], split_into_re) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if continuation_mode == "split_into":
        return bool(split_into_re.match(stripped))
    if _FORBIDDEN_ANGELITO_CONTINUATION_RE.match(stripped):
        return False
    return True


def _validate_angelito_rewrite(text: str, *, informal_proof: str = "", formal_statement: str = "") -> None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("Rewrite model returned empty output.")
    if not lines[0].startswith("PROVE "):
        raise ValueError(
            "Rewrite output is not strict Angelito: first non-empty line must start with 'PROVE '.\n"
            f"Raw output:\n{_truncate_for_error(text)}"
        )
    if "BEGIN" not in lines:
        raise ValueError(
            "Rewrite output is not strict Angelito: expected BEGIN line after PROVE.\n"
            f"Raw output:\n{_truncate_for_error(text)}"
        )
    if lines[-1] != "END":
        raise ValueError(
            "Rewrite output is not strict Angelito: missing final END line.\n"
            "The proof was likely cut off or continued past the required outer block. "
            "Return a shorter proof that ends with END.\n"
            f"Raw output:\n{_truncate_for_error(text)}"
        )
    if not any(line.startswith("CONCLUDE") for line in lines):
        raise ValueError(
            "Rewrite output is not strict Angelito: expected at least one CONCLUDE line.\n"
            f"Raw output:\n{_truncate_for_error(text)}"
        )

    bad_lines: list[str] = []
    continuation_mode: Optional[str] = None
    split_into_re = re.compile(r"^\(\d+\)\s+[A-Za-z0-9_]+:\s+.+$")
    for line in lines:
        keyword = line.split()[0].rstrip(":")
        if keyword in _ANGELITO_KEYWORDS:
            continuation_mode = None
            if keyword in {"SIMPLIFY", "GOAL", "THEREFORE", "FACT", "SINCE"}:
                continuation_mode = "default"
            elif keyword == "APPLY" and "SPLIT INTO:" in line:
                continuation_mode = "split_into"
            continue
        if _is_angelito_continuation_line(
            line,
            continuation_mode=continuation_mode,
            split_into_re=split_into_re,
        ):
            continue
        continuation_mode = None
        bad_lines.append(line)
    if bad_lines:
        joined = "\n".join(bad_lines[:5])
        raise ValueError(
            "Rewrite output contains non-Angelito lines.\n"
            f"Examples:\n{joined}\n\n"
            f"Raw output:\n{_truncate_for_error(text)}"
        )

    # Reject pseudo-mathematical notation that cannot become valid Rocq.
    _PSEUDO_MATH_TOKENS = ("\u2211", "sum_{", "card {", "card{")
    _SET_BUILDER_RE = re.compile(r"\{[^{}\n]*\|[^{}\n]*\}")
    pseudo_math_lines = [
        line for line in lines
        if any(tok in line for tok in _PSEUDO_MATH_TOKENS)
        or _SET_BUILDER_RE.search(line)
    ]
    if pseudo_math_lines:
        examples = "\n".join(pseudo_math_lines[:3])
        raise ValueError(
            "Rewrite contains pseudo-mathematical notation that cannot be translated to valid Rocq.\n"
            "Do not use set-builder notation like `card {a | ...}`, sigma notation like `sum_{...}` or `\u2211`, "
            "or set comprehensions like `{x | P x}`. "
            "Express counting and summation arguments in words or with named helper facts instead.\n"
            f"Examples:\n{examples}"
        )

    # Reject natural-language prose in FACT/THEREFORE content that cannot be
    # translated into a Rocq proposition.  The skeleton model needs each FACT
    # body to be a symbolic statement (equation, inequality, quantified
    # formula) — not an English sentence.
    _NL_PROSE_RE = re.compile(
        r"\b(?:for each|for all|for every|there (?:are|is|exist[s]?)"
        r"|the (?:number|sum|total|count|product) of"
        r"|over all|sum over|summing)\b",
        re.IGNORECASE,
    )
    def _fact_body(line: str) -> str:
        """Return the proposition part of a FACT/THEREFORE line, stripping [BY ...] justification."""
        by_idx = line.find("[BY ")
        return line[:by_idx] if by_idx != -1 else line

    prose_fact_lines = [
        line for line in lines
        if line.split()[0].rstrip(":") in {"FACT", "THEREFORE"}
        and _NL_PROSE_RE.search(_fact_body(line))
    ]
    if prose_fact_lines:
        examples = "\n".join(prose_fact_lines[:3])
        raise ValueError(
            "Rewrite contains natural-language prose inside FACT or THEREFORE lines.\n"
            "Each FACT must state a symbolic proposition that can become a Rocq `assert`, "
            "not an English sentence. Use quantifiers like `\u2200` and symbolic expressions "
            "instead of phrases like 'for each', 'there are', or 'the number of'.\n"
            "Example fix: replace `FACT h: for each integer a, P(a) [BY ...]` "
            "with `FACT h: \u2200 a : nat, P a [BY ...]`.\n"
            f"Examples:\n{examples}"
        )

    if informal_proof.strip():
        informal_lower = informal_proof.lower()
        informal_tokens = re.findall(r"\S+", informal_proof)
        answer_only = len(informal_tokens) <= 8 and len(informal_proof.strip().splitlines()) <= 2
        mentions_induction = any(token in informal_lower for token in ("induction", "inductive", "base case"))
        has_induction = any(line.startswith("INDUCTION ") for line in lines)
        has_split_apply = any(line.startswith("APPLY ") and "SPLIT INTO:" in line for line in lines)
        nested_proves = [line for line in lines[1:] if line.startswith("PROVE ")]

        if has_induction and not mentions_induction:
            raise ValueError(
                "Rewrite introduced INDUCTION even though the informal proof does not indicate an inductive proof shape.\n"
                "Keep the Angelito proof faithful to the given proof strategy.\n"
                f"Raw output:\n{_truncate_for_error(text)}"
            )

        if answer_only:
            if has_split_apply or has_induction or nested_proves:
                raise ValueError(
                    "Informal proof is answer-only, but rewrite invented branching structure or nested subproofs.\n"
                    "Use a compact direct Angelito proof instead of introducing new cases or induction.\n"
                    f"Raw output:\n{_truncate_for_error(text)}"
                )
            assume_lines = sum(1 for l in lines if l.startswith("ASSUME "))
            if len(lines) - assume_lines > 24:
                raise ValueError(
                    "Informal proof is answer-only, but rewrite is overexpanded.\n"
                    "Use a short direct Angelito proof with only the decisive steps.\n"
                    f"Raw output:\n{_truncate_for_error(text)}"
                )


def _extract_prebound_names(formal_statement: str) -> list[str]:
    """Extract variable/hypothesis names already bound in the theorem signature.

    For ``Theorem foo (x a : nat -> R) (H0 : ...) : goal`` returns ['x', 'a', 'H0'].
    """
    m = re.search(
        r"(?:Theorem|Lemma|Proposition|Corollary|Fact|Example)\s+\S+\s*",
        formal_statement,
    )
    if not m:
        return []
    rest = formal_statement[m.end():]
    # Walk rest, tracking paren depth, to find the ':' that starts the return type
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
        for name in name_part.split():
            if re.match(r"^[A-Za-z_][A-Za-z0-9_\']*$", name):
                names.append(name)
    return names

def _retry_guidance_for_stage(stage: str, error: str, *, formal_statement: str = "") -> str:
    lowered = error.lower()
    if stage == "rewrite":
        hints = [
            "Rewrite repair rules:",
            "- Keep the Angelito proof short and structure-first.",
            "- Only preserve outer proof structure needed by later stages.",
            "- Collapse routine algebra or computation into one FACT or THEREFORE line instead of long equality chains.",
            "- Avoid nested APPLY ... SPLIT INTO or INDUCTION unless the informal proof genuinely uses them.",
            "- Output only the Angelito proof, starting with PROVE and ending with END.",
        ]

        if "missing final end line" in lowered or "expected begin line" in lowered:
            hints.append("- Your previous answer was likely cut off. Return a shorter proof with fewer lines.")
        if "non-angelito lines" in lowered:
            hints.append("- Put continuation text directly under the preceding Angelito keyword; do not add commentary outside that structure.")
        if "answer-only" in lowered:
            hints.append("- The informal proof is only an answer, so do not invent induction, cases, or nested subproofs.")
        if "introduced induction" in lowered:
            hints.append("- Do not use INDUCTION unless the informal proof explicitly says to argue by induction.")
        if "pseudo-mathematical notation" in lowered:
            hints.append("- Do not use set-builder notation like `card {a | ...}`, sigma notation like `sum_{...}` or \u2211, or set comprehensions like `{x | P x}`.")
            hints.append("- Express counting and summation using symbolic Rocq-like notation instead.")
        if "natural-language prose" in lowered:
            hints.append("- Every FACT and THEREFORE must be a symbolic proposition, not an English sentence.")
            hints.append("- Replace `for each integer a, P(a)` with `\u2200 a : nat, P a`.")
            hints.append("- Replace `there are N things with property P` with a direct equation or inequality.")
            hints.append("- If a fact cannot be stated as a symbolic Rocq-like proposition, collapse it into a coarser step or drop it.")
        return "\n".join(hints)

    if stage == "fill_goal":
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

    if stage == "skeleton":
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

        # Compile-error-specific guidance
        if "already used" in lowered:
            prebound = _extract_prebound_names(formal_statement)
            hints.append(
                "- The Coq error `x is already used` means you tried to `intros` a name that is already "
                "bound in the theorem signature. Do NOT re-introduce names that appear as theorem parameters."
            )
            if prebound:
                names_str = ", ".join(prebound)
                hints.append(f"- These names are already in scope from the theorem statement: {names_str}")
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

        return "\n".join(hints)

    return ""


def _normalize_formal_statement(text: str) -> str:
    lines = text.splitlines()
    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        if re.match(r"^(Proof|Qed|Admitted)\.\s*$", stripped):
            break
        kept.append(line.rstrip())
    normalized = "\n".join(kept).strip()
    if not normalized:
        raise ValueError("Formal statement is empty after removing trailing proof commands.")
    return normalized


def _ensure_generated_imports(formal_statement: str, target_path: Path) -> str:
    lines = formal_statement.splitlines()
    leading_imports: list[str] = []
    body_start = 0
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            leading_imports.append(line.rstrip())
            continue
        if re.match(r"^(Require|From|Import)\b", stripped):
            leading_imports.append(line.rstrip())
            continue
        body_start = idx
        break
    else:
        body_start = len(lines)

    normalized_imports = [line.strip() for line in leading_imports if line.strip()]
    joined_imports = " ".join(normalized_imports)

    generated_imports: list[str] = []

    # Auto-add Lia when Arith or ZArith is imported
    _has_lia = any(m in joined_imports for m in ("Require Import Lia.", "From Coq Require Import Lia."))
    _has_arith_or_z = any(m in joined_imports for m in (
        "Require Import Arith.", "From Coq Require Import Arith.",
        "Require Import ZArith.", "From Coq Require Import ZArith.",
    ))
    if _has_arith_or_z and not _has_lia:
        generated_imports.append("Require Import Lia.")

    # Auto-add Lra and Psatz when Reals or Coquelicot is imported
    _has_reals = any(m in joined_imports for m in (
        "Require Import Reals.", "From Coq Require Import Reals.",
        "Require Import Coquelicot.", "From Coq Require Import Coquelicot.",
        "Coquelicot.Coquelicot",
    ))
    _has_lra = any(m in joined_imports for m in (
        "Require Import Lra.", "From Coq Require Import Lra.",
        "Require Import Psatz.", "From Coq Require Import Psatz.",
    ))
    if _has_reals and not _has_lra:
        generated_imports.append("Require Import Lra.")
        generated_imports.append("Require Import Psatz.")

    # Auto-add Field when Reals is imported but Field is missing
    _has_field = any(m in joined_imports for m in (
        "Require Import Field.", "From Coq Require Import Field.",
        "Require Import Ring.", "From Coq Require Import Ring.",
    ))
    if _has_reals and not _has_field:
        generated_imports.append("Require Import Field.")

    prefix = [line for line in leading_imports if line.strip()]
    if generated_imports:
        prefix.extend(generated_imports)
    body = [line.rstrip() for line in lines[body_start:] if line.rstrip() or line == ""]
    sections: list[str] = []
    if prefix:
        sections.append("\n".join(prefix).strip())
    if body:
        sections.append("\n".join(body).strip())
    return "\n\n".join(section for section in sections if section).strip()
def _as_model_list(model_value: Union[str, list]) -> list[str]:
    if isinstance(model_value, list):
        models = [str(m).strip() for m in model_value if str(m).strip()]
        if not models:
            raise ValueError("Model list is empty in config.")
        return models
    model = str(model_value).strip()
    if not model:
        raise ValueError("Model is empty in config.")
    return [model]


def _is_retryable_model_error(msg: str) -> bool:
    m = msg.lower()
    return any(s in m for s in [
        "open router api error 404", "open router api error 408",
        "open router api error 429", "open router api error 500",
        "open router api error 502", "open router api error 503",
        "open router api error 504", "open router request failed",
        "no endpoints found",
        "returned an empty message",
    ])


def _chat_with_model_fallback(
    model_value: Union[str, list],
    prompt: str,
    config: dict,
    *,
    stage: str,
    metadata: Optional[dict] = None,
) -> tuple[str, str]:
    from pipeline.openrouter_client import chat

    models = _as_model_list(model_value)
    errors = []
    debug_enabled = bool(config.get("debug"))
    debug_limit = int(config.get("debug_char_limit", 500))
    if debug_enabled:
        print(
            f"[DEBUG:{stage}] trying models in order: {models}",
            flush=True,
        )
    for i, model in enumerate(models):
        try:
            if debug_enabled:
                print(
                    f"[DEBUG:{stage}] invoking model {i + 1}/{len(models)}: {model}",
                    flush=True,
                )
            response = chat(
                model,
                prompt,
                max_tokens=config.get("max_tokens", 4096),
                temperature=config.get("temperature", 0.3),
                timeout=config.get("request_timeout_sec", 60),
                retries=config.get("request_retries", 4),
                backoff_base_sec=config.get("request_backoff_base_sec", 1.5),
                backoff_multiplier=config.get("request_backoff_multiplier", 2.0),
                backoff_max_sec=config.get("request_backoff_max_sec", 20.0),
                backoff_jitter_sec=config.get("request_backoff_jitter_sec", 0.35),
                log_path=Path(config["model_log_path"]) if config.get("model_log_path") else None,
                metadata={
                    "stage": stage,
                    "model_index": i + 1,
                    "model_count": len(models),
                    **(metadata or {}),
                },
            )
            if debug_enabled:
                print(
                    f"[DEBUG:{stage}] model succeeded: {model}, response_chars={len(response)}",
                    flush=True,
                )
                print(
                    f"[DEBUG:{stage}] response preview:\n{_preview_text(response, limit=debug_limit)}",
                    flush=True,
                )
            return response, model
        except Exception as e:
            msg = str(e)
            errors.append(f"{model}: {msg}")
            if debug_enabled:
                print(f"[DEBUG:{stage}] model failure from {model}: {msg}", flush=True)
            if i == len(models) - 1 or not _is_retryable_model_error(msg):
                break
            print(f"  Warning: {stage} failed with '{model}', trying fallback...", flush=True)
    raise RuntimeError(f"{stage} failed:\n  - " + "\n  - ".join(errors))


def _default_trace_path() -> Path:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    return REPO_ROOT / "pipeline" / "traces" / f"run-{ts}.json"


def _default_model_log_path(trace_path: Path) -> Path:
    return trace_path.with_name(f"{trace_path.stem}-model-log.jsonl")


def _write_trace(trace_path: Path, trace: dict) -> None:
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text(json.dumps(trace, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# CoqEditor helpers
# ---------------------------------------------------------------------------

def _format_proof_file_content(formal_statement: str, proof_body: str, use_admitted: bool) -> str:
    """Full .v contents: lemma/theorem, Proof., indented body, Qed./Admitted."""
    closing = "Admitted." if use_admitted else "Qed."
    indented = []
    for line in proof_body.splitlines():
        if line.strip():
            indented.append(f"  {line.rstrip()}")
        else:
            indented.append("")
    return f"{formal_statement}\nProof.\n" + "\n".join(indented) + f"\n{closing}\n"


def _write_proof_to_file(target_path: Path, formal_statement: str, proof_body: str, use_admitted: bool):
    """Write a .v file with the formal statement, Proof., proof body, and Qed./Admitted."""
    content = _format_proof_file_content(formal_statement, proof_body, use_admitted)
    target_path.write_text(content, encoding="utf-8")


def _proof_body_line_to_file_cursor(
    formal_statement: str,
    proof_body_line_index: int,
    *,
    target_path: Optional[Path] = None,
    before_line: bool = False,
) -> int:
    """
    Convert a 0-based proof-body line index to a 1-based file cursor line.

    When `before_line=True`, the cursor points to the previous body line so Coq
    snapshots show the goal *before* executing the target tactic/admit line.
    """
    line_index = proof_body_line_index - 1 if before_line else proof_body_line_index
    if line_index < 0:
        line_index = 0

    # Prefer anchoring to the generated file because imports/header shaping can
    # shift the theorem body away from a pure formal_statement-based offset.
    if target_path is not None and target_path.exists():
        file_lines = target_path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(file_lines):
            if line.strip() == "Proof.":
                return i + 2 + line_index

    return len(formal_statement.splitlines()) + 2 + line_index


def _should_snapshot_before_line(proof_body: str, proof_body_line_index: int) -> bool:
    if proof_body_line_index < 0:
        return True

    lines = proof_body.splitlines()
    if proof_body_line_index >= len(lines):
        return True

    target = lines[proof_body_line_index].lstrip()
    # Bullet-prefixed admits focus a new branch at the admit line itself, so
    # sampling the previous line can leave us stuck in the earlier branch.
    return not target.startswith(("-", "+", "*"))


def _capture_goal_state_after_replacement(
    *,
    repo_root: Path,
    target_rel: str,
    target_path: Path,
    formal_statement: str,
    admit_idx: int,
    replacement: str,
) -> str:
    replacement_line_count = max(1, len(replacement.splitlines()))
    cursor_line = _proof_body_line_to_file_cursor(
        formal_statement,
        admit_idx + replacement_line_count - 1,
        target_path=target_path,
        before_line=False,
    )
    return _focused_proof_state(
        run_get_proof_state(repo_root, target_rel, cursor_line)
    )


def _parse_structured_error(stderr: str, stdout: str) -> str:
    """Extract useful error info from coqc output."""
    raw = (stderr or stdout).strip()
    if not raw:
        return ""
    # Look for "Error:" lines and grab everything until the next blank line
    # or end of output — this captures the full error including environment.
    lines = raw.splitlines()
    error_lines = []
    in_error = False
    for i, line in enumerate(lines):
        if "Error:" in line or "error:" in line.lower():
            start = max(0, i - 2)
            error_lines.extend(lines[start:i])
            in_error = True
        if in_error:
            error_lines.append(line)
            # Stop at "Proof check failed" or end of meaningful content
            if line.strip() == "" or "Proof check failed" in line:
                error_lines.append("---")
                in_error = False
    if in_error:
        error_lines.append("---")
    if error_lines:
        return "\n".join(error_lines)
    return raw


def _build_structured_feedback_context(stdout: str, stderr: str) -> tuple[list[dict[str, str]], str]:
    from pipeline.compiler_feedback import extract_compiler_feedback, format_compiler_feedback

    feedback = extract_compiler_feedback(stdout or "", stderr or "")
    return feedback, format_compiler_feedback(feedback)


# ---------------------------------------------------------------------------
# Import verification
# ---------------------------------------------------------------------------

def _extract_imports(formal_statement: str) -> list[str]:
    """Extract Require Import / From ... Require Import lines from the formal statement."""
    imports = []
    for line in formal_statement.splitlines():
        stripped = line.strip()
        if re.match(r"^(?:Require\s+Import|From\s+\S+\s+Require\s+Import)\b", stripped):
            imports.append(stripped)
    return imports


def _verify_imports(
    imports: list[str],
    repo_root: Path,
    *,
    timeout_sec: int = 30,
) -> list[dict]:
    """Test each import line by writing a temp .v file and compiling with coqc."""
    from scripts.coq_script_utils import resolve_coqc, parse_coqproject

    coqc = resolve_coqc()
    coq_args, _ = parse_coqproject(repo_root)
    results = []
    # Use a relative path in repo root so Windows coqc can resolve it
    tmp_name = "_import_check_tmp.v"
    tmp_path = repo_root / tmp_name
    try:
        for imp in imports:
            try:
                tmp_path.write_text(imp + "\n", encoding="utf-8")
                proc = subprocess.run(
                    [coqc, *coq_args, tmp_name],
                    cwd=str(repo_root),
                    capture_output=True,
                    text=True,
                    timeout=timeout_sec,
                )
                ok = proc.returncode == 0
                error = (proc.stderr or "").strip() if not ok else ""
            except subprocess.TimeoutExpired:
                ok = False
                error = f"Timed out after {timeout_sec}s"
            except Exception as e:
                ok = False
                error = str(e)
            results.append({"import": imp, "ok": ok, "error": error})
    finally:
        tmp_path.unlink(missing_ok=True)
        for ext in (".vo", ".vok", ".vos", ".glob"):
            (repo_root / f"_import_check_tmp{ext}").unlink(missing_ok=True)
    return results


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    from pipeline.proof_template import (
        build_proof_template,
        count_rendered_admits,
        find_marked_admit_line,
    )

    parser = argparse.ArgumentParser(
        description="Proof pipeline: informal -> Angelito -> Rocq skeleton -> iterative fill"
    )
    parser.add_argument("--informal", type=Path, required=True, help="Informal proof text file")
    parser.add_argument("--formal", type=Path, required=True, help="Formal Coq statement file")
    parser.add_argument("--target", type=Path, default=Path("coq/CongModEq.v"), help="Target .v file")
    parser.add_argument("--max-fill-attempts", type=int, default=None, help="Max retries per admit fill")
    parser.add_argument("--trace-out", type=Path, default=None, help="JSON trace output path")
    parser.add_argument("--debug", action="store_true", help="Emit verbose debugging logs")
    parser.add_argument(
        "--debug-char-limit",
        type=int,
        default=500,
        help="Max chars per debug preview log",
    )
    args = parser.parse_args()

    config = load_config()
    config["debug"] = args.debug
    config["debug_char_limit"] = args.debug_char_limit
    max_fill = args.max_fill_attempts or config.get("max_fill_attempts", 3)
    max_skeleton_attempts = int(config.get("max_skeleton_attempts", 3))

    repo_root = REPO_ROOT
    target_path = args.target if args.target.is_absolute() else repo_root / args.target
    informal_path = args.informal if args.informal.is_absolute() else repo_root / args.informal
    formal_path = args.formal if args.formal.is_absolute() else repo_root / args.formal
    trace_path = args.trace_out or _default_trace_path()
    if not trace_path.is_absolute():
        trace_path = repo_root / trace_path
    model_log_path = _default_model_log_path(trace_path)
    if model_log_path.exists():
        model_log_path.unlink()
    config["model_log_path"] = str(model_log_path)

    if args.target.is_absolute():
        target_rel = str(target_path)
    else:
        target_rel = str(args.target).replace("\\", "/")

    trace: dict = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "status": "running",
        "inputs": {"informal": str(informal_path), "formal": str(formal_path),
                    "target": str(target_path), "target_rel": target_rel},
        "config": {
            "max_fill_attempts": max_fill,
            "max_skeleton_attempts": max_skeleton_attempts,
            "rewrite_model": _as_model_list(config["rewrite_model"]),
            "skeleton_model": _as_model_list(config["skeleton_model"]),
            "fill_model": _as_model_list(config["fill_model"]),
            "request_retries": config.get("request_retries", 4),
            "request_backoff_base_sec": config.get("request_backoff_base_sec", 1.5),
            "request_backoff_multiplier": config.get("request_backoff_multiplier", 2.0),
            "request_backoff_max_sec": config.get("request_backoff_max_sec", 20.0),
            "request_backoff_jitter_sec": config.get("request_backoff_jitter_sec", 0.35),
        },
        "model_log_path": str(model_log_path),
        "rewrite": {},
        "skeleton": {},
        "fills": [],
        "summary": {},
    }
    if args.debug:
        trace["debug"] = {"enabled": True, "char_limit": args.debug_char_limit}

    def persist():
        _write_trace(trace_path, trace)

    def fail(msg: str):
        trace["status"] = "failed"
        trace["error"] = msg
        trace["ended_at"] = datetime.now().isoformat(timespec="seconds")
        persist()
        print(msg, file=sys.stderr)
        print(f"Trace: {trace_path}")
        sys.exit(1)

    if not informal_path.exists():
        fail(f"Error: informal proof not found: {informal_path}")
    if not formal_path.exists():
        fail(f"Error: formal statement not found: {formal_path}")
    if args.debug:
        print("[DEBUG] pipeline inputs", flush=True)
        print(f"[DEBUG] informal path: {informal_path}", flush=True)
        print(f"[DEBUG] formal path:   {formal_path}", flush=True)
        print(f"[DEBUG] target path:   {target_path}", flush=True)
        print(f"[DEBUG] trace path:    {trace_path}", flush=True)
        print(f"[DEBUG] model log:     {model_log_path}", flush=True)

    try:
        formal_statement = _normalize_formal_statement(formal_path.read_text(encoding="utf-8"))
        formal_statement = _ensure_generated_imports(formal_statement, target_path)
    except Exception as e:
        fail(f"Formal statement normalization failed: {e}")
    persist()
    if args.debug:
        print(
            f"[DEBUG] normalized formal statement chars={len(formal_statement)}",
            flush=True,
        )
        print(
            f"[DEBUG] formal statement preview:\n{_preview_text(formal_statement, limit=args.debug_char_limit)}",
            flush=True,
        )

    # ------------------------------------------------------------------
    # Pre-flight: verify all imports resolve
    # ------------------------------------------------------------------
    import_lines = _extract_imports(formal_statement)
    if import_lines:
        print("Verifying imports...", flush=True)
        try:
            import_results = _verify_imports(import_lines, repo_root)
        except Exception as e:
            print(f"  Warning: import verification skipped ({e})", flush=True)
            import_results = None
        if import_results is not None:
            trace["import_check"] = import_results
            failed_imports = [r for r in import_results if not r["ok"]]
            if failed_imports:
                msgs = []
                for r in failed_imports:
                    msgs.append(f"  {r['import']}")
                    if r["error"]:
                        msgs.append(f"    -> {r['error']}")
                fail(
                    "Import verification failed. The following imports are not available:\n"
                    + "\n".join(msgs)
                    + "\n\nInstall the missing libraries before running the pipeline."
                )
        if args.debug:
            print(f"[DEBUG] all {len(import_lines)} imports verified OK", flush=True)
        print(f"  All {len(import_lines)} imports OK.", flush=True)
    persist()

    # ------------------------------------------------------------------
    # Step 1: Rewrite -> strict Angelito
    # ------------------------------------------------------------------
    print("Step 1: Rewrite -> Angelito...", flush=True)
    rewrite_attempts: list[dict] = []
    try:
        angelito_proof = run_rewrite(
            informal_path,
            formal_statement,
            config,
            debug_attempts=rewrite_attempts,
            log_metadata={"pipeline_call": "rewrite"},
        )
    except Exception as e:
        trace["rewrite"] = {"model_attempts": rewrite_attempts}
        persist()
        fail(f"Rewrite failed: {e}")
    trace["rewrite"] = {"text": angelito_proof, "model_attempts": rewrite_attempts}
    persist()
    print("  Done.", flush=True)
    if args.debug:
        print(f"[DEBUG] rewrite model attempts={len(rewrite_attempts)}", flush=True)
        print(
            f"[DEBUG] angelito chars={len(angelito_proof)} preview:\n"
            f"{_preview_text(angelito_proof, limit=args.debug_char_limit)}",
            flush=True,
        )

    # ------------------------------------------------------------------
    # Step 2: Skeleton (Angelito -> Rocq with admit. placeholders)
    # ------------------------------------------------------------------
    print("Step 2: Skeleton generation...", flush=True)
    trace["skeleton"] = {"compile_attempts": []}
    persist()

    skeleton_error_context = ""
    skeleton_structured_feedback = ""
    skeleton = ""
    rendered_skeleton = ""
    has_admits = True
    proof_template = None
    slot_values: dict[str, Optional[str]] = {}
    step2_success = False
    last_skeleton_output = ""

    for skeleton_attempt in range(1, max_skeleton_attempts + 1):
        if skeleton_attempt > 1:
            print(
                f"  Skeleton compile retry {skeleton_attempt}/{max_skeleton_attempts}...",
                flush=True,
            )
        # Bump temperature on skeleton compile retries to avoid identical output
        skeleton_config = config
        if skeleton_attempt > 1:
            skeleton_config = dict(config)
            skeleton_config["temperature"] = max(config.get("temperature", 0.0), 0.4)
        skeleton_model_attempts: list[dict] = []
        try:
            skeleton = run_skeleton(
                formal_statement,
                angelito_proof,
                skeleton_config,
                error_context=skeleton_error_context,
                structured_feedback=skeleton_structured_feedback,
                debug_attempts=skeleton_model_attempts,
                log_metadata={"skeleton_compile_attempt": skeleton_attempt},
            )
        except Exception as e:
            trace["skeleton"]["compile_attempts"].append(
                {
                    "attempt": skeleton_attempt,
                    "status": "model_error",
                    "error": str(e),
                    "model_attempts": skeleton_model_attempts,
                }
            )
            persist()
            # Don't abort — continue to next compile attempt with higher temperature
            skeleton_error_context = (
                f"The previous skeleton attempt failed format validation: {e}\n\n"
                "Generate a corrected skeleton that uses only valid Rocq syntax."
            )
            continue

        proof_template = build_proof_template(skeleton, angelito_proof)
        slot_values = {slot.name: None for slot in proof_template.slots}
        rendered_skeleton = proof_template.render(slot_values)
        has_admits = proof_template.has_unfilled_slots(slot_values)
        _write_proof_to_file(target_path, formal_statement, rendered_skeleton, use_admitted=has_admits)
        if args.debug:
            print(
                f"[DEBUG] skeleton attempt {skeleton_attempt}: slots={len(proof_template.slots)}, "
                f"has_admits={has_admits}, rendered_chars={len(rendered_skeleton)}",
                flush=True,
            )
            print(
                f"[DEBUG] rendered skeleton preview:\n"
                f"{_preview_text(rendered_skeleton, limit=args.debug_char_limit)}",
                flush=True,
            )

        exit_code, stdout, stderr = run_check_target(repo_root, target_rel)
        last_skeleton_output = (stderr or stdout).strip()
        feedback, formatted_feedback = _build_structured_feedback_context(stdout, stderr)
        if args.debug:
            print(
                f"[DEBUG] skeleton check exit_code={exit_code}, stdout_chars={len(stdout)}, "
                f"stderr_chars={len(stderr)}, feedback_items={len(feedback)}",
                flush=True,
            )
            if stdout.strip():
                print(
                    f"[DEBUG] skeleton stdout preview:\n"
                    f"{_preview_text(stdout, limit=args.debug_char_limit)}",
                    flush=True,
                )
            if stderr.strip():
                print(
                    f"[DEBUG] skeleton stderr preview:\n"
                    f"{_preview_text(stderr, limit=args.debug_char_limit)}",
                    flush=True,
                )

        attempt_trace: dict = {
            "attempt": skeleton_attempt,
            "text": skeleton,
            "rendered_text": rendered_skeleton,
            "full_file_text": _format_proof_file_content(
                formal_statement, rendered_skeleton, use_admitted=has_admits
            ),
            "slot_names": [slot.name for slot in proof_template.slots],
            "model_attempts": skeleton_model_attempts,
            "status": "compiled" if exit_code == 0 else "compile_error",
            "compiles": exit_code == 0,
            "check_stdout": stdout.strip(),
            "stdout": stdout.strip(),
            "check_stderr": stderr.strip(),
            "stderr": stderr.strip(),
        }
        if feedback:
            attempt_trace["compiler_feedback"] = feedback
        if exit_code == 0 and has_admits:
            admit_lines = _find_admits(rendered_skeleton)
            if admit_lines:
                snapshot_before_line = _should_snapshot_before_line(rendered_skeleton, admit_lines[0])
                cursor_line = _proof_body_line_to_file_cursor(
                    formal_statement,
                    admit_lines[0],
                    target_path=target_path,
                    before_line=snapshot_before_line,
                )
                attempt_trace["proof_state"] = _focused_proof_state(
                    run_get_proof_state(repo_root, target_rel, cursor_line)
                )
                if args.debug:
                    print(
                        f"[DEBUG] skeleton proof-state cursor_line={cursor_line}, "
                        f"snapshot_before_line={snapshot_before_line}",
                        flush=True,
                    )
                    print(
                        f"[DEBUG] skeleton proof-state preview:\n"
                        f"{_preview_text(attempt_trace['proof_state'], limit=args.debug_char_limit)}",
                        flush=True,
                    )
        trace["skeleton"]["compile_attempts"].append(attempt_trace)
        persist()

        if exit_code == 0:
            step2_success = True
            trace["skeleton"].update(
                {
                    "text": skeleton,
                    "rendered_text": rendered_skeleton,
                    "full_file_text": _format_proof_file_content(
                        formal_statement, rendered_skeleton, use_admitted=has_admits
                    ),
                    "slot_names": [slot.name for slot in proof_template.slots],
                    "model_attempts": skeleton_model_attempts,
                    "compiles": True,
                    "check_stdout": stdout.strip(),
                    "stdout": stdout.strip(),
                    "check_stderr": stderr.strip(),
                    "stderr": stderr.strip(),
                }
            )
            if feedback:
                trace["skeleton"]["compiler_feedback"] = feedback
            break

        skeleton_error_context = (
            "The previous skeleton failed to compile.\n\n"
            f"**Failed skeleton tactics:**\n```coq\n{rendered_skeleton}\n```\n\n"
            f"**Coq compiler error:**\n```\n{_parse_structured_error(stderr, stdout)}\n```\n\n"
        )
        # Accumulate history of previous failed attempts so the model can
        # combine partial fixes instead of repeating the same mistakes.
        if skeleton_attempt >= 2 and trace["skeleton"]["compile_attempts"]:
            prev_attempts = []
            for prev in trace["skeleton"]["compile_attempts"][:-1]:
                if prev.get("status") == "compile_error":
                    prev_skel = prev.get("rendered_text", "")[:300]
                    prev_err = prev.get("stderr", prev.get("check_stderr", ""))[:200]
                    prev_attempts.append(f"```coq\n{prev_skel}\n```\nError: {prev_err}")
            if prev_attempts:
                skeleton_error_context += (
                    "**Earlier failed attempts (do not repeat these):**\n"
                    + "\n---\n".join(prev_attempts) + "\n\n"
                )
        # Add pre-bound name awareness for "already used" errors
        error_lower = (stderr + stdout).lower()
        prebound = _extract_prebound_names(formal_statement)
        if "already used" in error_lower and prebound:
            skeleton_error_context += (
                f"**Important:** The theorem signature already binds these names: {', '.join(prebound)}. "
                "Do NOT re-introduce them with `intros`. Use fresh names or omit `intros` for parameters "
                "that are already in scope.\n\n"
            )
        if re.search(r"has type.*while.*expected", error_lower):
            skeleton_error_context += (
                "**Important:** There is a type mismatch. Check that types in `assert` statements "
                "match the Coq functions used (e.g., `Int_part` returns `Z`, not `nat`).\n\n"
            )
        skeleton_error_context += "Generate a corrected skeleton that compiles when wrapped with this theorem and imports."
        skeleton_structured_feedback = formatted_feedback

    if not step2_success:
        fail(
            "Skeleton does not compile after retrying scaffold generation. "
            "Refusing to start fill retries on an invalid proof scaffold.\n"
            f"{last_skeleton_output}"
        )
    elif not has_admits:
        # Skeleton is already a complete proof!
        _write_proof_to_file(target_path, formal_statement, rendered_skeleton, use_admitted=False)
        trace["skeleton"]["full_file_text"] = _format_proof_file_content(
            formal_statement, rendered_skeleton, use_admitted=False
        )
        trace["status"] = "success"
        trace["summary"] = {"admits_filled": 0, "total_attempts": 0}
        trace["ended_at"] = datetime.now().isoformat(timespec="seconds")
        persist()
        print("  Skeleton is already a complete proof!", flush=True)
        print(f"Trace: {trace_path}")
        print("Done.", flush=True)
        return

    print(f"  Skeleton has {count_rendered_admits(rendered_skeleton)} admit(s) to fill.", flush=True)
    if args.debug:
        print(
            f"[DEBUG] entering fill loop with slot_names={[slot.name for slot in proof_template.slots]}",
            flush=True,
        )

    # ------------------------------------------------------------------
    # Step 3: Iteratively fill each admit.
    # ------------------------------------------------------------------
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
        print(f"Step 3: Filling admit #{admits_filled} (line {admit_idx + 1}, "
              f"{remaining_admits} remaining)...", flush=True)

        _write_proof_to_file(target_path, formal_statement, proof_body, use_admitted=True)
        snapshot_before_line = _should_snapshot_before_line(marked_proof, admit_idx)
        current_goal_state = _focused_proof_state(run_get_proof_state(
            repo_root,
            target_rel,
            _proof_body_line_to_file_cursor(
                formal_statement,
                admit_idx,
                target_path=target_path,
                before_line=snapshot_before_line,
            ),
        ))
        error_context = ""
        structured_feedback_context = ""
        filled = False
        if args.debug:
            print(
                f"[DEBUG] slot={current_slot.name}, admit_idx={admit_idx}, "
                f"remaining_admits={remaining_admits}, goal_chars={len(current_goal_state)}",
                flush=True,
            )
            print(
                f"[DEBUG] goal preview:\n{_preview_text(current_goal_state, limit=args.debug_char_limit)}",
                flush=True,
            )

        for attempt in range(1, max_fill + 1):
            total_attempts += 1
            fill_trace: dict = {
                "slot_name": current_slot.name,
                "admit_index": admit_idx,
                "attempt": attempt,
                "current_goal_state": current_goal_state,
            }
            trace["fills"].append(fill_trace)
            persist()

            # Bump temperature on fill compile retries
            fill_config = config
            if attempt > 1:
                fill_config = dict(config)
                fill_config["temperature"] = max(config.get("temperature", 0.0), 0.4)

            fill_model_attempts: list[dict] = []
            try:
                replacement = run_fill_goal(
                    formal_statement,
                    angelito_proof,
                    marked_proof,
                    current_goal_state,
                    fill_config,
                    error_context,
                    structured_feedback_context,
                    debug_attempts=fill_model_attempts,
                    log_metadata={
                        "slot_name": current_slot.name,
                        "fill_attempt": attempt,
                        "admit_index": admit_idx,
                    },
                )
                fill_trace["source"] = "model"
                fill_trace["model_attempts"] = fill_model_attempts
            except Exception as e:
                fill_trace["status"] = "model_error"
                fill_trace["error"] = str(e)
                fill_trace["source"] = "model"
                fill_trace["model_attempts"] = fill_model_attempts
                persist()
                fail(f"  Fill model error: {e}")

            fill_trace["replacement"] = replacement
            if args.debug:
                print(
                    f"[DEBUG] fill attempt {attempt} replacement chars={len(replacement)}",
                    flush=True,
                )
                print(
                    f"[DEBUG] replacement preview:\n"
                    f"{_preview_text(replacement, limit=args.debug_char_limit)}",
                    flush=True,
                )

            candidate_slot_values = dict(slot_values)
            candidate_slot_values[current_slot.name] = replacement
            candidate = proof_template.render(candidate_slot_values)
            candidate_has_admits = proof_template.has_unfilled_slots(candidate_slot_values)
            _write_proof_to_file(target_path, formal_statement, candidate,
                                 use_admitted=candidate_has_admits)

            # Compile
            exit_code, stdout, stderr = run_check_target(repo_root, target_rel)
            fill_trace["exit_code"] = exit_code
            fill_trace["check_stdout"] = stdout.strip()
            fill_trace["stdout"] = stdout.strip()
            fill_trace["check_stderr"] = stderr.strip()
            fill_trace["stderr"] = stderr.strip()
            feedback, formatted_feedback = _build_structured_feedback_context(stdout, stderr)
            if feedback:
                fill_trace["compiler_feedback"] = feedback
            if args.debug:
                print(
                    f"[DEBUG] fill compile exit_code={exit_code}, stdout_chars={len(stdout)}, "
                    f"stderr_chars={len(stderr)}, feedback_items={len(feedback)}",
                    flush=True,
                )
                if stdout.strip():
                    print(
                        f"[DEBUG] fill stdout preview:\n"
                        f"{_preview_text(stdout, limit=args.debug_char_limit)}",
                        flush=True,
                    )
                if stderr.strip():
                    print(
                        f"[DEBUG] fill stderr preview:\n"
                        f"{_preview_text(stderr, limit=args.debug_char_limit)}",
                        flush=True,
                    )

            if exit_code == 0:
                fill_trace["status"] = "success"
                persist()
                slot_values = candidate_slot_values
                proof_body = candidate
                filled = True
                print(f"    Attempt {attempt}: compiled OK.", flush=True)
                break

            # Parse error for better feedback
            parsed_error = _parse_structured_error(stderr, stdout)
            failed_goal_state = _capture_goal_state_after_replacement(
                repo_root=repo_root,
                target_rel=target_rel,
                target_path=target_path,
                formal_statement=formal_statement,
                admit_idx=admit_idx,
                replacement=replacement,
            )
            if failed_goal_state:
                fill_trace["post_replacement_goal_state"] = failed_goal_state
            fill_trace["status"] = "compile_error"
            persist()

            error_context = (
                f"The previous replacement failed to compile.\n\n"
                f"**Failed tactics:**\n```coq\n{replacement}\n```\n\n"
                f"**Coq compiler error:**\n```\n{parsed_error}\n```\n\n"
            )
            # Add error-specific guidance (match on full stderr, not truncated)
            error_lower = (stderr or stdout or parsed_error).lower()
            error_hints = []
            if "found no subterm matching" in error_lower:
                error_hints.append(
                    "The `rewrite` tactic failed because the term you tried to rewrite does not appear "
                    "syntactically in the goal or hypothesis. Try a completely different approach. "
                    "If `lra` is available, it can often solve linear arithmetic goals directly from "
                    "hypotheses without needing `rewrite` at all."
                )
            if "unable to unify" in error_lower:
                error_hints.append(
                    "The tactic could not unify the expected and actual terms. "
                    "The goal shape may differ from what you assumed. Use the goal state as ground truth. "
                    "If the goal involves `^`, `x * y`, or other nonlinear terms over R, "
                    "`lra` cannot handle it — use `nlra` or `nra` instead (available when Psatz is imported). "
                    "Alternatively, `rewrite` the variables to concrete values first, then use `ring` or `nlra`."
                )
            if "not an equality" in error_lower or "not an equation" in error_lower:
                error_hints.append(
                    "`rewrite` requires an equality hypothesis. The hypothesis you used is not an equality."
                )
            if "no such goal" in error_lower or "no focused proof" in error_lower:
                error_hints.append(
                    "A previous tactic already closed the goal, so the next tactic had nothing to work on. "
                    "Remove the extra tactics after the goal-closing one."
                )
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
            if args.debug:
                print(
                    f"[DEBUG] retrying slot={current_slot.name} after compile error, "
                    f"structured_feedback_chars={len(structured_feedback_context)}",
                    flush=True,
                )
            print(f"    Attempt {attempt}: compile error, retrying...", flush=True)

        if not filled:
            _write_proof_to_file(target_path, formal_statement, proof_template.render(slot_values),
                                 use_admitted=True)
            fail(f"Failed to fill admit #{admits_filled} after {max_fill} attempts.")

    # ------------------------------------------------------------------
    # Final: write clean proof with Qed.
    # ------------------------------------------------------------------
    proof_body = proof_template.render(slot_values)
    _write_proof_to_file(target_path, formal_statement, proof_body, use_admitted=False)

    # Final compile check
    exit_code, stdout, stderr = run_check_target(repo_root, target_rel)
    if exit_code != 0:
        fail(f"Final proof does not compile:\n{stderr or stdout}")

    trace["summary"] = {
        "admits_filled": admits_filled,
        "total_attempts": total_attempts,
        "slot_count": len(proof_template.slots),
    }
    trace["status"] = "success"
    trace["ended_at"] = datetime.now().isoformat(timespec="seconds")
    persist()
    print(f"\nSummary: filled {admits_filled} admit(s) in {total_attempts} total attempt(s).", flush=True)
    print(f"Trace: {trace_path}", flush=True)
    print("Done.", flush=True)


if __name__ == "__main__":
    main()
