"""Trace persistence helpers."""

import json
from datetime import datetime
from pathlib import Path

from pipeline.config import REPO_ROOT


def default_trace_path() -> Path:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    return REPO_ROOT / "pipeline" / "traces" / f"run-{ts}.json"


def default_model_log_path(trace_path: Path) -> Path:
    return trace_path.with_name(f"{trace_path.stem}-model-log.jsonl")


def write_trace(trace_path: Path, trace: dict) -> None:
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text(json.dumps(trace, indent=2, ensure_ascii=False), encoding="utf-8")
