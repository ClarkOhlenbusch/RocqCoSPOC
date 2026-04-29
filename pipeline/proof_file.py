"""Proof file I/O and cursor math."""

import re
from pathlib import Path
from typing import Optional

from pipeline.coq import run_get_proof_state
from pipeline.utils import focused_proof_state

_ADMIT_LINE_RE = re.compile(r"^\s*[-+*{}]*\s*admit\.\s*$")


def find_admits(proof_text: str) -> list[int]:
    """Return 0-based line indices of admit. lines (including bullet-prefixed)."""
    return [i for i, line in enumerate(proof_text.splitlines()) if _ADMIT_LINE_RE.match(line)]


def format_proof_file_content(formal_statement: str, proof_body: str, use_admitted: bool) -> str:
    """Full .v contents: lemma/theorem, Proof., indented body, Qed./Admitted."""
    closing = "Admitted." if use_admitted else "Qed."
    indented = []
    for line in proof_body.splitlines():
        if line.strip():
            indented.append(f"  {line.rstrip()}")
        else:
            indented.append("")
    return f"{formal_statement}\nProof.\n" + "\n".join(indented) + f"\n{closing}\n"


def write_proof_to_file(target_path: Path, formal_statement: str, proof_body: str, use_admitted: bool):
    content = format_proof_file_content(formal_statement, proof_body, use_admitted)
    target_path.write_text(content, encoding="utf-8")


def proof_body_line_to_file_cursor(
    formal_statement: str,
    proof_body_line_index: int,
    *,
    target_path: Optional[Path] = None,
    before_line: bool = False,
) -> int:
    """Convert a 0-based proof-body line index to a 1-based file cursor line."""
    line_index = proof_body_line_index - 1 if before_line else proof_body_line_index
    if line_index < 0:
        line_index = 0
    if target_path is not None and target_path.exists():
        file_lines = target_path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(file_lines):
            if line.strip() == "Proof.":
                return i + 2 + line_index
    return len(formal_statement.splitlines()) + 2 + line_index


def should_snapshot_before_line(proof_body: str, proof_body_line_index: int) -> bool:
    if proof_body_line_index < 0:
        return True
    lines = proof_body.splitlines()
    if proof_body_line_index >= len(lines):
        return True
    target = lines[proof_body_line_index].lstrip()
    return not target.startswith(("-", "+", "*"))


def capture_goal_state_after_replacement(
    *, repo_root: Path, target_rel: str, target_path: Path,
    formal_statement: str, admit_idx: int, replacement: str,
) -> str:
    replacement_line_count = max(1, len(replacement.splitlines()))
    cursor_line = proof_body_line_to_file_cursor(
        formal_statement, admit_idx + replacement_line_count - 1,
        target_path=target_path, before_line=False,
    )
    return focused_proof_state(run_get_proof_state(repo_root, target_rel, cursor_line))


def normalize_formal_statement(text: str) -> str:
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


def ensure_generated_imports(formal_statement: str, target_path: Path) -> str:
    lines = formal_statement.splitlines()
    leading_imports: list[str] = []
    body_start = 0
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            leading_imports.append(line.rstrip())
            continue
        if re.match(r"^(Require|From|Import)\b", stripped):
            leading_imports.append(line.rstrip())
            continue
        body_start = idx
        break
    else:
        body_start = len(lines)

    normalized_imports = [line.strip() for line in leading_imports if line.strip()]
    joined_imports = " ".join(normalized_imports)
    generated_imports: list[str] = []

    _has_lia = any(m in joined_imports for m in ("Require Import Lia.", "From Coq Require Import Lia."))
    _has_arith_or_z = any(m in joined_imports for m in (
        "Require Import Arith.", "From Coq Require Import Arith.",
        "Require Import ZArith.", "From Coq Require Import ZArith.",
    ))
    if _has_arith_or_z and not _has_lia:
        generated_imports.append("Require Import Lia.")

    _has_reals = any(m in joined_imports for m in (
        "Require Import Reals.", "From Coq Require Import Reals.",
        "Require Import Coquelicot.", "From Coq Require Import Coquelicot.",
        "Coquelicot.Coquelicot",
    ))
    _has_lra = any(m in joined_imports for m in (
        "Require Import Lra.", "From Coq Require Import Lra.",
        "Require Import Psatz.", "From Coq Require Import Psatz.",
    ))
    if _has_reals and not _has_lra:
        generated_imports.append("Require Import Lra.")
        generated_imports.append("Require Import Psatz.")

    _has_field = any(m in joined_imports for m in (
        "Require Import Field.", "From Coq Require Import Field.",
        "Require Import Ring.", "From Coq Require Import Ring.",
    ))
    if _has_reals and not _has_field:
        generated_imports.append("Require Import Field.")

    prefix = [line for line in leading_imports if line.strip()]
    if generated_imports:
        prefix.extend(generated_imports)
    body = [line.rstrip() for line in lines[body_start:] if line.rstrip() or line == ""]
    sections: list[str] = []
    if prefix:
        sections.append("\n".join(prefix).strip())
    if body:
        sections.append("\n".join(body).strip())
    return "\n\n".join(section for section in sections if section).strip()
