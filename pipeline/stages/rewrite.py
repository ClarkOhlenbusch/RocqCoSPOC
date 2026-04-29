"""Stage 1: Rewrite informal proof to strict Angelito syntax."""

import re
from pathlib import Path
from typing import Optional

from pipeline.config import REPO_ROOT
from pipeline.model import generate_with_format_retries
from pipeline.utils import strip_fences, truncate_for_error

# ---------------------------------------------------------------------------
# Angelito keywords and regexes
# ---------------------------------------------------------------------------

_ANGELITO_KEYWORDS = {
    "PROVE", "BEGIN", "END", "ASSUME", "GOAL", "SIMPLIFY", "APPLY", "SPLIT",
    "INDUCTION", "FACT", "WITNESS_AT", "FOR_ALL", "EXTRACT", "SINCE",
    "THEREFORE", "CONCLUDE", "INDUCTIVE_HYPOTHESIS",
}

_FORBIDDEN_ANGELITO_CONTINUATION_RE = re.compile(
    r"^(?:```|~~~|#{1,6}\s|/\*|\*/|//)"
    r"|^(?:Proof|Qed|Admitted)\.\s*$"
    r"|^(?:intro|intros|rewrite|apply|eapply|exact|reflexivity|lia|nia|ring|"
    r"simpl|cbn|destruct|induction|split|left|right)\b",
    re.IGNORECASE,
)

_PSEUDO_MATH_TOKENS = ("\u2211", "sum_{", "card {", "card{")
_SET_BUILDER_RE = re.compile(r"\{[^{}\n]*\|[^{}\n]*\}")

