# Automatic proof-state bridge for agent default context

This project can be used with the current direct proving workflow and still keep the coding agent in the loop.  
The script below gives the agent default access to the current proof state by querying Coq
directly from the file position you are editing.

## What it does

- Reads your `.v` file and a cursor line.
- Finds the nearest theorem/lemma that contains that line.
- Replays the code up to that point in a `coqtop` session.
- Runs `Show.` to capture the current goal and hypotheses.
- Emits a state block in the same style used by the tactic prompt:

```text
State 0:
hypothesis : type
============================
goal
```

## Quick usage

From the repo root:

```powershell
.\scripts\get-proof-state.ps1 -FilePath .\coq\CongModEq.v -CursorLine 18
```

`-CursorLine` is the current editor line number (for example, where the cursor currently sits).

## Optional: run via VS Code/Cursor task

This repo includes `.vscode/tasks.json` with a task that calls the script using `${file}` and
`${lineNumber}`.  You can bind that task to a shortcut in Cursor and get a fresh state block
in one step.

## Required tools

- `coqtop` available on PATH or discoverable from project config.
- Rocq/Coq installation with `.vscode/settings.json` or `scripts/check-proofs.ps1` pointing to valid binaries.

## Known limitations

- If your cursor is outside an unfinished proof, the script returns `No Goals`.
- The snapshot script is robust enough for current usage, but it is not a full VS/IDE API integration yet.
  It is a fast bridge so the agent receives current state text without manual hand-copying from the IDE.
