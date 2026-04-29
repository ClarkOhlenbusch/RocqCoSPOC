"""Coq compilation, proof state capture, and import verification."""

import re
import subprocess
import sys
from pathlib import Path


def run_check_target(repo_root: Path, file_path_rel: str, *, timeout_sec: int = 60) -> tuple[int, str, str]:
    """Run check-target-proof.py. Returns (exit_code, stdout, stderr)."""
    script = repo_root / "scripts" / "check-target-proof.py"
    cmd = [sys.executable, str(script), "--file-path", file_path_rel]
    try:
        proc = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True, timeout=timeout_sec)
    except subprocess.TimeoutExpired as e:
        stdout = (e.stdout or "") if isinstance(e.stdout, str) else ""
        stderr = (e.stderr or "") if isinstance(e.stderr, str) else ""
        stderr = (
            (stderr + "\n") if stderr else ""
        ) + f"Proof check timed out after {timeout_sec} seconds for {file_path_rel}"
        return 124, stdout, stderr
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def run_get_proof_state(repo_root: Path, file_path_rel: str, cursor_line: int, *, timeout_sec: int = 60) -> str:
    """Run get-proof-state.py and return parsed proof state text, or empty string."""
    script = repo_root / "scripts" / "get-proof-state.py"
    cmd = [sys.executable, str(script), "--file-path", file_path_rel, "--cursor-line", str(cursor_line)]
    try:
        proc = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True, timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def extract_imports(formal_statement: str) -> list[str]:
    """Extract Require Import / From ... Require Import lines."""
    imports = []
    for line in formal_statement.splitlines():
        stripped = line.strip()
        if re.match(r"^(?:Require\s+Import|From\s+\S+\s+Require\s+Import)\b", stripped):
            imports.append(stripped)
    return imports


def verify_imports(imports: list[str], repo_root: Path, *, timeout_sec: int = 30) -> list[dict]:
    """Test each import line by writing a temp .v file and compiling with coqc."""
    from scripts.coq_script_utils import resolve_coqc, parse_coqproject

    coqc = resolve_coqc()
    coq_args, _ = parse_coqproject(repo_root)
    results = []
    tmp_name = "_import_check_tmp.v"
    tmp_path = repo_root / tmp_name
    try:
        for imp in imports:
            try:
                tmp_path.write_text(imp + "\n", encoding="utf-8")
                proc = subprocess.run(
                    [coqc, *coq_args, tmp_name],
                    cwd=str(repo_root), capture_output=True, text=True, timeout=timeout_sec,
                )
                ok = proc.returncode == 0
                error = (proc.stderr or "").strip() if not ok else ""
            except subprocess.TimeoutExpired:
                ok, error = False, f"Timed out after {timeout_sec}s"
            except Exception as e:
                ok, error = False, str(e)
            results.append({"import": imp, "ok": ok, "error": error})
    finally:
        tmp_path.unlink(missing_ok=True)
        for ext in (".vo", ".vok", ".vos", ".glob"):
            (repo_root / f"_import_check_tmp{ext}").unlink(missing_ok=True)
    return results
