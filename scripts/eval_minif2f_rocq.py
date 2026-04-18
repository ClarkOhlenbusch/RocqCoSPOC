#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import subprocess
import sys
import textwrap
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from datasets import load_dataset


REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class CaseArtifacts:
    case_index: int
    case_name: str
    split: str
    case_dir: Path
    informal_path: Path
    formal_path: Path
    target_path: Path
    trace_path: Path
    stdout_path: Path
    stderr_path: Path


def _slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", text.strip())
    cleaned = cleaned.strip("-").lower()
    return cleaned or "case"


def _first_line(text: str, limit: int = 140) -> str:
    line = (text or "").strip().splitlines()
    if not line:
        return "(empty)"
    s = line[0].strip()
    if len(s) <= limit:
        return s
    return s[: limit - 3] + "..."


def _append_model_attempt_blocks(
    lines: list[str],
    *,
    heading: str,
    attempts: list[dict[str, Any]],
) -> None:
    if not attempts:
        return
    lines.append(f"**{heading}**")
    lines.append("")
    for idx, attempt in enumerate(attempts, start=1):
        lines.append(
            f"- Attempt {idx}: status=`{attempt.get('status', 'unknown')}`, "
            f"model=`{attempt.get('model', 'unknown')}`"
        )
        raw_output = str(attempt.get("raw_output", "") or "").strip()
        parsed_output = str(attempt.get("parsed_output", "") or "").strip()
        error = str(attempt.get("error", "") or "").strip()
        if raw_output:
            lines.append("")
            lines.append("```text")
            lines.append(raw_output)
            lines.append("```")
        if parsed_output and parsed_output != raw_output:
            lines.append("")
            lines.append("Parsed as:")
            lines.append("```text")
            lines.append(parsed_output)
            lines.append("```")
        if error:
            lines.append("")
            lines.append(f"Parser/compiler note: `{error}`")
        lines.append("")


def _safe_read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _failure_stage(
    trace: dict[str, Any] | None,
    return_code: int,
    *,
    stdout_text: str = "",
    stderr_text: str = "",
) -> str:
    if return_code == 0:
        return "none"
    if not trace:
        return "pipeline_crash_no_trace"
    error = str(trace.get("error", ""))
    fills = trace.get("fills") or []
    skeleton_attempts = (trace.get("skeleton") or {}).get("compile_attempts") or []
    last_fill = fills[-1] if fills else {}
    last_fill_status = last_fill.get("status")
    last_fill_stderr = str(last_fill.get("stderr", "") or "")
    stderr_text = stderr_text or ""
    if error.startswith("Rewrite failed"):
        return "rewrite"
    if error.startswith("Skeleton"):
        return "skeleton"
    if error.startswith("  Fill model error:") or error.startswith("Fill model error:"):
        return "fill_model_error"
    if error.startswith("Failed to fill admit"):
        if "timed out" in last_fill_stderr.lower():
            return "fill_compile_timeout"
        if last_fill_status == "compile_error":
            return "fill_compile_error"
        if last_fill_status == "model_error":
            return "fill_model_error"
        return "fill"
    if error.startswith("Final proof does not compile"):
        return "final_compile"
    if fills:
        if "timed out" in last_fill_stderr.lower():
            return "fill_compile_timeout"
        if last_fill_status == "compile_error":
            return "fill_compile_error"
        if last_fill_status == "model_error":
            return "fill_model_error"
    if skeleton_attempts:
        last_skeleton = skeleton_attempts[-1]
        if not last_skeleton.get("compiles", True):
            if "timed out" in str(last_skeleton.get("stderr", "")).lower():
                return "skeleton_compile_timeout"
            return "skeleton_compile_error"
    if "TimeoutExpired" in stderr_text or "timed out after" in stderr_text.lower():
        if fills:
            return "fill_compile_timeout"
        if skeleton_attempts:
            return "skeleton_compile_timeout"
        return "pipeline_timeout"
    if trace.get("status") == "running":
        return "pipeline_interrupted"
    return "unknown"


