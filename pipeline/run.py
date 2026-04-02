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
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Union

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

def run_rewrite(informal_path: Path, config: dict) -> str:
    from pipeline.prompts import get_rewrite

    text = informal_path.read_text(encoding="utf-8").strip()
    angelito_spec_path = REPO_ROOT / "angelito-spec.md"
    if not angelito_spec_path.exists():
        raise FileNotFoundError(f"Angelito spec not found: {angelito_spec_path}")
    angelito_spec = angelito_spec_path.read_text(encoding="utf-8").strip()
    prompt = get_rewrite(text, angelito_spec)
    return _generate_with_format_retries(
        config["rewrite_model"],
        prompt,
        config,
        stage="rewrite",
        parser=_parse_rewrite_output,
    )


# ---------------------------------------------------------------------------
# Step 2: Skeleton
# ---------------------------------------------------------------------------

def run_skeleton(formal_statement: str, angelito_proof: str, config: dict) -> str:
    from pipeline.prompts import get_skeleton

    prompt = get_skeleton(formal_statement, angelito_proof)
    skeleton = _generate_with_format_retries(
        config["skeleton_model"],
        prompt,
        config,
        stage="skeleton",
        parser=_parse_tactic_output,
    )
    return _normalize_skeleton_structure(skeleton)


# ---------------------------------------------------------------------------
# Step 3: Fill one admit
# ---------------------------------------------------------------------------

def run_fill_goal(formal_statement: str, angelito_proof: str,
                  current_proof: str, current_goal_state: str, config: dict, error_context: str = "",
                  structured_feedback: str = "") -> str:
    from pipeline.prompts import get_fill_goal

    prompt = get_fill_goal(
        formal_statement,
        angelito_proof,
        current_proof,
        current_goal_state,
        error_context,
        structured_feedback,
    )
    return _generate_with_format_retries(
        config["fill_model"],
        prompt,
        config,
        stage="fill_goal",
        parser=_parse_tactic_output,
    )


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------

def run_check_target(repo_root: Path, file_path_rel: str) -> tuple[int, str, str]:
    """Run check-target-proof.ps1. Returns (exit_code, stdout, stderr)."""
    script = repo_root / "scripts" / "check-target-proof.ps1"
    shell_exe = _get_powershell_executable()
    cmd = [
        shell_exe, "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(script), "-FilePath", file_path_rel,
    ]
    proc = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True, timeout=60)
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def run_get_proof_state(repo_root: Path, file_path_rel: str, cursor_line: int) -> str:
    """Run get-proof-state.ps1 and return parsed proof state text, or empty string."""
    script = repo_root / "scripts" / "get-proof-state.ps1"
    shell_exe = _get_powershell_executable()
    cmd = [
        shell_exe, "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(script),
        "-FilePath", file_path_rel,
        "-CursorLine", str(cursor_line),
    ]
    proc = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


# ---------------------------------------------------------------------------
# admit. helpers
# ---------------------------------------------------------------------------

# Matches admit. optionally preceded by Coq bullets (-, +, *, {, })
_ADMIT_LINE_RE = re.compile(r"^\s*[-+*{}]*\s*admit\.\s*$")


def _find_admits(proof_text: str) -> list[int]:
    """Return 0-based line indices of admit. lines (including bullet-prefixed)."""
    return [i for i, line in enumerate(proof_text.splitlines())
            if _ADMIT_LINE_RE.match(line)]


def _mark_first_admit(proof_text: str) -> tuple[str, int]:
    """Replace the first admit. with '(* FILL THIS *) admit.' and return (marked_text, line_index).
    Returns line_index=-1 if no admit found."""
    lines = proof_text.splitlines()
    for i, line in enumerate(lines):
        if _ADMIT_LINE_RE.match(line):
            # Keep everything before 'admit.' (indent + bullet) as-is
            m = re.match(r"^(.*->)(admit\.\s*)$", line)
            prefix = m.group(1) if m else ""
            lines[i] = f"{prefix}(* FILL THIS *) admit."
            return "\n".join(lines), i
    return proof_text, -1


