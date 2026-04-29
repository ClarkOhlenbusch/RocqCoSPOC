"""Thin orchestrator: parse args, call stages in sequence."""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from pipeline.config import REPO_ROOT, as_model_list, load_config
from pipeline.coq import extract_imports, run_check_target, verify_imports
from pipeline.proof_file import (
    ensure_generated_imports, format_proof_file_content,
    normalize_formal_statement, write_proof_to_file,
)
from pipeline.trace import default_model_log_path, default_trace_path, write_trace
from pipeline.utils import preview_text

from pipeline.stages import rewrite as rewrite_stage
from pipeline.stages import skeleton as skeleton_stage
from pipeline.stages import fill as fill_stage


def main():
    parser = argparse.ArgumentParser(
        description="Proof pipeline: informal -> Angelito -> Rocq skeleton -> iterative fill"
    )
    parser.add_argument("--informal", type=Path, required=True, help="Informal proof text file")
    parser.add_argument("--formal", type=Path, required=True, help="Formal Coq statement file")
    parser.add_argument("--target", type=Path, default=Path("coq/CongModEq.v"), help="Target .v file")
    parser.add_argument("--max-fill-attempts", type=int, default=None, help="Max retries per admit fill")
    parser.add_argument("--trace-out", type=Path, default=None, help="JSON trace output path")
    parser.add_argument("--debug", action="store_true", help="Emit verbose debugging logs")
    parser.add_argument("--debug-char-limit", type=int, default=500, help="Max chars per debug preview log")
    args = parser.parse_args()

    config = load_config()
    config["debug"] = args.debug
    config["debug_char_limit"] = args.debug_char_limit
    max_fill = args.max_fill_attempts or config.get("max_fill_attempts", 3)
    config["max_fill_attempts"] = max_fill

    repo_root = REPO_ROOT
    target_path = args.target if args.target.is_absolute() else repo_root / args.target
    informal_path = args.informal if args.informal.is_absolute() else repo_root / args.informal
    formal_path = args.formal if args.formal.is_absolute() else repo_root / args.formal
    trace_path = args.trace_out or default_trace_path()
    if not trace_path.is_absolute():
        trace_path = repo_root / trace_path
    model_log_path = default_model_log_path(trace_path)
    if model_log_path.exists():
        model_log_path.unlink()
    config["model_log_path"] = str(model_log_path)

    target_rel = str(target_path) if args.target.is_absolute() else str(args.target).replace("\\", "/")

    trace: dict = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "status": "running",
        "inputs": {
            "informal": str(informal_path), "formal": str(formal_path),
            "target": str(target_path), "target_rel": target_rel,
        },
        "config": {
            "max_fill_attempts": max_fill,
            "max_skeleton_attempts": int(config.get("max_skeleton_attempts", 3)),
            "rewrite_model": as_model_list(config["rewrite_model"]),
            "skeleton_model": as_model_list(config["skeleton_model"]),
            "fill_model": as_model_list(config["fill_model"]),
            "request_retries": config.get("request_retries", 4),
            "request_backoff_base_sec": config.get("request_backoff_base_sec", 1.5),
            "request_backoff_multiplier": config.get("request_backoff_multiplier", 2.0),
            "request_backoff_max_sec": config.get("request_backoff_max_sec", 20.0),
            "request_backoff_jitter_sec": config.get("request_backoff_jitter_sec", 0.35),
        },
        "model_log_path": str(model_log_path),
        "rewrite": {}, "skeleton": {}, "fills": [], "summary": {},
    }
    if args.debug:
        trace["debug"] = {"enabled": True, "char_limit": args.debug_char_limit}

    def persist():
        write_trace(trace_path, trace)

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
        formal_statement = normalize_formal_statement(formal_path.read_text(encoding="utf-8"))
        formal_statement = ensure_generated_imports(formal_statement, target_path)
    except Exception as e:
        fail(f"Formal statement normalization failed: {e}")
    persist()
    if args.debug:
        print(f"[DEBUG] normalized formal statement chars={len(formal_statement)}", flush=True)
        print(f"[DEBUG] formal statement preview:\n{preview_text(formal_statement, limit=args.debug_char_limit)}", flush=True)

    # Pre-flight: verify imports
    import_lines = extract_imports(formal_statement)
    if import_lines:
        print("Verifying imports...", flush=True)
        try:
            import_results = verify_imports(import_lines, repo_root)
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

    # Step 1: Rewrite
    print("Step 1: Rewrite -> Angelito...", flush=True)
    rewrite_attempts: list[dict] = []
    try:
        angelito_proof = rewrite_stage.run(
            informal_path, formal_statement, config,
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
        print(f"[DEBUG] angelito chars={len(angelito_proof)} preview:\n{preview_text(angelito_proof, limit=args.debug_char_limit)}", flush=True)

    # Step 2: Skeleton
    print("Step 2: Skeleton generation...", flush=True)
    trace["skeleton"] = {"compile_attempts": []}
    persist()
    try:
        skel_result = skeleton_stage.run(
            formal_statement, angelito_proof, config,
            target_path=target_path, repo_root=repo_root, target_rel=target_rel,
            debug=args.debug, debug_char_limit=args.debug_char_limit,
            persist_fn=persist, trace=trace,
        )
    except RuntimeError as e:
        fail(str(e))

    proof_template = skel_result["proof_template"]
    slot_values = skel_result["slot_values"]
    rendered_skeleton = skel_result["rendered_skeleton"]
    has_admits = skel_result["has_admits"]

    if not has_admits:
        write_proof_to_file(target_path, formal_statement, rendered_skeleton, use_admitted=False)
        trace["skeleton"]["full_file_text"] = format_proof_file_content(formal_statement, rendered_skeleton, use_admitted=False)
        trace["status"] = "success"
        trace["summary"] = {"admits_filled": 0, "total_attempts": 0}
        trace["ended_at"] = datetime.now().isoformat(timespec="seconds")
        persist()
        print("  Skeleton is already a complete proof!", flush=True)
        print(f"Trace: {trace_path}")
        print("Done.", flush=True)
        return

    from pipeline.proof_template import count_rendered_admits
    print(f"  Skeleton has {count_rendered_admits(rendered_skeleton)} admit(s) to fill.", flush=True)
    if args.debug:
        print(f"[DEBUG] entering fill loop with slot_names={[slot.name for slot in proof_template.slots]}", flush=True)

    # Step 3: Fill
    try:
        fill_result = fill_stage.run(
            formal_statement, angelito_proof, proof_template, slot_values, config,
            target_path=target_path, repo_root=repo_root, target_rel=target_rel,
            debug=args.debug, debug_char_limit=args.debug_char_limit,
            persist_fn=persist, trace=trace,
        )
    except RuntimeError as e:
        fail(str(e))

    # Final: write clean proof with Qed.
    proof_body = fill_result["proof_body"]
    write_proof_to_file(target_path, formal_statement, proof_body, use_admitted=False)
    exit_code, stdout, stderr = run_check_target(repo_root, target_rel)
    if exit_code != 0:
        fail(f"Final proof does not compile:\n{stderr or stdout}")

    trace["summary"] = {
        "admits_filled": fill_result["admits_filled"],
        "total_attempts": fill_result["total_attempts"],
        "slot_count": fill_result["slot_count"],
    }
    trace["status"] = "success"
    trace["ended_at"] = datetime.now().isoformat(timespec="seconds")
    persist()
    print(f"\nSummary: filled {fill_result['admits_filled']} admit(s) in {fill_result['total_attempts']} total attempt(s).", flush=True)
    print(f"Trace: {trace_path}", flush=True)
    print("Done.", flush=True)


if __name__ == "__main__":
    main()
