#!/usr/bin/env python3
"""
Autonomous CoS pipeline: rewrite -> Chain of States -> tactic loop with ETR/ESR.
Uses Open Router API and existing Coq scripts. Run from repo root.
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


def run_rewrite(informal_path: Path, config: dict) -> str:
    from pipeline.prompts import get_rewrite

    text = informal_path.read_text(encoding="utf-8").strip()
    prompt = get_rewrite(text)
    out = _chat_with_model_fallback(config["rewrite_model"], prompt, config, stage="rewrite")
    # Strip markdown code fence if present
    if out.startswith("```"):
        lines = out.splitlines()
        if lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        out = "\n".join(lines)
    return out.strip()


def run_cos(formal_statement: str, coq_friendly_proof: str, config: dict) -> list:
    from pipeline.prompts import get_cos
    from pipeline.cos_parser import parse_chain_of_states

    prompt = get_cos(formal_statement, coq_friendly_proof)
    strict_suffix = (
        "\n\nIMPORTANT FORMAT REMINDER:\n"
        "- Output ONLY state blocks.\n"
        "- State 0 goal must match the formal theorem statement exactly.\n"
        "- Final state must be 'No Goals'.\n"
        "- No prose, no comments, no markdown."
    )
    last_out = ""
    for attempt in range(1, 4):
        out = _chat_with_model_fallback(config["cos_model"], prompt, config, stage="chain-of-states")
        last_out = out
        states = parse_chain_of_states(out)
        if _is_valid_chain(formal_statement, states):
            return states
        prompt = get_cos(formal_statement, coq_friendly_proof) + strict_suffix
        print(f"  Warning: invalid chain-of-states format on attempt {attempt}, retrying...", flush=True)

    fallback = _fallback_chain(formal_statement)
    if fallback:
        print("  Warning: falling back to single-transition chain (State 0 -> No Goals).", flush=True)
        return fallback

    snippet = "\n".join(last_out.splitlines()[:12])
    raise RuntimeError(f"Could not parse a valid chain-of-states after retries. Last output:\n{snippet}")


def run_tactic(state_p: str, state_n: str, config: dict) -> str:
    from pipeline.prompts import get_tactic
    from pipeline.tactic_parser import extract_tactics

    heuristic = _heuristic_tactic(state_p, state_n)
    if heuristic:
        return heuristic

    prompt = get_tactic(state_p, state_n)
    strict_suffix = (
        "\n\nIMPORTANT:\n"
        "Return ONLY a fenced Coq code block.\n"
        "Do not include any prose or analysis.\n"
    )
    last_out = ""
    for _ in range(3):
        out = _chat_with_model_fallback(config["tactic_model"], prompt, config, stage="tactic")
        last_out = out
        tactics = extract_tactics(out)
        if tactics:
            return tactics
        prompt = get_tactic(state_p, state_n) + strict_suffix
    snippet = "\n".join(last_out.splitlines()[:12])
    raise RuntimeError(f"No Coq tactic block in model response. Last output:\n{snippet}")


def run_etr(state_p: str, state_n: str, failed_tactics: str, error_message: str, config: dict) -> str:
    from pipeline.prompts import get_etr
    from pipeline.tactic_parser import extract_tactics

    prompt = get_etr(state_p, state_n, failed_tactics, error_message)
    strict_suffix = (
        "\n\nIMPORTANT:\n"
        "Return ONLY a fenced Coq code block.\n"
        "Do not include analysis/prose.\n"
    )
    last_out = ""
    for _ in range(3):
        out = _chat_with_model_fallback(config["etr_model"], prompt, config, stage="etr")
        last_out = out
        tactics = extract_tactics(out)
        if tactics:
            return tactics
        prompt = get_etr(state_p, state_n, failed_tactics, error_message) + strict_suffix
    snippet = "\n".join(last_out.splitlines()[:12])
    raise RuntimeError(f"No Coq tactic block in ETR response. Last output:\n{snippet}")


def run_esr(state_a: str, state_b: str, state_c: str, config: dict) -> str:
    from pipeline.prompts import get_esr
    from pipeline.tactic_parser import extract_tactics

    prompt = get_esr(state_a, state_b, state_c)
    strict_suffix = (
        "\n\nIMPORTANT:\n"
        "Return ONLY a fenced Coq code block.\n"
        "No prose.\n"
    )
    last_out = ""
    for _ in range(3):
        out = _chat_with_model_fallback(config["esr_model"], prompt, config, stage="esr")
        last_out = out
        tactics = extract_tactics(out)
        if tactics:
            return tactics
        prompt = get_esr(state_a, state_b, state_c) + strict_suffix
    snippet = "\n".join(last_out.splitlines()[:12])
    raise RuntimeError(f"No Coq tactic block in ESR response. Last output:\n{snippet}")


def run_check_target(repo_root: Path, file_path_rel: str) -> tuple[int, str, str]:
    """Run check-target-proof.ps1. Returns (exit_code, stdout, stderr)."""
    script = repo_root / "scripts" / "check-target-proof.ps1"
    shell_exe = _get_powershell_executable()
    cmd = [
        shell_exe, "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(script), "-FilePath", file_path_rel,
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def run_get_proof_state(repo_root: Path, file_path_rel: str, cursor_line: int) -> str:
    """Run get-proof-state.ps1; returns stdout (state text)."""
    script = repo_root / "scripts" / "get-proof-state.ps1"
    shell_exe = _get_powershell_executable()
    cmd = [
        shell_exe, "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(script), "-FilePath", file_path_rel, "-CursorLine", str(cursor_line),
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


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
    return (
        "open router api error 404" in m
        or "open router api error 408" in m
        or "open router api error 409" in m
        or "open router api error 425" in m
        or "open router api error 429" in m
        or "open router api error 500" in m
        or "open router api error 502" in m
        or "open router api error 503" in m
        or "open router api error 504" in m
        or "no endpoints found" in m
        or "returned an empty message" in m
    )


def _chat_with_model_fallback(model_value: Union[str, list], prompt: str, config: dict, *, stage: str) -> str:
    from pipeline.openrouter_client import chat

    models = _as_model_list(model_value)
    errors = []
    for i, model in enumerate(models):
        try:
            return chat(
                model,
                prompt,
                max_tokens=config.get("max_tokens", 4096),
                temperature=config.get("temperature", 0.3),
                timeout=config.get("request_timeout_sec", 60),
                retries=config.get("request_retries", 2),
            )
        except Exception as e:
            msg = str(e)
            errors.append(f"{model}: {msg}")
            is_last = i == len(models) - 1
            if is_last or not _is_retryable_model_error(msg):
                break
            print(f"  Warning: {stage} failed with model '{model}', trying fallback...", flush=True)

    joined = "\n  - ".join(errors)
    raise RuntimeError(f"{stage} failed for configured model(s):\n  - {joined}")


def _get_powershell_executable() -> str:
    """Use pwsh when available; otherwise fallback to Windows PowerShell."""
    if shutil.which("pwsh"):
        return "pwsh"
    if shutil.which("powershell"):
        return "powershell"
    raise RuntimeError("Neither 'pwsh' nor 'powershell' is available on PATH.")


def _extract_formal_goal(formal_statement: str) -> str:
    # Pull proposition from first Theorem/Lemma/... line.
    m = re.search(
        r"^\s*(?:Theorem|Lemma|Example|Corollary|Proposition|Remark|Fact|Goal)\b.*?:\s*(.+?)\.\s*$",
        formal_statement,
        re.IGNORECASE | re.MULTILINE,
    )
    if m:
        return m.group(1).strip()
    return ""


def _extract_state_goal(state: str) -> str:
    if state.strip().lower() == "no goals":
        return "No Goals"
    sep = "============================"
    if sep not in state:
        return ""
    return state.split(sep, 1)[1].strip()


def _normalize_goal_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _is_valid_chain(formal_statement: str, states: list[str]) -> bool:
    if len(states) < 2:
        return False
    if states[-1].strip() != "No Goals":
        return False
    first_goal = _extract_state_goal(states[0])
    if not first_goal:
        return False
    expected_goal = _extract_formal_goal(formal_statement)
    if not expected_goal:
        return True
    return _normalize_goal_text(first_goal) == _normalize_goal_text(expected_goal)


def _fallback_chain(formal_statement: str) -> list[str]:
    goal = _extract_formal_goal(formal_statement)
    if not goal:
        return []
    return [f"State 0:\n============================\n{goal}", "No Goals"]


def _heuristic_tactic(state_p: str, state_n: str) -> str:
    """Small deterministic fallback for common Nat identities in smoke tests."""
    if state_n.strip() != "No Goals":
        return ""
    goal = _extract_state_goal(state_p)
    if not goal:
        return ""
    normalized = _normalize_goal_text(goal)
    m = re.match(r"^forall\s+([a-zA-Z_][\w']*)\s*:\s*nat,\s*\1\s*\+\s*0\s*=\s*\1$", normalized)
    if m:
        n = m.group(1)
        return f"intros {n}.\nsymmetry.\napply plus_n_O."
    return ""


def _default_trace_path() -> Path:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    return REPO_ROOT / "pipeline" / "traces" / f"run-{ts}.json"


def _write_trace(trace_path: Path, trace: dict) -> None:
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text(json.dumps(trace, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(
        description="Autonomous CoS pipeline: informal proof -> Coq proof via Open Router"
    )
    parser.add_argument(
        "--informal",
        type=Path,
        required=True,
        help="Path to informal proof (text file)",
    )
    parser.add_argument(
        "--formal",
        type=Path,
        required=True,
        help="Path to formal Coq statement or .v file containing the theorem",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=Path("coq/CongModEq.v"),
        help="Target .v file to edit (default: coq/CongModEq.v)",
    )
    parser.add_argument(
        "--max-etr",
        type=int,
        default=None,
        help="Max ETR retries per transition (default from config)",
    )
    parser.add_argument(
        "--max-esr",
        type=int,
        default=None,
        help="Max ESR retries per transition (default from config)",
    )
    parser.add_argument(
        "--trace-out",
        type=Path,
        default=None,
        help="Optional JSON path for pipeline trace output (default: pipeline/traces/run-<timestamp>.json)",
    )
    args = parser.parse_args()

    config = load_config()
    max_etr = args.max_etr if args.max_etr is not None else config.get(
        "max_tactic_errors", config.get("max_etr", 3)
    )
    max_esr = args.max_esr if args.max_esr is not None else config.get(
        "max_state_mismatch", config.get("max_esr", 2)
    )

    repo_root = REPO_ROOT
    target_path = args.target if args.target.is_absolute() else repo_root / args.target
    informal_path = args.informal if args.informal.is_absolute() else repo_root / args.informal
    formal_path = args.formal if args.formal.is_absolute() else repo_root / args.formal
    trace_path = args.trace_out if args.trace_out is not None else _default_trace_path()
    if not trace_path.is_absolute():
        trace_path = repo_root / trace_path

    trace: dict = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "status": "running",
        "inputs": {
            "informal": str(informal_path),
            "formal": str(formal_path),
            "target": str(target_path),
            "target_rel": None,
        },
        "config": {
            "max_tactic_errors": max_etr,
            "max_state_mismatch": max_esr,
            "temperature": config.get("temperature", 0.3),
            "max_tokens": config.get("max_tokens", 4096),
        },
        "rewrite": {},
        "chain_of_states": {},
        "transitions": [],
        "summary": {},
    }

    def fail(msg: str) -> None:
        trace["status"] = "failed"
        trace["error"] = msg
        trace["ended_at"] = datetime.now().isoformat(timespec="seconds")
        _write_trace(trace_path, trace)
        print(msg, file=sys.stderr)
        print(f"Trace written to: {trace_path}")
        sys.exit(1)

    if not informal_path.exists():
        fail(f"Error: informal proof file not found: {informal_path}")
    if not formal_path.exists():
        fail(f"Error: formal statement file not found: {formal_path}")

    # Path for PowerShell scripts (relative to repo root or absolute)
    if args.target.is_absolute():
        target_rel = str(target_path)
    else:
        target_rel = str(args.target).replace("\\", "/")
    trace["inputs"]["target_rel"] = target_rel

    print("Step 1: Rewrite (Coq-friendly)...", flush=True)
    try:
        coq_friendly = run_rewrite(informal_path, config)
    except Exception as e:
        fail(f"Error in rewrite step: {e}")
    trace["rewrite"] = {"text": coq_friendly}
    print("  Done.", flush=True)

    formal_statement = formal_path.read_text(encoding="utf-8").strip()
    print("Step 2: Direct proving attempt (CoS disabled)...", flush=True)
    states = _fallback_chain(formal_statement)
    if not states:
        fail("Error: could not build proving goal from formal statement")
    if not states:
        fail("Error: could not construct direct proving states")
    # CoS is intentionally disabled: we use one transition (State 0 -> No Goals).
    trace["chain_of_states"] = {"count": len(states), "states": states}
    print(f"  Built {len(states)} state(s) for direct proving.", flush=True)

    # Ensure target has Proof. block
    from pipeline.coq_editor import CoqEditor
    editor = CoqEditor(target_path)
    editor.read()
    if not editor.has_proof_block():
        if not target_path.exists() or not target_path.read_text(encoding="utf-8").strip():
            fail("Error: target .v file has no Proof. block. Add a theorem statement and 'Proof.' first.")
        editor.ensure_proof()
    editor.ensure_qed()
    editor.write()

    from pipeline.cos_parser import states_match, normalize_state

    total_etr = 0
    total_esr = 0
    transition = 0
    i = 0
    while i + 1 < len(states):
        state_p = states[i]
        state_n = states[i + 1]
        transition += 1
        print(f"Step 3: Transition {transition} ({i} -> {i+1})...", flush=True)
        transition_trace = {
            "transition_index": transition,
            "from_state_index": i,
            "to_state_index": i + 1,
            "from_state": state_p,
            "to_state": state_n,
            "attempts": [],
            "status": "running",
        }
        trace["transitions"].append(transition_trace)
        editor.reset_last_tactic_block()

        etr_count = 0
        esr_count = 0
        done = False
        while not done:
            attempt_trace = {"attempt": len(transition_trace["attempts"]) + 1}
            transition_trace["attempts"].append(attempt_trace)
            try:
                tactics = run_tactic(state_p, state_n, config)
            except Exception as e:
                attempt_trace["status"] = "tactic_error"
                attempt_trace["error"] = str(e)
                transition_trace["status"] = "failed"
                fail(f"  Error getting tactics: {e}")
            attempt_trace["tactic"] = tactics

            editor.read()
            try:
                if editor.has_last_tactic_block():
                    editor.replace_last_tactic_block(tactics)
                else:
                    editor.append_tactics(tactics)
            except ValueError as e:
                attempt_trace["status"] = "append_error"
                attempt_trace["error"] = str(e)
                transition_trace["status"] = "failed"
                fail(f"  Error appending tactics: {e}")
            editor.write()

            # For intermediate transitions, compile-checking the whole file is too strict
            # because the proof is intentionally incomplete. We only do full coqc check
            # on the final "No Goals" transition.
            if state_n.strip() == "No Goals":
                exit_code, stdout, stderr = run_check_target(repo_root, target_rel)
                attempt_trace["check_exit_code"] = exit_code
                attempt_trace["check_stdout"] = stdout.strip()
                attempt_trace["check_stderr"] = stderr.strip()
                if exit_code != 0:
                    total_etr += 1
                    etr_count += 1
                    if etr_count > max_etr:
                        attempt_trace["status"] = "etr_limit_exceeded"
                        transition_trace["status"] = "failed"
                        fail(f"  Max ETR retries ({max_etr}) exceeded.")
                    print(f"  Coq error, ETR retry {etr_count}/{max_etr}...", flush=True)
                    try:
                        etr_tactics = run_etr(state_p, state_n, tactics, stderr or stdout, config)
                    except Exception as e:
                        attempt_trace["status"] = "etr_error"
                        attempt_trace["error"] = str(e)
                        transition_trace["status"] = "failed"
                        fail(f"  ETR failed: {e}")
                    editor.read()
                    editor.replace_last_tactic_block(etr_tactics)
                    editor.write()
                    attempt_trace["status"] = "coq_error_etr_retry"
                    attempt_trace["etr_tactic"] = etr_tactics
                    continue

            # Success: check state match
            cursor_line = editor.get_cursor_line_for_state()
            actual_state = run_get_proof_state(repo_root, target_rel, cursor_line)
            attempt_trace["actual_state"] = actual_state
            if not actual_state:
                total_etr += 1
                etr_count += 1
                if etr_count > max_etr:
                    attempt_trace["status"] = "etr_limit_exceeded_no_state"
                    transition_trace["status"] = "failed"
                    fail(f"  Max ETR retries ({max_etr}) exceeded.")
                print(f"  Could not read proof state, ETR retry {etr_count}/{max_etr}...", flush=True)
                try:
                    etr_tactics = run_etr(
                        state_p,
                        state_n,
                        tactics,
                        "Could not capture proof state after applying tactics.",
                        config,
                    )
                except Exception as e:
                    attempt_trace["status"] = "etr_error_no_state"
                    attempt_trace["error"] = str(e)
                    transition_trace["status"] = "failed"
                    fail(f"  ETR failed: {e}")
                editor.read()
                editor.replace_last_tactic_block(etr_tactics)
                editor.write()
                attempt_trace["status"] = "no_state_etr_retry"
                attempt_trace["etr_tactic"] = etr_tactics
                continue

            if state_n.strip() == "No Goals":
                if actual_state.strip().endswith("No Goals"):
                    attempt_trace["status"] = "success_no_goals"
                    transition_trace["status"] = "success"
                    done = True
                    break
                total_esr += 1
                esr_count += 1
                if esr_count > max_esr:
                    attempt_trace["status"] = "esr_limit_exceeded_no_goals"
                    transition_trace["status"] = "failed"
                    fail(f"  Max ESR retries ({max_esr}) exceeded.")
                print(f"  Expected No Goals, ESR retry {esr_count}/{max_esr}...", flush=True)
                try:
                    esr_tactics = run_esr(state_p, state_n, actual_state, config)
                except Exception as e:
                    attempt_trace["status"] = "esr_error_no_goals"
                    attempt_trace["error"] = str(e)
                    transition_trace["status"] = "failed"
                    fail(f"  ESR failed: {e}")
                editor.read()
                editor.replace_last_tactic_block(esr_tactics)
                editor.write()
                attempt_trace["status"] = "no_goals_esr_retry"
                attempt_trace["esr_tactic"] = esr_tactics
                continue

            if states_match(state_n, actual_state):
                attempt_trace["status"] = "success_state_match"
                transition_trace["status"] = "success"
                done = True
                break

            total_esr += 1
            esr_count += 1
            if esr_count > max_esr:
                attempt_trace["status"] = "esr_limit_exceeded"
                transition_trace["status"] = "failed"
                fail(f"  Max ESR retries ({max_esr}) exceeded.")
            print(f"  State mismatch, ESR retry {esr_count}/{max_esr}...", flush=True)
            try:
                esr_tactics = run_esr(state_p, state_n, actual_state, config)
            except Exception as e:
                attempt_trace["status"] = "esr_error"
                attempt_trace["error"] = str(e)
                transition_trace["status"] = "failed"
                fail(f"  ESR failed: {e}")
            editor.read()
            editor.replace_last_tactic_block(esr_tactics)
            editor.write()
            attempt_trace["status"] = "state_mismatch_esr_retry"
            attempt_trace["esr_tactic"] = esr_tactics

        i += 1
        if state_n.strip() == "No Goals":
            print("  No Goals — proof complete.", flush=True)
            break

    print("", flush=True)
    print(f"Summary: {transition} transition(s), ETR retries: {total_etr}, ESR retries: {total_esr}", flush=True)
    trace["summary"] = {
        "transition_count": transition,
        "etr_retries": total_etr,
        "esr_retries": total_esr,
    }
    trace["status"] = "success"
    trace["ended_at"] = datetime.now().isoformat(timespec="seconds")
    _write_trace(trace_path, trace)
    print(f"Trace written to: {trace_path}", flush=True)
    print("Done.", flush=True)


if __name__ == "__main__":
    main()
