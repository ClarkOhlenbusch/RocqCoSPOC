# Project Goal: Agentic Rocq Compiler

## Vision
Build a fully automatic pipeline that takes informal mathematical proofs and compiles them into verified Rocq proof scripts, using Angelito as an intermediate representation.

## Core Problem
Rocq is too low-level for an LLM to reliably generate correct proofs in one shot. Raw `coqc` errors are cryptic and unhelpful for an AI agent to self-correct.

## Architecture: Iterative Top-Down Compilation

### Step 1: Informal → Angelito Rewrite
- Input: informal natural language proof
- Output: structured proof using strict Angelito syntax (`PROVE`, `ASSUME`, `SIMPLIFY`, `THEREFORE`, etc.)
- Reference: `angelito-to-rocq-translation-guide.md`

### Step 2: Skeleton Generation
- Translate only the outermost Angelito structure into Rocq
- Induction? Generate the case split. Case analysis? Generate the branches.
- All inner goals are left as `sorry` placeholders
- This must compile successfully before moving deeper

### Step 3: Iterative Goal Filling
- For each `sorry`, make a targeted LLM call to fill that sub-goal
- Use Angelito custom tactics (`assume`, `simplify lhs/rhs`, `assert_goal`, `pick`) — not raw low-level Rocq
- Compile after each fill. Custom tactics return structured errors (expected vs. actual goal state)
- Retry with that structured feedback if compilation fails
- Retain the informal proof text until a block is fully discharged

## Key Principles
- **Top-down, not one-shot**: Paint broad strokes first (lemma/proof/induction/end), then iteratively fill detail
- **Custom tactics are not syntactic sugar**: They provide introspection — telling the agent what went wrong in terms it can understand
- **Angelito is the bridge**: It sits between informal reasoning and Rocq, giving the LLM a declarative vocabulary that maps mechanically to tactics
- **Compilation feedback drives iteration**: Every generated level is compiled. The compiler output informs the next pass.

## Dependencies
- Angelito-to-Rocq translation guide (keyword → tactic mappings)
- Tiago's custom Ltac2 tactics (`From Angelito Require Import Tactics.`)
  - `assert_goal` — assert expected proof state, get diff if wrong
  - `simplify lhs / rhs` — declarative rewriting
  - `pick` — structured term selection
- Dashboard UI for running pipeline and visualizing traces

## Anti-Patterns to Avoid
- ❌ One-shot full proof generation
- ❌ Chain of states as a prompt engineering pattern (removed)
- ❌ Feeding raw `coqc` errors back without structure
- ❌ Using Angelito keywords as if they are Rocq tactics
- ❌ Letting the LLM skip the skeleton step and jump to low-level tactics