_NL_PROSE_RE = re.compile(
    r"\b(?:for each|for all|for every|there (?:are|is|exist[s]?)"
    r"|the (?:number|sum|total|count|product) of"
    r"|over all|sum over|summing)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_angelito_line_wrappers(line: str) -> str:
    stripped = line.strip()
    if stripped.startswith("[PROVE "):
        return line.replace("[PROVE ", "PROVE ", 1)
    if stripped == "END]":
        return line.replace("END]", "END")
    return line


def _extract_angelito_block(text: str) -> str:
    lines = [_normalize_angelito_line_wrappers(line) for line in text.splitlines()]
    prove_idx = next((i for i, line in enumerate(lines) if line.strip().startswith("PROVE ")), None)
    if prove_idx is not None:
        for end_idx in range(len(lines) - 1, prove_idx - 1, -1):
            if lines[end_idx].strip() == "END":
                return "\n".join(lines[prove_idx:end_idx + 1]).strip()
    return text.strip()


def _is_angelito_continuation_line(line: str, *, continuation_mode: Optional[str], split_into_re) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if continuation_mode == "split_into":
        return bool(split_into_re.match(stripped))
    if _FORBIDDEN_ANGELITO_CONTINUATION_RE.match(stripped):
        return False
    return True


def _fact_body(line: str) -> str:
    by_idx = line.find("[BY ")
    return line[:by_idx] if by_idx != -1 else line


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_angelito_rewrite(text: str, *, informal_proof: str = "", formal_statement: str = "") -> None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("Rewrite model returned empty output.")
    if not lines[0].startswith("PROVE "):
        raise ValueError(
            "Rewrite output is not strict Angelito: first non-empty line must start with 'PROVE '.\n"
            f"Raw output:\n{truncate_for_error(text)}"
        )
    if "BEGIN" not in lines:
        raise ValueError(
            "Rewrite output is not strict Angelito: expected BEGIN line after PROVE.\n"
            f"Raw output:\n{truncate_for_error(text)}"
        )
    if lines[-1] != "END":
        raise ValueError(
            "Rewrite output is not strict Angelito: missing final END line.\n"
            "The proof was likely cut off or continued past the required outer block. "
            "Return a shorter proof that ends with END.\n"
            f"Raw output:\n{truncate_for_error(text)}"
        )
    if not any(line.startswith("CONCLUDE") for line in lines):
        raise ValueError(
            "Rewrite output is not strict Angelito: expected at least one CONCLUDE line.\n"
            f"Raw output:\n{truncate_for_error(text)}"
        )

    bad_lines: list[str] = []
    continuation_mode: Optional[str] = None
    split_into_re = re.compile(r"^\(\d+\)\s+[A-Za-z0-9_]+:\s+.+$")
    for line in lines:
        keyword = line.split()[0].rstrip(":")
        if keyword in _ANGELITO_KEYWORDS:
            continuation_mode = None
            if keyword in {"SIMPLIFY", "GOAL", "THEREFORE", "FACT", "SINCE"}:
                continuation_mode = "default"
            elif keyword == "APPLY" and "SPLIT INTO:" in line:
                continuation_mode = "split_into"
            continue
        if _is_angelito_continuation_line(line, continuation_mode=continuation_mode, split_into_re=split_into_re):
            continue
        continuation_mode = None
        bad_lines.append(line)
    if bad_lines:
        joined = "\n".join(bad_lines[:5])
        raise ValueError(
            "Rewrite output contains non-Angelito lines.\n"
            f"Examples:\n{joined}\n\n"
            f"Raw output:\n{truncate_for_error(text)}"
        )

    pseudo_math_lines = [
        line for line in lines
        if any(tok in line for tok in _PSEUDO_MATH_TOKENS) or _SET_BUILDER_RE.search(line)
    ]
    if pseudo_math_lines:
        examples = "\n".join(pseudo_math_lines[:3])
        raise ValueError(
            "Rewrite contains pseudo-mathematical notation that cannot be translated to valid Rocq.\n"
            "Do not use set-builder notation like `card {a | ...}`, sigma notation like `sum_{...}` or \u2211, "
            "or set comprehensions like `{x | P x}`. "
            "Express counting and summation arguments in words or with named helper facts instead.\n"
            f"Examples:\n{examples}"
        )

    prose_fact_lines = [
        line for line in lines
        if line.split()[0].rstrip(":") in {"FACT", "THEREFORE"}
        and _NL_PROSE_RE.search(_fact_body(line))
    ]
    if prose_fact_lines:
        examples = "\n".join(prose_fact_lines[:3])
        raise ValueError(
            "Rewrite contains natural-language prose inside FACT or THEREFORE lines.\n"
            "Each FACT must state a symbolic proposition that can become a Rocq `assert`, "
            "not an English sentence. Use quantifiers like \u2200 and symbolic expressions "
            "instead of phrases like 'for each', 'there are', or 'the number of'.\n"
            "Example fix: replace `FACT h: for each integer a, P(a) [BY ...]` "
            "with `FACT h: \u2200 a : nat, P a [BY ...]`.\n"
            f"Examples:\n{examples}"
        )

    if informal_proof.strip():
        informal_lower = informal_proof.lower()
        informal_tokens = re.findall(r"\S+", informal_proof)
        answer_only = len(informal_tokens) <= 8 and len(informal_proof.strip().splitlines()) <= 2
        mentions_induction = any(token in informal_lower for token in ("induction", "inductive", "base case"))
        has_induction = any(line.startswith("INDUCTION ") for line in lines)
        has_split_apply = any(line.startswith("APPLY ") and "SPLIT INTO:" in line for line in lines)
        nested_proves = [line for line in lines[1:] if line.startswith("PROVE ")]

        if has_induction and not mentions_induction:
            raise ValueError(
                "Rewrite introduced INDUCTION even though the informal proof does not indicate an inductive proof shape.\n"
                "Keep the Angelito proof faithful to the given proof strategy.\n"
                f"Raw output:\n{truncate_for_error(text)}"
            )

        if answer_only:
            if has_split_apply or has_induction or nested_proves:
                raise ValueError(
                    "Informal proof is answer-only, but rewrite invented branching structure or nested subproofs.\n"
                    "Use a compact direct Angelito proof instead of introducing new cases or induction.\n"
                    f"Raw output:\n{truncate_for_error(text)}"
                )
            assume_lines = sum(1 for l in lines if l.startswith("ASSUME "))
            if len(lines) - assume_lines > 24:
                raise ValueError(
                    "Informal proof is answer-only, but rewrite is overexpanded.\n"
                    "Use a short direct Angelito proof with only the decisive steps.\n"
                    f"Raw output:\n{truncate_for_error(text)}"
                )


# ---------------------------------------------------------------------------
# Retry guidance
# ---------------------------------------------------------------------------

def _retry_guidance(stage: str, error: str, *, formal_statement: str = "") -> str:
    lowered = error.lower()
    hints = [
        "Rewrite repair rules:",
        "- Keep the Angelito proof short and structure-first.",
        "- Only preserve outer proof structure needed by later stages.",
        "- Collapse routine algebra or computation into one FACT or THEREFORE line instead of long equality chains.",
        "- Avoid nested APPLY ... SPLIT INTO or INDUCTION unless the informal proof genuinely uses them.",
        "- Output only the Angelito proof, starting with PROVE and ending with END.",
    ]
    if "missing final end line" in lowered or "expected begin line" in lowered:
        hints.append("- Your previous answer was likely cut off. Return a shorter proof with fewer lines.")
    if "non-angelito lines" in lowered:
        hints.append("- Put continuation text directly under the preceding Angelito keyword; do not add commentary outside that structure.")
    if "answer-only" in lowered:
        hints.append("- The informal proof is only an answer, so do not invent induction, cases, or nested subproofs.")
    if "introduced induction" in lowered:
        hints.append("- Do not use INDUCTION unless the informal proof explicitly says to argue by induction.")
    if "pseudo-mathematical notation" in lowered:
        hints.append("- Do not use set-builder notation like `card {a | ...}`, sigma notation like `sum_{...}` or \u2211, or set comprehensions like `{x | P x}`.")
        hints.append("- Express counting and summation using symbolic Rocq-like notation instead.")
    if "natural-language prose" in lowered:
        hints.append("- Every FACT and THEREFORE must be a symbolic proposition, not an English sentence.")
        hints.append("- Replace `for each integer a, P(a)` with `\u2200 a : nat, P a`.")
        hints.append("- Replace `there are N things with property P` with a direct equation or inequality.")
        hints.append("- If a fact cannot be stated as a symbolic Rocq-like proposition, collapse it into a coarser step or drop it.")
    return "\n".join(hints)


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

def _parse_rewrite_output(raw_output: str, *, informal_proof: str = "", formal_statement: str = "") -> str:
    rewrite = _extract_angelito_block(strip_fences(raw_output))
    _validate_angelito_rewrite(rewrite, informal_proof=informal_proof, formal_statement=formal_statement)
    return rewrite


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run(informal_path: Path, formal_statement: str, config: dict,
        debug_attempts: Optional[list[dict]] = None,
        log_metadata: Optional[dict] = None) -> str:
    """Run the rewrite stage. Returns the Angelito proof text."""
    from pipeline.prompts import get_rewrite

    text = informal_path.read_text(encoding="utf-8").strip()
    angelito_spec_path = REPO_ROOT / "angelito-spec.md"
    if not angelito_spec_path.exists():
        raise FileNotFoundError(f"Angelito spec not found: {angelito_spec_path}")
    angelito_spec = angelito_spec_path.read_text(encoding="utf-8").strip()
    prompt = get_rewrite(text, formal_statement, angelito_spec)
    return generate_with_format_retries(
        config["rewrite_model"], prompt, config,
        stage="rewrite",
        parser=lambda raw: _parse_rewrite_output(raw, informal_proof=text, formal_statement=formal_statement),
        retry_guidance_fn=_retry_guidance,
        debug_attempts=debug_attempts,
        log_metadata=log_metadata,
    )
