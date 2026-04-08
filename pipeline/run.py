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
        parser=_parse_rewrite_output,
        debug_attempts=debug_attempts,
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
) -> str:
    from pipeline.prompts import get_skeleton

    if not _angelito_has_outer_structure(angelito_proof):
        skeleton = _build_direct_skeleton(formal_statement)
        if debug_attempts is not None:
            debug_attempts.append(
                {
                    "format_attempt": 0,
                    "model": "deterministic",
                    "raw_output": skeleton,
                    "status": "derived",
                    "parsed_output": skeleton,
                }
            )
        return skeleton

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
    )
    return _normalize_skeleton_structure(skeleton)


# ---------------------------------------------------------------------------
# Step 3: Fill one admit
# ---------------------------------------------------------------------------

def run_fill_goal(formal_statement: str, angelito_proof: str,
                  current_proof: str, current_goal_state: str, config: dict, error_context: str = "",
                  structured_feedback: str = "", debug_attempts: Optional[list[dict]] = None) -> str:
    from pipeline.prompts import get_fill_goal

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
        parser=_parse_tactic_output,
        debug_attempts=debug_attempts,
    )
    return _trim_terminal_tactic_suffix(replacement)


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------

def run_check_target(repo_root: Path, file_path_rel: str) -> tuple[int, str, str]:
    """Run check-target-proof.py. Returns (exit_code, stdout, stderr)."""
    script = repo_root / "scripts" / "check-target-proof.py"
    cmd = [
        sys.executable,
        str(script),
        "--file-path",
        file_path_rel,
    ]
    proc = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True, timeout=60)
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def run_get_proof_state(repo_root: Path, file_path_rel: str, cursor_line: int) -> str:
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
    proc = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True, timeout=60)
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


def _parse_rewrite_output(raw_output: str) -> str:
    rewrite = _extract_angelito_block(_strip_fences(raw_output))
    _validate_angelito_rewrite(rewrite)
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