def _replace_admit_at(proof_text: str, line_index: int, replacement: str) -> str:
    """Replace the admit. at line_index with replacement tactics (preserving indent + bullet)."""
    lines = proof_text.splitlines()
    line = lines[line_index]
    # Extract the prefix (indent + bullet) before admit.
    m = re.match(r"^(.*->)\s*(->:\(\*\s*FILL THIS\s*\*\)\s*)->admit\.\s*$", line)
    prefix = m.group(1) if m else re.match(r"^(\s*)", line).group(1)
    # First replacement line gets the bullet prefix, rest get just the indent
    indent = re.match(r"^(\s*)", prefix).group(1)
    bullet_part = prefix.lstrip()
    repl_lines = [r.strip() for r in replacement.strip().splitlines() if r.strip()]
    new_lines = []
    for j, rline in enumerate(repl_lines):
        if j == 0 and bullet_part:
            new_lines.append(f"{indent}{bullet_part} {rline}")
        else:
            new_lines.append(f"{indent}  {rline}")
    lines[line_index:line_index + 1] = new_lines
    return "\n".join(lines)


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
    rewrite = _strip_fences(raw_output)
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
    return "\n".join(normalized)


def _focused_proof_state(state_text: str) -> str:
    if not state_text.strip():
        return ""
    stop_markers = (
        "This subproof is complete",
        "Focus next goal with bullet",
        "goal 1 is:",
    )
    kept: list[str] = []
    for line in state_text.splitlines():
        if any(marker in line for marker in stop_markers):
            break
        kept.append(line)
    return "\n".join(kept).strip()


def _heuristic_fill_tactics(current_goal_state: str) -> str:
    state = current_goal_state.strip()
    if not state:
        return ""
    if "============================\n0 + 0 = 0" in state:
        return "reflexivity."
    if "IHn : n + 0 = n" in state and "============================\nS n + 0 = S n" in state:
        return "simpl.\nrewrite IHn.\nreflexivity."
    return ""


def _generate_with_format_retries(
    model_value: Union[str, list],
    prompt: str,
    config: dict,
    *,
    stage: str,
    parser,
) -> str:
    max_attempts = int(config.get("format_retries", 3))
    current_prompt = prompt
    errors: list[str] = []
    for attempt in range(1, max_attempts + 1):
        out = _chat_with_model_fallback(model_value, current_prompt, config, stage=stage)
        try:
            return parser(out)
        except Exception as e:
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
    allow_continuation = False
    continuation_re = re.compile(
        r"^(?:"
        r"=\s*.+"
        r"|[A-Za-z0-9_()\[\]{}:+\-*/<>=,.' ]+\[BY .+\]"
        r"|[A-Za-z0-9_()\[\]{}:+\-*/<>=,.' ]+"
        r")$"
    )
    for line in lines:
        keyword = line.split()[0].rstrip(":")
        if keyword in _ANGELITO_KEYWORDS:
            allow_continuation = keyword in {"SIMPLIFY", "GOAL", "THEREFORE", "FACT", "SINCE"}
            continue
        if allow_continuation and continuation_re.match(line):
            continue
        allow_continuation = False
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
        "open router api error 504", "no endpoints found",
        "returned an empty message",
    ])


def _chat_with_model_fallback(model_value: Union[str, list], prompt: str, config: dict, *, stage: str) -> str:
    from pipeline.openrouter_client import chat

    models = _as_model_list(model_value)
    errors = []
    for i, model in enumerate(models):
        try:
            return chat(
                model, prompt,
                max_tokens=config.get("max_tokens", 4096),
                temperature=config.get("temperature", 0.3),
                timeout=config.get("request_timeout_sec", 60),
                retries=config.get("request_retries", 2),
            )
        except Exception as e:
            msg = str(e)
            errors.append(f"{model}: {msg}")
            if i == len(models) - 1 or not _is_retryable_model_error(msg):
                break
            print(f"  Warning: {stage} failed with '{model}', trying fallback...", flush=True)
    raise RuntimeError(f"{stage} failed:\n  - " + "\n  - ".join(errors))


