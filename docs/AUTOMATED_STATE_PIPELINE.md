# Automatic Proof-State Bridge

This project's current workflow is rewrite -> Angelito -> Rocq skeleton -> iterative admit filling.
The script below gives the pipeline or coding agent direct access to the current proof state at the
specific hole it is trying to fill.

## What It Does

- Reads your `.v` file and a cursor line.
- Finds the nearest theorem/lemma that contains that line.
- Replays the code up to that point in a `coqtop` session.
- Runs `Show.` to capture the current goal and hypotheses.
- Emits a state block in the same style used by the fill prompt:

```text
State 0:
hypothesis : type
============================
goal
```

## Quick Usage

From the repo root:

```powershell
.\scripts\get-proof-state.ps1 -FilePath .\coq\CongModEq.v -CursorLine 18
```

`-CursorLine` is the current editor line number (for example, where the cursor currently sits).

## Optional: Run Via VS Code/Cursor Task

This repo includes `.vscode/tasks.json` with a task that calls the script using `${file}` and
`${lineNumber}`.  You can bind that task to a shortcut in Cursor and get a fresh state block
in one step.

## Required Tools

- `coqtop` available on PATH or discoverable from project config.
- Rocq/Coq installation with `.vscode/settings.json` or `scripts/check-proofs.ps1` pointing to valid binaries.

## Known Limitations

- If your cursor is outside an unfinished proof, the script returns `No Goals`.
- The snapshot script is robust enough for current usage, but it is not a full VS/IDE API integration yet.
  It is a fast bridge so the pipeline receives current state text without manual hand-copying from the IDE.
