#!/usr/bin/env python3
"""
Autonomous CoS pipeline: rewrite -> Chain of States -> tactic loop with ETR/ESR.
Uses Open Router API and existing Coq scripts. Run from repo root.
"""

import argparse
import json
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
    out = _chat_with_model_fallback(config["cos_model"], prompt, config, stage="chain-of-states")
    return parse_chain_of_states(out)


def run_tactic(state_p: str, state_n: str, config: dict) -> str:
    from pipeline.prompts import get_tactic
    from pipeline.tactic_parser import extract_tactics

    prompt = get_tactic(state_p, state_n)
    out = _chat_with_model_fallback(config["tactic_model"], prompt, config, stage="tactic")
    tactics = extract_tactics(out)
    if not tactics:
        raise RuntimeError("No Coq tactic block in model response")
    return tactics


def run_etr(state_p: str, state_n: str, failed_tactics: str, error_message: str, config: dict) -> str:
    from pipeline.prompts import get_etr
    from pipeline.tactic_parser import extract_tactics

    prompt = get_etr(state_p, state_n, failed_tactics, error_message)
    out = _chat_with_model_fallback(config["etr_model"], prompt, config, stage="etr")
    tactics = extract_tactics(out)
    if not tactics:
        raise RuntimeError("No Coq tactic block in ETR response")
    return tactics


def run_esr(state_a: str, state_b: str, state_c: str, config: dict) -> str:
    from pipeline.prompts import get_esr
    from pipeline.tactic_parser import extract_tactics

    prompt = get_esr(state_a, state_b, state_c)
    out = _chat_with_model_fallback(config["esr_model"], prompt, config, stage="esr")
    tactics = extract_tactics(out)
    if not tactics:
        raise RuntimeError("No Coq tactic block in ESR response")
    return tactics


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
            )
        except Exception as e:
            msg = str(e)
            errors.append(f"{model}: {msg}")
            is_last = i == len(models) - 1
            if is_last or not _is_retryable_model_error(msg):
                break
            print(f"  Warning: {stage} failed with model '{model}', trying fallback...")

    joined = "\n  - ".join(errors)
    raise RuntimeError(f"{stage} failed for configured model(s):\n  - {joined}")


def _get_powershell_executable() -> str:
    """Use pwsh when available; otherwise fallback to Windows PowerShell."""
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

    print("Step 1: Rewrite (Coq-friendly)...")
    try:
        coq_friendly = run_rewrite(informal_path, config)
    except Exception as e:
        fail(f"Error in rewrite step: {e}")
    trace["rewrite"] = {"text": coq_friendly}
    print("  Done.")

    formal_statement = formal_path.read_text(encoding="utf-8").strip()
    print("Step 2: Chain of States...")
    try:
        states = run_cos(formal_statement, coq_friendly, config)
    except Exception as e:
        fail(f"Error in chain-of-states step: {e}")
    if not states:
        fail("Error: no states parsed from CoS response")
    if len(states) > 50:
        fail(
            f"Error: parsed an unusually large state chain ({len(states)}). "
            "The model output likely contained scratch reasoning instead of a final CoS block."
        )
    trace["chain_of_states"] = {"count": len(states), "states": states}
    print(f"  Parsed {len(states)} state(s).")

    # Ensure target has Proof. block
    from pipeline.coq_editor import CoqEditor
    editor = CoqEditor(target_path)
    editor.read()
    if not editor.has_proof_block():
        if not target_path.exists() or not target_path.read_text(encoding="utf-8").strip():
            fail("Error: target .v file has no Proof. block. Add a theorem statement and 'Proof.' first.")
        editor.ensure_proof()
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
        print(f"Step 3: Transition {transition} ({i} -> {i+1})...")
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
                editor.append_tactics(tactics)
            except ValueError as e:
                attempt_trace["status"] = "append_error"
                attempt_trace["error"] = str(e)
                transition_trace["status"] = "failed"
                fail(f"  Error appending tactics: {e}")
            editor.write()

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
                print(f"  Coq error, ETR retry {etr_count}/{max_etr}...")
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
                print("  Warning: could not get proof state from script; assuming OK.")
                attempt_trace["status"] = "success_no_state"
                transition_trace["status"] = "success"
                done = True
                break

            if state_n.strip() == "No Goals":
                attempt_trace["status"] = "success_no_goals"
                transition_trace["status"] = "success"
                done = True
                break

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
            print(f"  State mismatch, ESR retry {esr_count}/{max_esr}...")
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
            print("  No Goals — proof complete.")
            break

    print("")
    print(f"Summary: {transition} transition(s), ETR retries: {total_etr}, ESR retries: {total_esr}")
    trace["summary"] = {
        "transition_count": transition,
        "etr_retries": total_etr,
        "esr_retries": total_esr,
    }
    trace["status"] = "success"
    trace["ended_at"] = datetime.now().isoformat(timespec="seconds")
    _write_trace(trace_path, trace)
    print(f"Trace written to: {trace_path}")
    print("Done.")


if __name__ == "__main__":
    main()
