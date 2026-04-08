#!/usr/bin/env python3
"""Shared helpers for Coq utility scripts."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import List, Sequence, Tuple

DEFAULT_COQ_BIN = Path(r"C:\Users\clark\scoop\apps\coq\2025.01.0\bin")


def _resolve_executable(preferred: Path, fallback_name: str) -> str:
    if preferred.exists():
        return str(preferred)
    fallback = shutil.which(fallback_name)
    if fallback:
        return fallback
    raise RuntimeError(
        f"Could not find '{preferred}' and '{fallback_name}' is not available on PATH."
    )


def resolve_coqc() -> str:
    return _resolve_executable(DEFAULT_COQ_BIN / "coqc.exe", "coqc")


def resolve_coqtop(explicit_path: str | None, project_root: Path) -> str:
    if explicit_path:
        candidate = Path(explicit_path).expanduser()
        if candidate.exists():
            return str(candidate.resolve())
        raise RuntimeError(f"The supplied --coqtop path was not found: {explicit_path}")

    settings_path = project_root / ".vscode" / "settings.json"
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            settings = {}

        vscoq_path = settings.get("vscoq.path")
        if isinstance(vscoq_path, str) and vscoq_path.strip():
            candidate = Path(vscoq_path).expanduser()
            if candidate.exists():
                coqtop_from_vscoq = candidate.with_name("coqtop.exe")
                if coqtop_from_vscoq.exists():
                    return str(coqtop_from_vscoq.resolve())

        coqtop_path = settings.get("coqtop.path")
        if isinstance(coqtop_path, str) and coqtop_path.strip():
            candidate = Path(coqtop_path).expanduser()
            if candidate.exists():
                return str(candidate.resolve())

    return _resolve_executable(DEFAULT_COQ_BIN / "coqtop.exe", "coqtop")


def parse_coqproject(project_root: Path) -> Tuple[List[str], List[str]]:
    coq_args: List[str] = []
    v_files: List[str] = []
    coq_project = project_root / "_CoqProject"
    if not coq_project.exists():
        return coq_args, v_files

    for raw_line in coq_project.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 3 and parts[0] in {"-R", "-Q"}:
            coq_args.extend([parts[0], parts[1], parts[2]])
            continue
        if line.endswith(".v"):
            v_files.append(line)

    return coq_args, v_files


def find_project_root(start_path: Path) -> Path:
    current = start_path.resolve()
    if current.is_file():
        current = current.parent

    for directory in [current, *current.parents]:
        if (directory / "_CoqProject").exists() or (directory / ".git").exists():
            return directory
    raise RuntimeError(f"Could not find project root for {start_path}")


def run_subprocess(command: Sequence[str], cwd: Path) -> Tuple[int, str, str]:
    import subprocess

    proc = subprocess.run(
        list(command),
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""
