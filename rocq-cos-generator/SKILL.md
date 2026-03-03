---
name: rocq-cos-generator
description: Generate and execute CoSProver-style Rocq/Coq proof steps from Chain of States data. Use when working in this repository on `.v` files to move between adjacent states, recover from tactic/state mismatches (ETR/ESR), capture proof state with `scripts/get-proof-state.ps1`, and validate with `scripts/check-target-proof.ps1` or `scripts/check-proofs.ps1`.
---

# Rocq Cos Generator

## Overview

Implement the manual CoS workflow in this repo: take state pairs, apply Coq tactics, verify in Coq, and iterate until `No Goals`.
Keep edits deterministic and project-aware by following `_CoqProject`, proof-state snapshots, and proof-check scripts.

## Required Inputs

Provide or infer these before editing:

- `target_file`: the `.v` file to edit (for example `coq/CongModEq.v`).
- `state_chain`: CoS states (`State 0`, `State 1`, ... `No Goals`) or at least one adjacent pair.
- `current_cursor_line` when state must be captured from source.
- `formal_statement` if theorem scaffolding is needed.

## Slash Invocation Defaults

When invoked as `/rocq-cos-generator` with a CoS chain:

- Assume edit-only mode by default.
- Do not ask for confirmation before first edit.
- Do not output planning/strategy text before first patch.
- If `target_file` is omitted, infer it automatically:
  - Prefer the currently active `.v` file when available.
  - Otherwise default to `coq/CongModEq.v` in this repository.

## Direct Mode Trigger

Enter direct mode immediately when the user provides:

- `target_file` (or clear destination file),
- a theorem statement (or equivalent state-0 goal),
- and at least one adjacent CoS state transition.

In direct mode, start writing proof code at once. Do not run broad repository discovery.

## Edit-Only Mode (Preferred)

When the user says "edit this file" (or equivalent), or when slash invocation defaults apply:

- Perform a direct patch to the target file first.
- Run zero shell commands before the first edit.
- Do not run `get-proof-state` or proof-check commands unless the user asks to verify/check/state-capture.
- If verification is requested, run only `scripts/check-target-proof.ps1` for that file unless full-project check is explicitly requested.

## Read Budget (Anti-Overread)

When in direct mode, allow only this minimal read set before first edit:

- `target_file`
- `_CoqProject`
- `scripts/get-proof-state.ps1` only if state capture fails or needs debugging

Do not scan docs, `.glob`, git history, or unrelated files unless blocked by a concrete compile/state error.
If blocked, read only the single file needed to unblock.

## Execution Contract (Edit-First)

- After direct mode triggers, perform the first proof-file edit within the first 3 actions.
- In edit-only mode, perform the first proof-file edit as action 1.
- Do not spend more than one brief preflight pass before editing.
- Do not answer with long strategy-only messages while the file remains unedited.
- If the user gave a valid state transition, write tactics first, then explain if asked.

## Tooling Guardrails (No REPL Thrash)

- Do not run ad-hoc `coqtop` `Search`/`Check` loops as a first step.
- Do not run non-Coq scratch commands (for example Python no-op snippets) during proof formalization.
- Use repository scripts and direct file edits as the default mechanism.
- Only use interactive probing when blocked by a specific unknown lemma, and run at most one focused probe.
- In edit-only mode, skip interactive probing entirely unless user explicitly requests it.

## File Rules (Do Not Violate)

Treat these as hard constraints:

- Use existing `.v` files by default. Do not create a new proof file unless explicitly requested.
- Never blank or delete existing `.v` sources.
- Never run `scripts/clean-coq-artifacts.ps1` with `-ResetVFiles` unless the user explicitly asks.
- Treat `_CoqProject` as the source of truth for what `scripts/check-proofs.ps1` compiles.
- If you create a new `.v` file intentionally, add it to `_CoqProject` in the same change.
- Keep edits focused on the target theorem; avoid unrelated rewrites.
- Default to one theorem in one target `.v` file per run.
- Do not edit docs, prompts, or scripts unless explicitly requested.

## Artifact Trust Rules

- Do not treat `.glob`, `.vo`, `.vos`, `.vok`, or caches as authoritative source code.
- Never infer "proof already exists" from compiled/generated artifacts.
- Source of truth is `.v` text plus user-provided chain and statement.

## Language Safety (Coq vs Lean)

Write Rocq/Coq syntax only:

- Allowed examples: `intros`, `destruct`, `induction`, `assert`, `pose proof`, `rewrite`, `apply`, `eapply`, `exact`, `lia`, `ring`, `omega`.
- Disallowed Lean-style tokens in proof scripts: `have`, `rw`, `simp`, `simpa`, `by`, `by_cases`.
- If generated tactics include Lean syntax, stop and rewrite them into Coq before saving.

## Workflow

1. Preflight
- Confirm `target_file` exists.
- Check whether `target_file` is listed in `_CoqProject`.
- If user expects full-project validation, ensure intended files are in `_CoqProject`.
- If `target_file` is empty and user provided statement/chain, write theorem scaffold immediately instead of searching for prior versions.

2. Run the Golden Loop
- Execute this loop repeatedly until the theorem reaches `No Goals`:

```powershell
.\scripts\get-proof-state.ps1 -FilePath <target_file> -CursorLine <line>
# apply tactics / edit proof
.\scripts\check-target-proof.ps1 -FilePath <target_file>
```

- Run `.\scripts\check-proofs.ps1` only when user asks for full-project verification or when finishing.

3. Establish the active proof state
- Use:
  - `.\scripts\get-proof-state.ps1 -FilePath <target_file> -CursorLine <line>`
- If cursor is outside an unfinished proof, the script will return `No Goals`.

4. Apply adjacent-state tactics
- For each `(State p -> State p+1)`, add the smallest Coq tactic block that makes that transition.
- Keep proof scripts readable; prefer one intentional tactic step at a time.
- Prioritize user-provided state chain over inferred context from other files.

5. Validate and iterate
- Run:
  - `.\scripts\check-proofs.ps1`
- If Coq raises a tactic/syntax error, run ETR loop (Prompt #4 style).
- If tactics run but land in wrong state, run ESR loop (Prompt #5 style).
- Re-capture state and continue until final state is `No Goals`.

6. Finalize
- Leave only valid Coq code in theorem files.
- Keep helper notes in chat output, not in `.v` source, unless asked.

## ETR and ESR Decision Rule

- Use ETR when Coq reports an error for a tactic sequence.
- Use ESR when tactics succeed but produce the wrong intermediate goal.
- Always include the exact state text when regenerating tactics.

## Failure Policy

- If `get-proof-state.ps1` fails, stop tactic generation and report the command error first.
- If `get-proof-state.ps1` returns `No Goals` but proof is expected to be in progress, treat cursor line as wrong and re-sample at the theorem body.
- If `check-proofs.ps1` fails in unrelated files, do not rewrite those files by default; isolate validation to the target file unless the user asks for whole-project fixes.

## Resources

- `scripts/get-proof-state.ps1`: capture current proof state block for agent context.
- `scripts/check-target-proof.ps1`: compile only the current target file with `_CoqProject` flags.
- `scripts/check-proofs.ps1`: compile all files listed in `_CoqProject`.
- `docs/PROMPTS.md`: canonical prompt formats for rewrite, CoS generation, tactic generation, ETR, and ESR.
