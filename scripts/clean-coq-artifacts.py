#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path


DEFAULT_PATTERNS = ("*.vo", "*.vos", "*.vok", "*.vio", "*.glob", "*.aux")


def _iter_matches(root: Path, pattern: str, recurse: bool):
    if recurse:
        yield from root.rglob(pattern)
    else:
        yield from root.glob(pattern)


def main() -> int:
    parser = argparse.ArgumentParser(description="Delete generated Coq artifact files.")
    parser.add_argument(
        "--path",
        default=str(Path(__file__).resolve().parent.parent),
        help="Root directory to clean (defaults to repository root).",
    )
    parser.add_argument(
        "--patterns",
        nargs="+",
        default=list(DEFAULT_PATTERNS),
        help="File glob patterns to remove.",
    )
    parser.add_argument("--no-recurse", action="store_true", help="Only search the root directory.")
    parser.add_argument(
        "--reset-v-files",
        action="store_true",
        help="Also empty matching .v source files.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview files without deleting.")
    args = parser.parse_args()

    root = Path(args.path).expanduser().resolve()
    if not root.exists():
        raise RuntimeError(f"Path does not exist: {root}")

    recurse = not args.no_recurse
    artifacts: set[Path] = set()
    for pattern in args.patterns:
        for candidate in _iter_matches(root, pattern, recurse):
            if candidate.is_file():
                artifacts.add(candidate.resolve())

    if not artifacts and not args.reset_v_files:
        print("No matching Coq artifacts found.")
        return 0

    deleted = 0
    for artifact in sorted(artifacts):
        if args.dry_run:
            print(f"[dry-run] delete {artifact}")
            continue
        artifact.unlink(missing_ok=True)
        deleted += 1

    reset = 0
    if args.reset_v_files:
        v_sources = (
            root.rglob("*.v")
            if recurse
            else root.glob("*.v")
        )
        for source in v_sources:
            if not source.is_file():
                continue
            if args.dry_run:
                print(f"[dry-run] empty {source}")
                continue
            source.write_text("", encoding="utf-8")
            reset += 1
        print(f"Emptied {reset} source file(s) in: {root}")
        if deleted == 0:
            print("No matching generated artifacts were found.")
    else:
        print(f"Cleaned up {deleted} generated file(s) in: {root}")

    print("Used recursive search." if recurse else "Used non-recursive search.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
