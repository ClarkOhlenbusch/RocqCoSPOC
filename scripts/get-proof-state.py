#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from coq_script_utils import find_project_root, parse_coqproject, resolve_coqtop

DECLARATION_RE = re.compile(
    r"^\s*(Theorem|Lemma|Example|Corollary|Proposition|Remark|Fact|Definition|Goal)\b"
)
PROOF_OPEN_RE = re.compile(r"^\s*Proof\b")
PROOF_CLOSE_RE = re.compile(r"^\s*(Qed|Defined|Admitted|Abort)\.?\b")
PROMPT_RE = re.compile(r"^\S+\s*<\s*$")
GOALS_COUNT_RE = re.compile(r"^\d+\s+goals?$")


def parse_proof_state(output_text: str, state_label: str) -> str | None:
    if not output_text.strip():
        return None

    lines = output_text.splitlines()
    separator = "============================"
    sep_idx = -1
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip() == separator:
            sep_idx = i
            break

    if sep_idx < 0:
        return None

    hypotheses: list[str] = []
    for i in range(sep_idx - 1, -1, -1):
        line = lines[i].strip()
        if not line:
            continue
        if GOALS_COUNT_RE.match(line):
            break
        if line in {"No goals.", "No goals", "No more goals.", "No more goals"}:
            continue
        if line.startswith("Welcome to Coq") or line.startswith("Coq "):
            continue
        if PROMPT_RE.match(line):
            continue
        hypotheses.insert(0, line)

    goal: list[str] = []
    for i in range(sep_idx + 1, len(lines)):
        line = lines[i].strip()
        if not line:
            continue
        if line in {"No goals.", "No goals", "No more goals.", "No more goals"}:
            return f"{state_label}:\nNo Goals"
        if GOALS_COUNT_RE.match(line):
            continue
        if line.startswith("Welcome to Coq") or line.startswith("Coq "):
            continue
        if PROMPT_RE.match(line):
            continue
        if re.fullmatch(r"-+", line):
            continue
        goal.append(line)

    if not goal:
        return f"{state_label}:\nNo Goals"

    payload = [f"{state_label}:", *hypotheses, separator, "\n".join(goal)]
    return "\n".join(payload)


def locate_open_proof_depth(lines: list[str]) -> int:
    depth = 0
    for line in lines:
        if PROOF_OPEN_RE.match(line):
            depth += 1
        if PROOF_CLOSE_RE.match(line) and depth > 0:
            depth -= 1
    return depth


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture Coq proof state at a cursor line.")
    parser.add_argument("-FilePath", "--file-path", required=True, help="Path to Coq source file.")
    parser.add_argument(
        "-CursorLine", "--cursor-line", required=True, type=int, help="1-based cursor line number."
    )
    parser.add_argument("-StateName", "--state-name", default="State 0", help="Proof state label.")
    parser.add_argument("-CoqTop", "--coqtop", default=None, help="Explicit path to coqtop executable.")
    args = parser.parse_args()

    resolved_file = Path(args.file_path).expanduser().resolve()
    if not resolved_file.exists():
        print(f"Target file not found: {resolved_file}", file=sys.stderr)
        return 1

    repo_root = find_project_root(resolved_file)
    all_lines = resolved_file.read_text(encoding="utf-8").splitlines()
    line_count = len(all_lines)
    if args.cursor_line < 1 or args.cursor_line > line_count:
        print(
            f"Cursor line must be between 1 and {line_count} for file {resolved_file}",
            file=sys.stderr,
        )
        return 1

    idx = args.cursor_line - 1
    start = 0
    for i in range(idx, -1, -1):
        if DECLARATION_RE.match(all_lines[i]):
            start = i
            break

    prefix = all_lines[:start]
    snippet = all_lines[start : idx + 1]
    if locate_open_proof_depth(snippet) <= 0:
        print(f"{args.state_name}:")
        print("No Goals")
        return 0

    coqtop = resolve_coqtop(args.coqtop, repo_root)
    coq_args, _ = parse_coqproject(repo_root)
    cmd = [coqtop, "-q", *coq_args]
    script_text = "\n".join(
        [
            "(* Auto-generated proof state snapshot for agent pipeline. *)",
            *prefix,
            *snippet,
            "Show.",
            "Abort.",
        ]
    )

    proc = subprocess.run(
        cmd,
        cwd=str(repo_root),
        input=script_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    raw_out = proc.stdout or ""
    raw_err = proc.stderr or ""

    if raw_err.strip() and "Error:" in raw_err:
        print(raw_err, file=sys.stderr, end="" if raw_err.endswith("\n") else "\n")
        return 1

    if proc.returncode != 0 and not raw_out.strip():
        if raw_err.strip():
            print(raw_err, file=sys.stderr, end="" if raw_err.endswith("\n") else "\n")
        else:
            print(f"coqtop failed with code {proc.returncode}.", file=sys.stderr)
        return proc.returncode or 1

    state_text = parse_proof_state(f"{raw_out}\n{raw_err}", args.state_name)
    if not state_text:
        print("Could not parse coqtop output into a proof state.", file=sys.stderr)
        return 1
    print(state_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