def _display_skeleton_attempt_status(attempt: dict[str, Any]) -> str:
    status = str(attempt.get("status", "") or "").strip()
    if status:
        return status
    if attempt.get("compiles", False):
        return "compiled"
    if "error" in attempt:
        return "model_error"
    return "compile_error"


def _build_formal_text(case_row: dict[str, Any]) -> str:
    header = str(case_row.get("header", "") or "").strip()
    statement = str(case_row.get("rocq_statement", "") or "").strip()
    if not statement:
        raise ValueError("Missing `rocq_statement` in dataset row.")
    if header:
        return f"{header}\n\n{statement}\n"
    return statement + "\n"


def _build_informal_text(case_row: dict[str, Any]) -> tuple[str, str]:
    informal_proof = str(case_row.get("informal_proof", "") or "").strip()
    informal_statement = str(case_row.get("informal_statement", "") or "").strip()
    if informal_proof:
        return informal_proof + "\n", "informal_proof"
    if informal_statement:
        return informal_statement + "\n", "informal_statement_fallback"
    raise ValueError("Both `informal_proof` and `informal_statement` are empty.")


def _prepare_case_files(
    out_dir: Path,
    dataset_name: str,
    case_index: int,
    case_row: dict[str, Any],
) -> CaseArtifacts:
    case_name = str(case_row.get("name", f"row-{case_index}"))
    split = str(case_row.get("split", "unknown"))
    slug = _slugify(f"{case_index:03d}-{case_name}")
    case_dir = out_dir / "cases" / slug
    case_dir.mkdir(parents=True, exist_ok=True)

    informal_text, informal_source = _build_informal_text(case_row)
    formal_text = _build_formal_text(case_row)

    informal_path = case_dir / "informal.txt"
    formal_path = case_dir / "formal.v"
    target_path = case_dir / "target.v"
    trace_path = case_dir / "trace.json"
    stdout_path = case_dir / "pipeline.stdout.txt"
    stderr_path = case_dir / "pipeline.stderr.txt"
    metadata_path = case_dir / "case_metadata.json"

    informal_path.write_text(informal_text, encoding="utf-8")
    formal_path.write_text(formal_text, encoding="utf-8")

    metadata = {
        "dataset": dataset_name,
        "case_index": case_index,
        "case_name": case_name,
        "split": split,
        "informal_source": informal_source,
        "original_row": case_row,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")

    return CaseArtifacts(
        case_index=case_index,
        case_name=case_name,
        split=split,
        case_dir=case_dir,
        informal_path=informal_path,
        formal_path=formal_path,
        target_path=target_path,
        trace_path=trace_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )


def _run_pipeline_for_case(artifacts: CaseArtifacts, max_fill_attempts: int | None) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(REPO_ROOT / "pipeline" / "run.py"),
        "--informal",
        str(artifacts.informal_path),
        "--formal",
        str(artifacts.formal_path),
        "--target",
        str(artifacts.target_path),
        "--trace-out",
        str(artifacts.trace_path),
    ]
    if max_fill_attempts is not None:
        cmd += ["--max-fill-attempts", str(max_fill_attempts)]

    started = time.time()
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    elapsed_sec = round(time.time() - started, 3)

    artifacts.stdout_path.write_text(proc.stdout or "", encoding="utf-8")
    artifacts.stderr_path.write_text(proc.stderr or "", encoding="utf-8")

    trace = _safe_read_json(artifacts.trace_path)
    rewrite_attempts = len((trace or {}).get("rewrite", {}).get("model_attempts", []))
    skeleton_compile_attempts = len((trace or {}).get("skeleton", {}).get("compile_attempts", []))
    fill_attempts = len((trace or {}).get("fills", []))
    fill_compile_errors = sum(
        1 for f in (trace or {}).get("fills", []) if f.get("status") == "compile_error"
    )
    fill_successes = sum(1 for f in (trace or {}).get("fills", []) if f.get("status") == "success")

    case_result = {
        "case_index": artifacts.case_index,
        "case_name": artifacts.case_name,
        "split": artifacts.split,
        "paths": {
            "case_dir": str(artifacts.case_dir),
            "informal": str(artifacts.informal_path),
            "formal": str(artifacts.formal_path),
            "target": str(artifacts.target_path),
            "trace": str(artifacts.trace_path),
            "stdout": str(artifacts.stdout_path),
            "stderr": str(artifacts.stderr_path),
        },
        "command": cmd,
        "return_code": proc.returncode,
        "elapsed_sec": elapsed_sec,
        "trace_status": (trace or {}).get("status", "missing"),
        "failure_stage": _failure_stage(
            trace,
            proc.returncode,
            stdout_text=proc.stdout or "",
            stderr_text=proc.stderr or "",
        ),
        "counts": {
            "rewrite_model_attempts": rewrite_attempts,
            "skeleton_compile_attempts": skeleton_compile_attempts,
            "fill_attempts": fill_attempts,
            "fill_success_attempts": fill_successes,
            "fill_compile_errors": fill_compile_errors,
        },
        "trace": trace,
    }

    return case_result


