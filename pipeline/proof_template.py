"""Build and render Jinja2 proof templates with named tactic slots."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional

from jinja2 import Environment, StrictUndefined

_ADMIT_LINE_RE = re.compile(r"^\s*[-+*{}]*\s*admit\.\s*$")
_ADMIT_PREFIX_RE = re.compile(
    r"^(?P<indent>\s*)(?P<bullet>[-+*{}]*\s*)(?:\(\*\s*FILL THIS\s*\*\)\s*)?admit\.\s*$"
)
_MARKED_ADMIT_RE = re.compile(
    r"^\s*[-+*{}]*\s*\(\*\s*FILL THIS\s*\*\)\s*admit\.\s*$"
)
_PROVE_LABEL_RE = re.compile(r"^PROVE\s+([A-Za-z0-9_]+)\s*:")
_SPLIT_LABEL_RE = re.compile(r"^\(\d+\)\s+([A-Za-z0-9_]+)\s*:")

_JINJA = Environment(
    autoescape=False,
    keep_trailing_newline=True,
    trim_blocks=False,
    lstrip_blocks=False,
    undefined=StrictUndefined,
)


@dataclass(frozen=True)
class SlotSpec:
    name: str
    original_line: str


@dataclass
class ProofTemplate:
    template_text: str
    slots: list[SlotSpec]

    def render(
        self,
        slot_values: dict[str, Optional[str]],
        *,
        marked_slot: Optional[str] = None,
    ) -> str:
        if not self.slots:
            return self.template_text.strip()

        context: dict[str, str] = {}
        for slot in self.slots:
            replacement = slot_values.get(slot.name)
            if replacement is None:
                replacement = "admit."
            if marked_slot == slot.name:
                replacement = "(* FILL THIS *) admit."
            context[slot.name] = _format_slot_value(slot.original_line, replacement)
        rendered = _JINJA.from_string(self.template_text).render(**context)
        return rendered.strip()

    def has_unfilled_slots(self, slot_values: dict[str, Optional[str]]) -> bool:
        return any(slot_values.get(slot.name) is None for slot in self.slots)

    def next_unfilled_slot(self, slot_values: dict[str, Optional[str]]) -> Optional[SlotSpec]:
        for slot in self.slots:
            if slot_values.get(slot.name) is None:
                return slot
        return None


def build_proof_template(skeleton: str, angelito_proof: str) -> ProofTemplate:
    lines: list[str] = []
    slots: list[SlotSpec] = []
    slot_hints = _extract_slot_hints(angelito_proof)
    used_names: set[str] = set()
    hint_index = 0

    for line in skeleton.splitlines():
        if _ADMIT_LINE_RE.match(line):
            slot_name = _allocate_slot_name(
                slot_hints=slot_hints,
                hint_index=hint_index,
                slot_number=len(slots) + 1,
                used_names=used_names,
            )
            hint_index += 1
            slots.append(SlotSpec(name=slot_name, original_line=line))
            lines.append(f"{{{{ {slot_name} }}}}")
            continue
        lines.append(line)

    return ProofTemplate(template_text="\n".join(lines), slots=slots)


def find_marked_admit_line(rendered_proof: str) -> int:
    for idx, line in enumerate(rendered_proof.splitlines()):
        if _MARKED_ADMIT_RE.match(line):
            return idx
    return -1


def count_rendered_admits(rendered_proof: str) -> int:
    return sum(1 for line in rendered_proof.splitlines() if _ADMIT_LINE_RE.match(line))


def _format_slot_value(original_line: str, replacement: str) -> str:
    match = _ADMIT_PREFIX_RE.match(original_line)
    indent = match.group("indent") if match else re.match(r"^(\s*)", original_line).group(1)
    bullet_part = match.group("bullet") if match else ""
    continuation_indent = indent + ("  " if bullet_part.strip() else "")
    replacement_lines = [line.strip() for line in replacement.strip().splitlines() if line.strip()]
    if not replacement_lines:
        raise ValueError("Slot replacement must contain at least one non-empty tactic line.")

    rendered_lines: list[str] = []
    for idx, line in enumerate(replacement_lines):
        prefix = f"{indent}{bullet_part}" if idx == 0 else continuation_indent
        rendered_lines.append(f"{prefix}{line}".rstrip())
    return "\n".join(rendered_lines)


def _extract_slot_hints(angelito_proof: str) -> list[str]:
    hints: list[str] = []
    saw_top_level_prove = False
    for raw_line in angelito_proof.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        prove_match = _PROVE_LABEL_RE.match(line)
        if prove_match:
            label = prove_match.group(1)
            if not saw_top_level_prove:
                saw_top_level_prove = True
                continue
            hints.append(label)
            continue

        split_match = _SPLIT_LABEL_RE.match(line)
        if split_match:
            hints.append(split_match.group(1))

    return hints


def _allocate_slot_name(*, slot_hints: list[str], hint_index: int, slot_number: int, used_names: set[str]) -> str:
    if hint_index < len(slot_hints):
        base_name = _slugify_slot_name(slot_hints[hint_index])
    else:
        base_name = f"slot_{slot_number}"

    candidate = base_name
    suffix = 2
    while candidate in used_names:
        candidate = f"{base_name}_{suffix}"
        suffix += 1
    used_names.add(candidate)
    return candidate


def _slugify_slot_name(label: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", label.strip().lower()).strip("_")
    if not slug:
        slug = "slot"
    if slug[0].isdigit():
        slug = f"slot_{slug}"
    return slug
