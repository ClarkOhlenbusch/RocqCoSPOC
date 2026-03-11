"""
Read/write Coq .v file: append or replace tactic block, track last line for state capture.
"""

import re
from pathlib import Path
from typing import Optional


class CoqEditor:
    """Edits a single .v file: locates Proof. ... Qed., appends tactics, can replace last block."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lines: list[str] = []
        self._proof_start: Optional[int] = None   # 0-based index of line containing "Proof."
        self._proof_end: Optional[int] = None     # 0-based index of line containing "Qed." or end of body
        self._last_block_start: Optional[int] = None  # 0-based line index of first line of last tactic block
        self._last_block_end: Optional[int] = None   # 0-based line index of last line of last tactic block

    def read(self) -> None:
        if not self.path.exists():
            self._lines = []
            self._proof_start = self._proof_end = None
            return
        self._lines = self.path.read_text(encoding="utf-8").splitlines()
        self._find_proof()

    def _find_proof(self) -> None:
        self._proof_start = None
        self._proof_end = None
        for i, line in enumerate(self._lines):
            stripped = line.strip()
            if re.match(r"^\s*Proof\.\s*$", line):
                self._proof_start = i
            if self._proof_start is not None and re.match(r"^\s*Qed\.\s*$", line):
                self._proof_end = i
                break
        if self._proof_start is not None and self._proof_end is None:
            # Proof. with no Qed. yet
            self._proof_end = len(self._lines)

    def has_proof_block(self) -> bool:
        return self._proof_start is not None

    def ensure_proof(self) -> bool:
        """Ensure there is a Proof. line. Returns True if already present or added."""
        if self._proof_start is not None:
            return True
        # Append Proof. at end if file has content
        if self._lines and self._lines[-1].strip():
            self._lines.append("Proof.")
            self._proof_start = len(self._lines) - 1
            self._proof_end = len(self._lines)
            return True
        return False

    def append_tactics(self, tactic_text: str) -> int:
        """
        Append tactic block to the proof body (before Qed. if present).
        tactic_text can be multiple lines. Each line is indented with 2 spaces.
        Returns the 1-based line number of the last line added (for get-proof-state -CursorLine).
        """
        if self._proof_start is None:
            raise ValueError("No Proof. block in file; add theorem statement and Proof. first")
        # Normalize: ensure each line ends without trailing newline, indent with 2 spaces
        tactic_lines = []
        for line in tactic_text.strip().splitlines():
            line = line.strip()
            if line:
                tactic_lines.append("  " + line if not line.startswith("  ") else line)
        if not tactic_lines:
            return self._last_line_of_proof_body_1based()

        # Insert before Qed. or at end
        insert_idx = self._proof_end if self._proof_end is not None else len(self._lines)
        # If there's a Qed., the line at _proof_end is "Qed." so we insert before it
        for j, t in enumerate(tactic_lines):
            self._lines.insert(insert_idx + j, t)
        self._proof_end = (self._proof_end or len(self._lines)) + len(tactic_lines)
        self._last_block_start = insert_idx
        self._last_block_end = insert_idx + len(tactic_lines) - 1
        # 1-based last line
        return self._last_block_end + 1

    def replace_last_tactic_block(self, new_tactic_text: str) -> int:
        """
        Replace the last appended tactic block with new_tactic_text.
        Returns the 1-based line number of the last line after replacement.
        """
        if self._last_block_start is None or self._last_block_end is None:
            raise ValueError("No previous tactic block to replace")
        tactic_lines = []
        for line in new_tactic_text.strip().splitlines():
            line = line.strip()
            if line:
                tactic_lines.append("  " + line if not line.startswith("  ") else line)
        if not tactic_lines:
            return self._last_block_end + 1

        # Replace lines [_last_block_start .. _last_block_end] with new lines
        n_old = self._last_block_end - self._last_block_start + 1
        for _ in range(n_old):
            self._lines.pop(self._last_block_start)
        for j, t in enumerate(tactic_lines):
            self._lines.insert(self._last_block_start + j, t)
        self._proof_end = (self._proof_end or 0) - n_old + len(tactic_lines)
        self._last_block_end = self._last_block_start + len(tactic_lines) - 1
        return self._last_block_end + 1

    def _last_line_of_proof_body_1based(self) -> int:
        """1-based line number of the last line of the proof body (before Qed.)."""
        if self._proof_end is None:
            return len(self._lines)
        return self._proof_end

    def get_cursor_line_for_state(self) -> int:
        """1-based line number suitable for get-proof-state.ps1 -CursorLine (last line of proof body)."""
        if self._last_block_end is not None:
            return self._last_block_end + 1
        if self._proof_end is not None and self._proof_end > 0:
            return self._proof_end
        return (self._proof_start or 0) + 1

    def write(self) -> None:
        self.path.write_text("\n".join(self._lines) + "\n", encoding="utf-8")

    def get_content(self) -> str:
        return "\n".join(self._lines)