def _get_powershell_executable() -> str:
    if shutil.which("pwsh"):
        return "pwsh"
    if shutil.which("powershell"):
        return "powershell"
    raise RuntimeError("Neither 'pwsh' nor 'powershell' is available on PATH.")


def _default_trace_path() -> Path:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    return REPO_ROOT / "pipeline" / "traces" / f"run-{ts}.json"


def _write_trace(trace_path: Path, trace: dict) -> None:
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text(json.dumps(trace, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# CoqEditor helpers
# ---------------------------------------------------------------------------

def _write_proof_to_file(target_path: Path, formal_statement: str, proof_body: str, use_admitted: bool):
    """Write a .v file with the formal statement, Proof., proof body, and Qed./Admitted."""
    closing = "Admitted." if use_admitted else "Qed."
    # Indent proof body
    indented = []
    for line in proof_body.splitlines():
        stripped = line.strip()
        if stripped:
            indented.append(f"  {stripped}")
        else:
            indented.append("")
    content = f"{formal_statement}\nProof.\n" + "\n".join(indented) + f"\n{closing}\n"
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


def _build_structured_feedback_context(stdout: str) -> tuple[list[dict[str, str]], str]:
    from pipeline.compiler_feedback import extract_xml_feedback, format_xml_feedback

    feedback = extract_xml_feedback(stdout or "")
    return feedback, format_xml_feedback(feedback)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
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

    repo_root = REPO_ROOT
    target_path = args.target if args.target.is_absolute() else repo_root / args.target
    informal_path = args.informal if args.informal.is_absolute() else repo_root / args.informal
    formal_path = args.formal if args.formal.is_absolute() else repo_root / args.formal
    trace_path = args.trace_out or _default_trace_path()
    if not trace_path.is_absolute():
        trace_path = repo_root / trace_path

    if args.target.is_absolute():
        target_rel = str(target_path)
    else:
        target_rel = str(args.target).replace("\\", "/")

    trace: dict = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "status": "running",
        "inputs": {"informal": str(informal_path), "formal": str(formal_path),
                    "target": str(target_path), "target_rel": target_rel},
        "config": {"max_fill_attempts": max_fill},
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
    except Exception as e:
        fail(f"Formal statement normalization failed: {e}")
    persist()

    # ------------------------------------------------------------------
    # Step 1: Rewrite -> strict Angelito
    # ------------------------------------------------------------------
    print("Step 1: Rewrite -> Angelito...", flush=True)
    try:
        angelito_proof = run_rewrite(informal_path, config)
    except Exception as e:
        fail(f"Rewrite failed: {e}")
    trace["rewrite"] = {"text": angelito_proof}
    persist()
    print("  Done.", flush=True)

    # ------------------------------------------------------------------
    # Step 2: Skeleton (Angelito -> Rocq with admit. placeholders)
    # ------------------------------------------------------------------
    print("Step 2: Skeleton generation...", flush=True)
    try:
        skeleton = run_skeleton(formal_statement, angelito_proof, config)
    except Exception as e:
        fail(f"Skeleton generation failed: {e}")
    trace["skeleton"] = {"text": skeleton}
    persist()

    # Write skeleton with Admitted. (admits are present)
    has_admits = bool(_find_admits(skeleton))
    _write_proof_to_file(target_path, formal_statement, skeleton, use_admitted=has_admits)

    # Compile skeleton to verify structure
    exit_code, stdout, stderr = run_check_target(repo_root, target_rel)
    trace["skeleton"]["compiles"] = exit_code == 0
    trace["skeleton"]["check_stdout"] = stdout.strip()
    trace["skeleton"]["stdout"] = stdout.strip()
    trace["skeleton"]["check_stderr"] = stderr.strip()
    trace["skeleton"]["stderr"] = stderr.strip()
    feedback, _ = _build_structured_feedback_context(stdout)
    if feedback:
        trace["skeleton"]["compiler_feedback"] = feedback
    persist()

    if exit_code != 0:
        fail(
            "Skeleton does not compile. Refusing to start fill retries on an invalid proof scaffold.\n"
            f"{stderr or stdout}"
        )
    elif not has_admits and exit_code == 0:
        # Skeleton is already a complete proof!
        _write_proof_to_file(target_path, formal_statement, skeleton, use_admitted=False)
        trace["status"] = "success"
        trace["summary"] = {"admits_filled": 0, "total_attempts": 0}
        trace["ended_at"] = datetime.now().isoformat(timespec="seconds")
        persist()
        print("  Skeleton is already a complete proof!", flush=True)
        print(f"Trace: {trace_path}")
        print("Done.", flush=True)
        return

    print(f"  Skeleton has {len(_find_admits(skeleton))} admit(s) to fill.", flush=True)

    # ------------------------------------------------------------------
    # Step 3: Iteratively fill each admit.
    # ------------------------------------------------------------------
    proof_body = skeleton
    admits_filled = 0
    total_attempts = 0

    while True:
        admit_indices = _find_admits(proof_body)
        if not admit_indices:
            break

        admit_idx = admit_indices[0]
        admits_filled += 1
        print(f"Step 3: Filling admit #{admits_filled} (line {admit_idx + 1}, "
              f"{len(admit_indices)} remaining)...", flush=True)

        marked_proof, _ = _mark_first_admit(proof_body)
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
                "admit_index": admit_idx,
                "attempt": attempt,
                "current_goal_state": current_goal_state,
            }
            trace["fills"].append(fill_trace)
            persist()

            heuristic_replacement = _heuristic_fill_tactics(current_goal_state)
            if heuristic_replacement:
                replacement = heuristic_replacement
                fill_trace["source"] = "heuristic_fallback"
            else:
                try:
                    replacement = run_fill_goal(
                        formal_statement,
                        angelito_proof,
                        marked_proof,
                        current_goal_state,
                        config,
                        error_context,
                        structured_feedback_context,
                    )
                    fill_trace["source"] = "model"
                except Exception as e:
                    fill_trace["status"] = "model_error"
                    fill_trace["error"] = str(e)
                    persist()
                    fail(f"  Fill model error: {e}")

            fill_trace["replacement"] = replacement

            # Apply replacement
            candidate = _replace_admit_at(proof_body, admit_idx, replacement)
            candidate_has_admits = bool(_find_admits(candidate))
            _write_proof_to_file(target_path, formal_statement, candidate,
                                 use_admitted=candidate_has_admits)

            # Compile
            exit_code, stdout, stderr = run_check_target(repo_root, target_rel)
            fill_trace["exit_code"] = exit_code
            fill_trace["check_stdout"] = stdout.strip()
            fill_trace["stdout"] = stdout.strip()
            fill_trace["check_stderr"] = stderr.strip()
            fill_trace["stderr"] = stderr.strip()
            feedback, formatted_feedback = _build_structured_feedback_context(stdout)
            if feedback:
                fill_trace["compiler_feedback"] = feedback

            if exit_code == 0:
                fill_trace["status"] = "success"
                persist()
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
            # Re-mark the original proof (not the failed candidate) for next attempt
            marked_proof, _ = _mark_first_admit(proof_body)
            print(f"    Attempt {attempt}: compile error, retrying...", flush=True)

        if not filled:
            # Write back the skeleton state so the file isn't left broken
            _write_proof_to_file(target_path, formal_statement, proof_body,
                                 use_admitted=True)
            fail(f"Failed to fill admit #{admits_filled} after {max_fill} attempts.")

    # ------------------------------------------------------------------
    # Final: write clean proof with Qed.
    # ------------------------------------------------------------------
    _write_proof_to_file(target_path, formal_statement, proof_body, use_admitted=False)

    # Final compile check
    exit_code, stdout, stderr = run_check_target(repo_root, target_rel)
    if exit_code != 0:
        fail(f"Final proof does not compile:\n{stderr or stdout}")

    trace["summary"] = {"admits_filled": admits_filled, "total_attempts": total_attempts}
    trace["status"] = "success"
    trace["ended_at"] = datetime.now().isoformat(timespec="seconds")
    persist()
    print(f"\nSummary: filled {admits_filled} admit(s) in {total_attempts} total attempt(s).", flush=True)
    print(f"Trace: {trace_path}", flush=True)
    print("Done.", flush=True)


if __name__ == "__main__":
    main()