def _format_aggregate_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    successes = [r for r in results if r["return_code"] == 0 and r["trace_status"] == "success"]
    failure_counter = Counter(r["failure_stage"] for r in results if r["failure_stage"] != "none")

    total_fill_attempts = [r["counts"]["fill_attempts"] for r in results]
    total_elapsed = [r["elapsed_sec"] for r in results]

    successful_total_attempts = []
    for result in successes:
        trace = result.get("trace") or {}
        summary = trace.get("summary") or {}
        if "total_attempts" in summary:
            successful_total_attempts.append(summary["total_attempts"])

    return {
        "num_cases": len(results),
        "num_success": len(successes),
        "success_rate": (len(successes) / len(results)) if results else 0.0,
        "failure_stage_counts": dict(failure_counter),
        "fill_attempts_mean": statistics.mean(total_fill_attempts) if total_fill_attempts else 0.0,
        "elapsed_sec_mean": statistics.mean(total_elapsed) if total_elapsed else 0.0,
        "elapsed_sec_total": sum(total_elapsed),
        "successful_total_attempts_mean": (
            statistics.mean(successful_total_attempts) if successful_total_attempts else 0.0
        ),
    }


def _build_report_markdown(
    *,
    dataset_name: str,
    split: str,
    seed: int,
    results: list[dict[str, Any]],
    aggregate: dict[str, Any],
    generated_at: str,
) -> str:
    lines: list[str] = []

    lines.append("# MiniF2F-Rocq Pipeline Evaluation (10 Cases)")
    lines.append("")
    lines.append("## Abstract")
    lines.append("")
    lines.append(
        "This report evaluates the Rocq proof pipeline on 10 sampled tasks from "
        f"`{dataset_name}` (`{split}` split). For each case, we record the exact informal proof input, "
        "all stage traces (rewrite, skeleton, fill), attempt counts, and failure points."
    )
    lines.append("")
    lines.append("## Experimental Setup")
    lines.append("")
    lines.append(f"- Dataset: `{dataset_name}`")
    lines.append(f"- Split: `{split}`")
    lines.append(f"- Cases: `{len(results)}`")
    lines.append(f"- Sampling seed: `{seed}`")
    lines.append("- Pipeline: `pipeline/run.py` (Step 1 rewrite, Step 2 skeleton, Step 3 iterative fill)")
    lines.append(f"- Generated at: `{generated_at}`")
    lines.append("")
    lines.append("## Aggregate Results")
    lines.append("")
    lines.append(f"- Successes: `{aggregate['num_success']}/{aggregate['num_cases']}`")
    lines.append(f"- Success rate: `{aggregate['success_rate']:.1%}`")
    lines.append(f"- Mean runtime per case: `{aggregate['elapsed_sec_mean']:.2f}s`")
    lines.append(f"- Total runtime: `{aggregate['elapsed_sec_total']:.2f}s`")
    lines.append(f"- Mean fill attempts per case: `{aggregate['fill_attempts_mean']:.2f}`")
    lines.append(
        "- Mean total attempts for successful cases: "
        f"`{aggregate['successful_total_attempts_mean']:.2f}`"
    )
    if aggregate["failure_stage_counts"]:
        lines.append("- Failure stages:")
        for stage, count in sorted(aggregate["failure_stage_counts"].items()):
            lines.append(f"  - `{stage}`: `{count}`")
    else:
        lines.append("- Failure stages: none")
    lines.append("")
    lines.append("## Case Index")
    lines.append("")
    lines.append("| # | Case | Status | Failure Stage | Runtime (s) | Fill Attempts |")
    lines.append("|---|------|--------|---------------|-------------|---------------|")
    for result in results:
        status = "success" if result["return_code"] == 0 else "failed"
        lines.append(
            "| "
            f"{result['case_index']} | "
            f"{result['case_name']} | "
            f"{status} | "
            f"{result['failure_stage']} | "
            f"{result['elapsed_sec']:.2f} | "
            f"{result['counts']['fill_attempts']} |"
        )
    lines.append("")
    lines.append("## Detailed Case Logs")
    lines.append("")

    for result in results:
        trace = result.get("trace") or {}
        metadata_path = Path(result["paths"]["case_dir"]) / "case_metadata.json"
        metadata = _safe_read_json(metadata_path) or {}
        row = metadata.get("original_row") or {}
        informal_source = metadata.get("informal_source", "unknown")
        informal_text = Path(result["paths"]["informal"]).read_text(encoding="utf-8")
        formal_text = Path(result["paths"]["formal"]).read_text(encoding="utf-8")

        lines.append(f"### Case {result['case_index']}: `{result['case_name']}`")
        lines.append("")
        lines.append(f"- Split: `{result['split']}`")
        lines.append(f"- Return code: `{result['return_code']}`")
        lines.append(f"- Trace status: `{result['trace_status']}`")
        lines.append(f"- Failure stage: `{result['failure_stage']}`")
        lines.append(f"- Runtime: `{result['elapsed_sec']:.2f}s`")
        lines.append("")
        lines.append("**Input Informal Statement**")
        lines.append("")
        lines.append("```text")
        lines.append(str(row.get("informal_statement", "")).strip() or "(empty)")
        lines.append("```")
        lines.append("")
        lines.append(f"**Exact Informal Proof Used** (`{informal_source}`)")
        lines.append("")
        lines.append("```text")
        lines.append(informal_text.strip() or "(empty)")
        lines.append("```")
        lines.append("")
        lines.append("**Formal Statement File Used**")
        lines.append("")
        lines.append("```coq")
        lines.append(formal_text.strip() or "(empty)")
        lines.append("```")
        lines.append("")
        lines.append("**Step Outcomes and Attempt Counts**")
        lines.append("")

        rewrite_attempts = (trace.get("rewrite") or {}).get("model_attempts", [])
        lines.append(f"- Step 1 (rewrite): `{len(rewrite_attempts)}` model attempt(s)")
        for i, attempt in enumerate(rewrite_attempts, start=1):
            lines.append(
                f"  - attempt {i}: status=`{attempt.get('status', 'unknown')}`, "
                f"model=`{attempt.get('model', 'unknown')}`"
            )

        skeleton_attempts = (trace.get("skeleton") or {}).get("compile_attempts", [])
        lines.append(f"- Step 2 (skeleton): `{len(skeleton_attempts)}` compile attempt(s)")
        for s in skeleton_attempts:
            lines.append(
                f"  - compile attempt {s.get('attempt', '?')}: "
                f"status=`{_display_skeleton_attempt_status(s)}`, compiles=`{s.get('compiles', False)}`"
            )

        fills = trace.get("fills") or []
        lines.append(f"- Step 3 (fill): `{len(fills)}` total fill attempt(s)")
        if fills:
            lines.append("")
            lines.append("| Fill # | Slot | Attempt | Status | Exit Code | Replacement Summary |")
            lines.append("|--------|------|---------|--------|-----------|---------------------|")
            for idx, fill in enumerate(fills, start=1):
                lines.append(
                    "| "
                    f"{idx} | "
                    f"{fill.get('slot_name', '?')} | "
                    f"{fill.get('attempt', '?')} | "
                    f"{fill.get('status', '?')} | "
                    f"{fill.get('exit_code', '?')} | "
                    f"{_first_line(fill.get('replacement', ''))} |"
                )

            lines.append("")
            lines.append("**Step 3 Detailed Attempts**")
            lines.append("")
            for idx, fill in enumerate(fills, start=1):
                lines.append(
                    f"#### Step 3 Fill Attempt {idx}"
                )
                lines.append("")
                lines.append(
                    f"- Slot: `{fill.get('slot_name', '?')}`"
                )
                lines.append(
                    f"- Attempt: `{fill.get('attempt', '?')}`"
                )
                lines.append(
                    f"- Status: `{fill.get('status', '?')}`"
                )
                lines.append(
                    f"- Exit code: `{fill.get('exit_code', '?')}`"
                )
                current_goal_state = str(fill.get("current_goal_state", "") or "").strip()
                if current_goal_state:
                    lines.append("")
                    lines.append("Goal state:")
                    lines.append("```text")
                    lines.append(current_goal_state)
                    lines.append("```")
                _append_model_attempt_blocks(
                    lines,
                    heading="Model Outputs",
                    attempts=fill.get("model_attempts") or [],
                )
                replacement = str(fill.get("replacement", "") or "").strip()
                if replacement:
                    lines.append("Replacement inserted:")
                    lines.append("```coq")
                    lines.append(replacement)
                    lines.append("```")
                    lines.append("")
                stderr_text = str(fill.get("stderr", "") or "").strip()
                if stderr_text:
                    lines.append("Compiler stderr:")
                    lines.append("```text")
                    lines.append(stderr_text)
                    lines.append("```")
                    lines.append("")

        _append_model_attempt_blocks(
            lines,
            heading="Step 1 Raw Model Outputs",
            attempts=rewrite_attempts,
        )

        skeleton_model_attempts = []
        for attempt in skeleton_attempts:
            for model_attempt in attempt.get("model_attempts") or []:
                skeleton_model_attempts.append(model_attempt)
        _append_model_attempt_blocks(
            lines,
            heading="Step 2 Raw Model Outputs",
            attempts=skeleton_model_attempts,
        )

        failure_points = []
        if result["failure_stage"] != "none":
            if trace.get("error"):
                failure_points.append(str(trace["error"]))
            for fill in fills:
                if fill.get("status") == "model_error":
                    failure_points.append(
                        f"slot={fill.get('slot_name', '?')} attempt={fill.get('attempt', '?')} "
                        f"model_error={_first_line(fill.get('error', ''), limit=220)}"
                    )
                if fill.get("status") == "compile_error":
                    failure_points.append(
                        f"slot={fill.get('slot_name', '?')} attempt={fill.get('attempt', '?')} "
                        f"error={_first_line(fill.get('stderr', ''), limit=220)}"
                    )
            if result["return_code"] != 0 and Path(result["paths"]["stderr"]).exists():
                stderr_text = Path(result["paths"]["stderr"]).read_text(encoding="utf-8").strip()
                if stderr_text:
                    failure_points.append(f"pipeline_stderr={_first_line(stderr_text, limit=220)}")

        lines.append("")
        lines.append("**Failure Points**")
        lines.append("")
        if failure_points:
            for fp in failure_points[:12]:
                lines.append(f"- {fp}")
        else:
            lines.append("- none")

        lines.append("")
        lines.append("**Artifacts**")
        lines.append("")
        lines.append(f"- Trace: `{result['paths']['trace']}`")
        model_log_path = str(trace.get("model_log_path", "") or "").strip()
        if model_log_path:
            lines.append(f"- Model log: `{model_log_path}`")
        lines.append(f"- Target proof file: `{result['paths']['target']}`")
        lines.append(f"- Pipeline stdout: `{result['paths']['stdout']}`")
        lines.append(f"- Pipeline stderr: `{result['paths']['stderr']}`")
        lines.append("")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a 10-case MiniF2F-Rocq evaluation and generate a paper-style report."
    )
    parser.add_argument("--dataset", default="LLM4Rocq/miniF2F-rocq")
    parser.add_argument("--split", default="valid")
    parser.add_argument("--num-cases", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-fill-attempts", type=int, default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for eval artifacts. Defaults to pipeline/evals/minif2f-rocq-<timestamp>.",
    )
    args = parser.parse_args()

    if args.num_cases <= 0:
        raise ValueError("--num-cases must be positive.")

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = args.output_dir or (REPO_ROOT / "pipeline" / "evals" / f"minif2f-rocq-{ts}")
    out_dir = out_dir if out_dir.is_absolute() else REPO_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[eval] Loading dataset {args.dataset} ({args.split})...")
    dataset = load_dataset(args.dataset, split=args.split)
    if len(dataset) < args.num_cases:
        raise ValueError(
            f"Requested {args.num_cases} cases but split has only {len(dataset)} rows."
        )

    indices = list(range(len(dataset)))
    rng = random.Random(args.seed)
    selected = sorted(rng.sample(indices, args.num_cases))
    print(f"[eval] Selected indices: {selected}")

    selection_manifest = {
        "dataset": args.dataset,
        "split": args.split,
        "seed": args.seed,
        "num_cases": args.num_cases,
        "selected_indices": selected,
    }
    (out_dir / "selection.json").write_text(
        json.dumps(selection_manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    results: list[dict[str, Any]] = []
    for case_number, dataset_idx in enumerate(selected, start=1):
        row = dict(dataset[dataset_idx])
        case_name = str(row.get("name", f"row-{dataset_idx}"))
        print(f"[eval] ({case_number}/{len(selected)}) {dataset_idx}: {case_name}")
        artifacts = _prepare_case_files(out_dir, args.dataset, dataset_idx, row)
        result = _run_pipeline_for_case(artifacts, args.max_fill_attempts)
        results.append(result)
        status = "OK" if result["return_code"] == 0 else "FAIL"
        print(
            f"[eval]   -> {status}, trace_status={result['trace_status']}, "
            f"failure_stage={result['failure_stage']}, elapsed={result['elapsed_sec']:.2f}s"
        )

    aggregate = _format_aggregate_metrics(results)
    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "dataset": args.dataset,
        "split": args.split,
        "seed": args.seed,
        "num_cases": args.num_cases,
        "aggregate": aggregate,
        "results": results,
    }
    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    report = _build_report_markdown(
        dataset_name=args.dataset,
        split=args.split,
        seed=args.seed,
        results=results,
        aggregate=aggregate,
        generated_at=summary["generated_at"],
    )
    report_path = out_dir / "report.md"
    report_path.write_text(report, encoding="utf-8")

    short = textwrap.dedent(
        f"""
        [eval] Complete.
        [eval] Output dir: {out_dir}
        [eval] Summary:    {summary_path}
        [eval] Report:     {report_path}
        [eval] Successes:  {aggregate['num_success']}/{aggregate['num_cases']} ({aggregate['success_rate']:.1%})
        """
    ).strip()
    print(short)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
