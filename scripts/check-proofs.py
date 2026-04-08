#!/usr/bin/env python3

from __future__ import annotations

import sys
from pathlib import Path

from coq_script_utils import parse_coqproject, resolve_coqc, run_subprocess


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    coq_bin = resolve_coqc()
    coq_args, v_files = parse_coqproject(repo_root)

    for v_file in v_files:
        if not (repo_root / v_file).exists():
            continue
        print(f"Checking {v_file} ...")
        code, stdout, stderr = run_subprocess([coq_bin, *coq_args, v_file], cwd=repo_root)
        if stdout:
            print(stdout, end="")
        if stderr:
            print(stderr, file=sys.stderr, end="")
        if code != 0:
            print(f"Proof check failed: {v_file}", file=sys.stderr)
            return code

    print("All proofs checked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
