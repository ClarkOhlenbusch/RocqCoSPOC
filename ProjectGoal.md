# Project Goal: Agentic Rocq Compiler

## Vision

Build a fully automatic pipeline that takes informal mathematical proofs and compiles them into verified Rocq proof scripts, using Angelito as an intermediate representation.

## Core Problem

Rocq is too low-level for an LLM to reliably generate correct proofs in one shot. Raw `coqc` errors are often too noisy to support reliable self-correction.

## Architecture: Iterative Top-Down Compilation

### Step 1: Informal -> Angelito Rewrite

- Input: informal natural-language proof
- Output: structured proof using strict Angelito syntax (`PROVE`, `ASSUME`, `SIMPLIFY`, `THEREFORE`, etc.)
- Constraint: Angelito keywords are proof-language markers, not Rocq tactics

### Step 2: Skeleton Generation

- Translate only the outermost Angelito structure into Rocq
- Induction generates case splits, theorem application generates subgoal structure, and trivial direct proofs get a minimal deterministic scaffold
- Inner goals are left as `admit.` placeholders or named slots until they are filled
- This scaffold must compile before moving deeper

### Step 3: Iterative Goal Filling

- For each remaining slot, make a targeted model call to fill that sub-goal only
- Use Angelito-aware Ltac1 tactics when helpful: `assert_goal`, `simplify lhs`, `simplify rhs`, and `pick`
- Keep low-level Rocq tactics available for the actual proof work
- Compile after each fill
- Parse structured feedback from the Angelito tactics when compilation fails, then retry with that feedback

## Key Principles

- **Top-down, not one-shot**: generate structure first, then fill local goals
- **Compiler feedback drives iteration**: every generated level is compiled before moving on
- **Angelito is the bridge**: it gives the model a declarative vocabulary that maps mechanically to Rocq
- **Custom tactics provide observability**: they report expected-vs-actual mismatches in a form the pipeline can reuse

## Dependencies

- `angelito-spec.md` for the rewrite-stage proof language
- `angelito-to-rocq.md` for Angelito -> Rocq mappings
- `coq/Angelito.v` for the Ltac1 and Ltac2 tactics library
- Generated proofs under `coq/` should import:

```coq
From RocqCoSPOC Require Import Angelito.
Import Angelito.Ltac1.
```

`_CoqProject` maps the `coq/` folder to the logical path `RocqCoSPOC`, so `coq/Angelito.v` is the library `RocqCoSPOC.Angelito`. Compile and check with the same `-R coq RocqCoSPOC` as in `_CoqProject`.

- Dashboard UI for running the pipeline and inspecting traces

## Anti-Patterns to Avoid

- One-shot full proof generation
- Reviving the removed direct-goal / transition pipeline
- Feeding raw `coqc` errors back without using structured Angelito feedback when available
- Using Angelito keywords as if they were Rocq tactics
- Letting the model invent proof structure that is not present in the Angelito rewrite
