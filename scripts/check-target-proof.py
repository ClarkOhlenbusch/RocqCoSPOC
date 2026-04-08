#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from coq_script_utils import find_project_root, parse_coqproject, resolve_coqc, run_subprocess


def _to_rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def run_check(file_path: Path) -> int:
    file_path = file_path.resolve()
    if not file_path.exists():
        print(f"Target file not found: {file_path}", file=sys.stderr)
        return 1

    repo_root = find_project_root(file_path)
    coq_bin = resolve_coqc()
    coq_args, _ = parse_coqproject(repo_root)

    target_rel = _to_rel(file_path, repo_root)
    angelito_rel = "coq/Angelito.v"
    angelito_path = repo_root / angelito_rel

    if angelito_path.exists() and target_rel != angelito_rel:
        print(f"Checking {angelito_rel} ...")
        code, stdout, stderr = run_subprocess([coq_bin, *coq_args, angelito_rel], cwd=repo_root)
        if stdout:
            print(stdout, end="")
        if stderr:
            print(stderr, file=sys.stderr, end="")
        if code != 0:
            print(f"Proof check failed: {angelito_rel}", file=sys.stderr)
            return code

    print(f"Checking {target_rel} ...")
    code, stdout, stderr = run_subprocess([coq_bin, *coq_args, target_rel], cwd=repo_root)
    if stdout:
        print(stdout, end="")
    if stderr:
        print(stderr, file=sys.stderr, end="")
    if code != 0:
        print(f"Proof check failed: {target_rel}", file=sys.stderr)
        return code

    print(f"Proof check passed: {target_rel}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile a target Coq proof file.")
    parser.add_argument("--file-path", required=True, help="Path to target .v file.")
    args = parser.parse_args()
    return run_check(Path(args.file_path))


if __name__ == "__main__":
    sys.exit(main())
