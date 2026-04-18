#!/usr/bin/env python3

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


def _safe_read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            row["_matched"] = False
            rows.append(row)
    return rows


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _html_pre(text: str, class_name: str = "code") -> str:
    safe = html.escape(text.strip() or "(empty)")
    return f'<pre class="{class_name}">{safe}</pre>'


def _html_meta(items: list[tuple[str, str]]) -> str:
    cells = []
    for key, value in items:
        if not value:
            continue
        cells.append(
            '<div class="meta-item">'
            f'<span class="meta-key">{html.escape(key)}</span>'
            f'<span class="meta-value">{html.escape(value)}</span>'
            "</div>"
        )
    return '<div class="meta-grid">' + "".join(cells) + "</div>"


def _match_model_log_entry(
    log_entries: list[dict[str, Any]],
    *,
    stage: str,
    model_attempt: dict[str, Any],
    extra_context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    extra_context = extra_context or {}
    format_attempt = model_attempt.get("format_attempt")
    model_name = _normalize_text(model_attempt.get("model"))

    def matches(entry: dict[str, Any], *, strict: bool) -> bool:
        if entry.get("_matched"):
            return False
        metadata = entry.get("metadata") or {}
        if metadata.get("stage") != stage:
            return False
        if format_attempt is not None and metadata.get("format_attempt") != format_attempt:
            return False
        if model_name and _normalize_text(entry.get("model")) != model_name:
            return False
        if strict:
            for key, value in extra_context.items():
                if value is None:
                    continue
                if metadata.get(key) != value:
                    return False
        return True

    for strict in (True, False):
        for entry in log_entries:
            if matches(entry, strict=strict):
                entry["_matched"] = True
                return entry
    return None


def _attempt_card(
    *,
    title: str,
    subtitle: str,
    prompt_text: str,
    raw_output: str,
    parsed_output: str,
    extra_panels: list[tuple[str, str]],
    metadata_items: list[tuple[str, str]],
) -> str:
    panel_html = [
        '<div class="panel"><h4>Prompt</h4>'
        + _html_pre(prompt_text or "(prompt unavailable for this older run)")
        + "</div>",
        '<div class="panel"><h4>Raw Model Output</h4>' + _html_pre(raw_output) + "</div>",
    ]
    if parsed_output and parsed_output != raw_output:
        panel_html.append('<div class="panel"><h4>Parsed Output</h4>' + _html_pre(parsed_output) + "</div>")
    for heading, text in extra_panels:
        panel_html.append(f'<div class="panel"><h4>{html.escape(heading)}</h4>{_html_pre(text)}</div>')

    return (
        '<section class="attempt-card">'
        f"<h3>{html.escape(title)}</h3>"
        f'<div class="subtitle">{html.escape(subtitle)}</div>'
        f"{_html_meta(metadata_items)}"
        '<div class="panel-grid">'
        + "".join(panel_html)
        + "</div></section>"
    )


def _render_viewer_html(trace_path: Path, trace: dict[str, Any], log_entries: list[dict[str, Any]]) -> str:
    rewrite = (trace.get("rewrite") or {}).get("model_attempts", [])
    skeleton_compile_attempts = (trace.get("skeleton") or {}).get("compile_attempts", [])
    fills = trace.get("fills") or []

    sections: list[str] = []

    for idx, attempt in enumerate(rewrite, start=1):
        log_entry = _match_model_log_entry(
            log_entries,
            stage="rewrite",
            model_attempt=attempt,
            extra_context={"pipeline_call": "rewrite"},
        )
        sections.append(
            _attempt_card(
                title=f"Step 1 Rewrite Attempt {idx}",
                subtitle="Informal proof -> Angelito",
                prompt_text=_normalize_text((log_entry or {}).get("prompt_text") or (log_entry or {}).get("prompt_preview")),
                raw_output=_normalize_text(attempt.get("raw_output")),
                parsed_output=_normalize_text(attempt.get("parsed_output")),
                extra_panels=[
                    ("Parser Error", _normalize_text(attempt.get("error")))
                ] if attempt.get("error") else [],
                metadata_items=[
                    ("Model", _normalize_text(attempt.get("model"))),
                    ("Status", _normalize_text(attempt.get("status"))),
                    ("Format Attempt", _normalize_text(attempt.get("format_attempt"))),
                ],
            )
        )

    for compile_attempt in skeleton_compile_attempts:
        compile_no = compile_attempt.get("attempt")
        model_attempts = compile_attempt.get("model_attempts") or []
        if not model_attempts:
            sections.append(
                _attempt_card(
                    title=f"Step 2 Skeleton Compile Attempt {compile_no}",
                    subtitle="No model attempt captured",
                    prompt_text="(no model attempt)",
                    raw_output=_normalize_text(compile_attempt.get("text")),
                    parsed_output=_normalize_text(compile_attempt.get("rendered_text")),
                    extra_panels=[
                        ("Compiler stderr", _normalize_text(compile_attempt.get("stderr"))),
                        ("Proof State", _normalize_text(compile_attempt.get("proof_state"))),
                    ],
                    metadata_items=[
                        ("Status", _normalize_text(compile_attempt.get("status"))),
                        ("Compiles", _normalize_text(compile_attempt.get("compiles"))),
                    ],
                )
            )
            continue

        for model_idx, model_attempt in enumerate(model_attempts, start=1):
            log_entry = None
            if _normalize_text(model_attempt.get("model")) != "deterministic":
                log_entry = _match_model_log_entry(
                    log_entries,
                    stage="skeleton",
                    model_attempt=model_attempt,
                    extra_context={"skeleton_compile_attempt": compile_no},
                )
            sections.append(
                _attempt_card(
                    title=f"Step 2 Skeleton Attempt {compile_no}.{model_idx}",
                    subtitle="Angelito -> Rocq scaffold",
                    prompt_text=_normalize_text(
                        (log_entry or {}).get("prompt_text")
                        or (log_entry or {}).get("prompt_preview")
                        or "(deterministic scaffold)"
                    ),
                    raw_output=_normalize_text(model_attempt.get("raw_output") or compile_attempt.get("text")),
                    parsed_output=_normalize_text(model_attempt.get("parsed_output") or compile_attempt.get("rendered_text")),
                    extra_panels=[
                        ("Rendered Skeleton", _normalize_text(compile_attempt.get("rendered_text"))),
                        ("Compiler stderr", _normalize_text(compile_attempt.get("stderr"))),
                        ("Proof State", _normalize_text(compile_attempt.get("proof_state"))),
                    ],
                    metadata_items=[
                        ("Model", _normalize_text(model_attempt.get("model"))),
                        ("Status", _normalize_text(model_attempt.get("status") or compile_attempt.get("status"))),
                        ("Compile Attempt", _normalize_text(compile_no)),
                        ("Compiles", _normalize_text(compile_attempt.get("compiles"))),
                    ],
                )
            )

    for fill in fills:
        fill_attempt = fill.get("attempt")
        slot_name = _normalize_text(fill.get("slot_name"))
        model_attempts = fill.get("model_attempts") or []
        for model_idx, model_attempt in enumerate(model_attempts, start=1):
            log_entry = None
            if _normalize_text(model_attempt.get("model")) != "deterministic":
                log_entry = _match_model_log_entry(
                    log_entries,
                    stage="fill_goal",
                    model_attempt=model_attempt,
                    extra_context={
                        "slot_name": slot_name,
                        "fill_attempt": fill_attempt,
                        "admit_index": fill.get("admit_index"),
                    },
                )
            sections.append(
                _attempt_card(
                    title=f"Step 3 Fill Attempt {fill_attempt}.{model_idx}",
                    subtitle=f"Slot {slot_name or '?'}",
                    prompt_text=_normalize_text(
                        (log_entry or {}).get("prompt_text")
                        or (log_entry or {}).get("prompt_preview")
                        or "(deterministic fill)"
                    ),
                    raw_output=_normalize_text(model_attempt.get("raw_output") or fill.get("replacement")),
                    parsed_output=_normalize_text(model_attempt.get("parsed_output") or fill.get("replacement")),
                    extra_panels=[
                        ("Goal State", _normalize_text(fill.get("current_goal_state"))),
                        ("Replacement Inserted", _normalize_text(fill.get("replacement"))),
                        ("Compiler stderr", _normalize_text(fill.get("stderr"))),
                    ],
                    metadata_items=[
                        ("Model", _normalize_text(model_attempt.get("model"))),
                        ("Status", _normalize_text(fill.get("status"))),
                        ("Fill Attempt", _normalize_text(fill_attempt)),
                        ("Exit Code", _normalize_text(fill.get("exit_code"))),
                        ("Slot", slot_name),
                    ],
                )
            )

    title = trace_path.stem
    status = _normalize_text(trace.get("status"))
    error = _normalize_text(trace.get("error"))
    started_at = _normalize_text(trace.get("started_at"))
    ended_at = _normalize_text(trace.get("ended_at"))

    header = (
        "<header>"
        f"<h1>Pipeline Attempt Viewer: {html.escape(title)}</h1>"
        '<p class="lede">Side-by-side prompt/output trace for rewrite, skeleton, and fill attempts.</p>'
        f"{_html_meta([('Trace Status', status), ('Started', started_at), ('Ended', ended_at), ('Error', error), ('Trace', str(trace_path))])}"
        "</header>"
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{html.escape(title)} - Pipeline Attempt Viewer</title>
  <style>
    :root {{
      --bg: #f7f2e8;
      --card: #fffdf8;
      --ink: #1e1a17;
      --muted: #6a5f56;
      --line: #d9cdbd;
      --accent: #9d3d2f;
      --shadow: rgba(58, 35, 14, 0.08);
      --code: #231f1c;
      --code-bg: #f3ede2;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Georgia, "Iowan Old Style", "Palatino Linotype", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, #fff7eb 0, transparent 25%),
        linear-gradient(180deg, #f8f3ea 0%, var(--bg) 100%);
    }}
    header {{
      padding: 32px 40px 20px;
      border-bottom: 1px solid var(--line);
      background: linear-gradient(180deg, rgba(255,255,255,0.7), rgba(255,255,255,0.35));
      position: sticky;
      top: 0;
      backdrop-filter: blur(10px);
      z-index: 10;
    }}
    h1, h2, h3, h4 {{ margin: 0; font-weight: 700; }}
    h1 {{ font-size: 30px; }}
    .lede {{ color: var(--muted); margin: 10px 0 0; }}
    main {{ padding: 24px 24px 48px; max-width: 1800px; margin: 0 auto; }}
    .attempt-card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: 0 14px 30px var(--shadow);
      padding: 20px;
      margin-bottom: 18px;
    }}
    .subtitle {{
      color: var(--muted);
      margin-top: 6px;
      margin-bottom: 12px;
    }}
    .meta-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px;
      margin: 16px 0 18px;
    }}
    .meta-item {{
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px 12px;
      background: rgba(255,255,255,0.65);
    }}
    .meta-key {{
      display: block;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      margin-bottom: 6px;
    }}
    .meta-value {{
      font-size: 15px;
      word-break: break-word;
    }}
    .panel-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
      align-items: start;
    }}
    .panel {{
      border: 1px solid var(--line);
      border-radius: 14px;
      overflow: hidden;
      background: #fff;
    }}
    .panel h4 {{
      padding: 10px 14px;
      font-size: 14px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: var(--accent);
      border-bottom: 1px solid var(--line);
      background: #fbf5ea;
    }}
    pre.code {{
      margin: 0;
      padding: 14px;
      font-family: Consolas, "SFMono-Regular", Menlo, monospace;
      font-size: 13px;
      line-height: 1.45;
      white-space: pre-wrap;
      word-break: break-word;
      color: var(--code);
      background: var(--code-bg);
      max-height: 460px;
      overflow: auto;
    }}
    @media (max-width: 980px) {{
      header {{ padding: 24px 20px 18px; }}
      main {{ padding: 18px; }}
      .panel-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  {header}
  <main>
    {''.join(sections) if sections else '<p>No attempts found in this trace.</p>'}
  </main>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a side-by-side HTML viewer for one pipeline trace.")
    parser.add_argument("--trace", type=Path, required=True, help="Path to trace.json")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="HTML output path. Defaults to <trace-stem>-viewer.html beside the trace.",
    )
    args = parser.parse_args()

    trace_path = args.trace.resolve()
    trace = _safe_read_json(trace_path)
    model_log_path = Path(_normalize_text(trace.get("model_log_path")) or trace_path.with_name(f"{trace_path.stem}-model-log.jsonl"))
    log_entries = _safe_read_jsonl(model_log_path)

    output_path = args.output.resolve() if args.output else trace_path.with_name(f"{trace_path.stem}-viewer.html")
    output_path.write_text(_render_viewer_html(trace_path, trace, log_entries), encoding="utf-8")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