def _parse_skeleton_output(raw_output: str, *, formal_statement: str, angelito_proof: str) -> str:
    skeleton = _normalize_skeleton_structure(_parse_tactic_output(raw_output))
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

    angelito_lines = [line.strip() for line in angelito_proof.splitlines() if line.strip()]
    allows_induction = any(line.startswith("INDUCTION ") for line in angelito_lines)
    allows_split_apply = any(line.startswith("APPLY ") and "SPLIT INTO:" in line for line in angelito_lines)

    if not allows_induction and any(line.lower().startswith("induction ") for line in nonempty_lines):
        raise ValueError(
            "Skeleton introduced `induction` even though the Angelito proof has no `INDUCTION` step.\n"
            f"Raw output:\n{_truncate_for_error(raw_output)}"
        )

    if not allows_split_apply and any(line.lower().startswith("apply ") for line in nonempty_lines):
        raise ValueError(
            "Skeleton introduced `apply ...` structure even though the Angelito proof has no `APPLY ... SPLIT INTO` step.\n"
            f"Raw output:\n{_truncate_for_error(raw_output)}"
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
    if last_admit_idx >= 0:
        trailing_nonempty = [line for line in normalized[last_admit_idx + 1 :] if line.strip()]
        if trailing_nonempty:
            normalized = normalized[: last_admit_idx + 1]

    return "\n".join(normalized)


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
) -> str:
    max_attempts = int(config.get("format_retries", 3))
    current_prompt = prompt
    errors: list[str] = []
    for attempt in range(1, max_attempts + 1):
        out, resolved_model = _chat_with_model_fallback(
            model_value,
            current_prompt,
            config,
            stage=stage,
            metadata={"format_attempt": attempt},
        )
        attempt_info = {
            "format_attempt": attempt,
            "model": resolved_model,
            "raw_output": out,
        }
        try:
            parsed = parser(out)
            attempt_info["status"] = "parsed"
            attempt_info["parsed_output"] = parsed
            if debug_attempts is not None:
                debug_attempts.append(attempt_info)
            return parsed
        except Exception as e:
            attempt_info["status"] = "invalid_format"
            attempt_info["error"] = str(e)
            if debug_attempts is not None:
                debug_attempts.append(attempt_info)
            errors.append(f"Attempt {attempt}: {e}")
            if attempt == max_attempts:
                break
            current_prompt = (
                prompt
                + "\n\nYour previous output was invalid.\n"
                + f"Reason: {e}\n"
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


def _validate_angelito_rewrite(text: str) -> None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("Rewrite model returned empty output.")
    if not lines[0].startswith("PROVE "):
        raise ValueError(
            "Rewrite output is not strict Angelito: first non-empty line must start with 'PROVE '.\n"
            f"Raw output:\n{_truncate_for_error(text)}"
        )
    if "BEGIN" not in lines or "END" not in lines:
        raise ValueError(
            "Rewrite output is not strict Angelito: expected BEGIN/END block.\n"
            f"Raw output:\n{_truncate_for_error(text)}"
        )
    if not any(line.startswith("CONCLUDE") for line in lines):
        raise ValueError(
            "Rewrite output is not strict Angelito: expected at least one CONCLUDE line.\n"
            f"Raw output:\n{_truncate_for_error(text)}"
        )

    bad_lines: list[str] = []
    continuation_mode: Optional[str] = None
    default_continuation_re = re.compile(
        r"^(?:"
        r"=\s*.+"
        r"|[A-Za-z0-9_()\[\]{}:+\-*/<>=,.' ]+\[BY .+\]"
        r"|[A-Za-z0-9_()\[\]{}:+\-*/<>=,.' ]+"
        r")$"
    )
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
        if continuation_mode == "default" and default_continuation_re.match(line):
            continue
        if continuation_mode == "split_into" and split_into_re.match(line):
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
    angelito_require_markers = {
        "Require Import Angelito.",
        "Require Import RocqCoSPOC.Angelito.",
        "From RocqCoSPOC Require Import Angelito.",
    }
    generated_imports: list[str] = []
    if target_path.parent.name.lower() == "coq":
        if not any(marker in normalized_imports for marker in angelito_require_markers):
            generated_imports.append("From RocqCoSPOC Require Import Angelito.")
        if "Import Angelito.Ltac1." not in normalized_imports:
            generated_imports.append("Import Angelito.Ltac1.")

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


def _angelito_has_outer_structure(angelito_proof: str) -> bool:
    for raw_line in angelito_proof.splitlines():
        line = raw_line.strip()
        if line.startswith("INDUCTION "):
            return True
        if line.startswith("APPLY ") and "SPLIT INTO:" in line:
            return True
        if line.startswith("PROVE BASE_CASE:") or line.startswith("PROVE INDUCTIVE_CASE:"):
            return True
    return False


def _build_direct_skeleton(formal_statement: str) -> str:
    theorem_lines = [line.strip() for line in formal_statement.splitlines() if line.strip()]
    theorem_text = theorem_lines[-1] if theorem_lines else formal_statement
    needs_intros = "forall " in theorem_text or "->" in theorem_text
    if needs_intros:
        return "intros.\nadmit."
    return "admit."


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
    for i, model in enumerate(models):
        try:
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
            return response, model
        except Exception as e:
            msg = str(e)
            errors.append(f"{model}: {msg}")
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


def _proof_body_line_to_file_cursor(formal_statement: str, proof_body_line_index: int) -> int:
    return len(formal_statement.splitlines()) + 2 + proof_body_line_index


def _parse_structured_error(stderr: str, stdout: str) -> str:
    """Extract useful error info from coqc output."""
    raw = (stderr or stdout).strip()
    if not raw:
        return ""
    # Look for "Error:" lines and surrounding context
    lines = raw.splitlines()
    error_lines = []
    for i, line in enumerate(lines):
        if "Error:" in line or "error:" in line.lower():
            start = max(0, i - 2)
            end = min(len(lines), i + 5)
            error_lines.extend(lines[start:end])
            error_lines.append("---")
    if error_lines:
        return "\n".join(error_lines)
    return raw


def _build_structured_feedback_context(stdout: str, stderr: str) -> tuple[list[dict[str, str]], str]:
    from pipeline.compiler_feedback import extract_compiler_feedback, format_compiler_feedback

    feedback = extract_compiler_feedback(stdout or "", stderr or "")
    return feedback, format_compiler_feedback(feedback)


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
    args = parser.parse_args()

    config = load_config()
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

    try:
        formal_statement = _normalize_formal_statement(formal_path.read_text(encoding="utf-8"))
        formal_statement = _ensure_generated_imports(formal_statement, target_path)
    except Exception as e:
        fail(f"Formal statement normalization failed: {e}")
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
        )
    except Exception as e:
        trace["rewrite"] = {"model_attempts": rewrite_attempts}
        persist()
        fail(f"Rewrite failed: {e}")
    trace["rewrite"] = {"text": angelito_proof, "model_attempts": rewrite_attempts}
    persist()
    print("  Done.", flush=True)

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
        skeleton_model_attempts: list[dict] = []
        try:
            skeleton = run_skeleton(
                formal_statement,
                angelito_proof,
                config,
                error_context=skeleton_error_context,
                structured_feedback=skeleton_structured_feedback,
                debug_attempts=skeleton_model_attempts,
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
            fail(f"Skeleton generation failed: {e}")

        proof_template = build_proof_template(skeleton, angelito_proof)
        slot_values = {slot.name: None for slot in proof_template.slots}
        rendered_skeleton = proof_template.render(slot_values)
        has_admits = proof_template.has_unfilled_slots(slot_values)
        _write_proof_to_file(target_path, formal_statement, rendered_skeleton, use_admitted=has_admits)

        exit_code, stdout, stderr = run_check_target(repo_root, target_rel)
        last_skeleton_output = (stderr or stdout).strip()
        feedback, formatted_feedback = _build_structured_feedback_context(stdout, stderr)

        attempt_trace: dict = {
            "attempt": skeleton_attempt,
            "text": skeleton,
            "rendered_text": rendered_skeleton,
            "full_file_text": _format_proof_file_content(
                formal_statement, rendered_skeleton, use_admitted=has_admits
            ),
            "slot_names": [slot.name for slot in proof_template.slots],
            "model_attempts": skeleton_model_attempts,
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
                cursor_line = _proof_body_line_to_file_cursor(formal_statement, admit_lines[0])
                attempt_trace["proof_state"] = _focused_proof_state(
                    run_get_proof_state(repo_root, target_rel, cursor_line)
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
            "Generate a corrected skeleton that compiles when wrapped with this theorem and imports."
        )
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
        current_goal_state = _focused_proof_state(run_get_proof_state(
            repo_root,
            target_rel,
            _proof_body_line_to_file_cursor(formal_statement, admit_idx),
        ))
        error_context = ""
        structured_feedback_context = ""
        filled = False

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

            fill_model_attempts: list[dict] = []
            try:
                replacement = run_fill_goal(
                    formal_statement,
                    angelito_proof,
                    marked_proof,
                    current_goal_state,
                    config,
                    error_context,
                    structured_feedback_context,
                    debug_attempts=fill_model_attempts,
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
            fill_trace["status"] = "compile_error"
            persist()

            error_context = (
                f"The previous replacement failed to compile.\n\n"
                f"**Failed tactics:**\n```coq\n{replacement}\n```\n\n"
                f"**Coq compiler error:**\n```\n{parsed_error}\n```\n\n"
                f"Please fix the tactics for this sub-goal."
            )
            structured_feedback_context = formatted_feedback
            marked_proof = proof_template.render(slot_values, marked_slot=current_slot.name)
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
