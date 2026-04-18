# Agent Behavior: Error Recovery and Context Passing

This document describes how the pipeline agent behaves at each stage, how it recovers from errors, and how context flows between stages. The goal is a clean three-stage handoff — rewrite, skeleton, fill — where the agent understands its task at each point and gets actionable feedback when things go wrong.

## Design Principles

1. **No heuristic fallbacks.** The agent should understand its task and fix its own mistakes. We don't paper over model errors with hardcoded workarounds.
2. **One slot at a time.** During fill (Step 3), the agent works on exactly one `admit.` slot. The rest of the skeleton stays admitted. If the filled slot compiles with everything else admitted, it's correct.
3. **Imports must be right.** The pipeline auto-adds standard library imports based on what the formal statement uses, and verifies every import compiles before any model calls happen.
4. **Context over heuristics.** When something fails, the agent gets the actual compiler error, structured feedback, and stage-specific repair guidance — not a generic "try again" message.
5. **Fail fast on environment issues.** Missing libraries, broken Coq installations, and unresolvable imports are caught before we spend API calls.

## Pre-flight: Import Verification

Before any model calls, the pipeline runs a pre-flight check on every import in the formal statement.

### Why this matters

Previously, if a formal statement referenced a library that wasn't installed (e.g., a third-party library like `Coquelicot`, or a typo like `Require Import Realls.`), the pipeline would:

1. Spend an API call on Step 1 (rewrite) — succeeds, no compilation involved
2. Spend an API call on Step 2 (skeleton) — model generates valid tactics
3. Try to compile the skeleton — **fails on the import line**, not on any tactic
4. Feed the import error back to the model as if it were a tactic problem
5. Model retries 3 times, producing the same skeleton, failing on the same import
6. Pipeline gives up after wasting all retry budget on an unsolvable problem

The model can't fix a missing library by changing tactics. This is an environment problem, not a model problem.

### What the pre-flight does

```
formal statement (with auto-added imports)
  │
  ├─ _extract_imports()     → pulls out every Require Import / From ... Require Import line
  │
  └─ _verify_imports()      → for each import line:
      ├─ writes a one-line .v file in the repo root
      ├─ compiles it with coqc (same flags as the real compilation)
      ├─ checks exit code
      └─ cleans up temp files (.v, .vo, .vok, .vos, .glob)
```

If any import fails, the pipeline stops immediately:

```
Import verification failed. The following imports are not available:
  Require Import Coquelicot.Coquelicot.
    -> Cannot find a physical path bound to logical path Coquelicot.Coquelicot.

Install the missing libraries before running the pipeline.
```

The verification uses the same `coqc` binary and `_CoqProject` flags as the real compilation, so it tests the exact same environment. Results are saved in the trace as `import_check`.

### Auto-added imports

The pipeline inspects the formal statement's existing imports and auto-adds standard libraries before verification:

| If the formal statement imports... | Pipeline auto-adds |
|---|---|
| `Reals` or `Coquelicot` | `Lra`, `Psatz`, `Field` |
| `Arith` or `ZArith` | `Lia` |

Duplicates are not added. The auto-added imports are standard Coq libraries that ship with every installation — they will always resolve. This ensures the agent can use `lra.`, `lia.`, `field.`, etc. without the model needing to know about import management.

The pre-flight verifies the auto-added imports too, so if something is wrong with the Coq installation, we catch it here.

## Stage-by-Stage Behavior

### Step 1: Rewrite (Informal → Angelito)

**Input:** Informal proof text, formal theorem statement, Angelito spec.

**Output:** Strict Angelito proof (`PROVE ... BEGIN ... END`).

**No compilation.** The Angelito pseudo-proof language is not Coq — it's a structured text format consumed by the Python parser and the Step 2 model. `coq/Angelito.v` defines Coq *tactics* that share the Angelito name, but the language itself is never compiled.

**Validation:** The Python parser checks for correct Angelito structure:
- `PROVE` header, `BEGIN`/`END` delimiters, at least one `CONCLUDE`
- Every line is either an Angelito keyword or a valid continuation of one
- No pseudo-math notation (`∑`, `sum_{...}`, set-builder `{x | P x}`)
- No natural-language prose in `FACT`/`THEREFORE` bodies
- No invented `INDUCTION` when the informal proof doesn't mention it
- No overexpanded proofs for answer-only inputs

**On failure:** The agent gets the specific validation error plus stage-specific repair hints. Temperature increases on retries (0.0 → 0.4) to avoid repeating the same output.

### Step 2: Skeleton (Angelito → Rocq with admits)

**Input:** Formal statement (with auto-added imports), Angelito proof, tactics reference, translation guide.

**Output:** Rocq tactic lines with `admit.` at every leaf goal.

**Validation (format):** The Python parser (`tactic_parser.py`) extracts tactic lines from the model output:
- Finds ````coq` block or uses raw text
- Splits inline tactics (e.g., `assert (h : P). { admit. }` → 3 lines)
- Validates each line against a regex of ~40 known tactic names
- **All-or-nothing:** if any line fails validation, the entire output is rejected

Then `_parse_skeleton_output` runs structural checks:
- Every line must be "structural" — `intros`, `assert`, `destruct`, `induction`, `apply`, `split`, `admit.`, `{ }` are allowed; `simpl`, `rewrite`, `exact`, `lia`, etc. are blocked (those belong in Step 3)
- `admit.` must be standalone (not embedded like `... by admit.`)
- Must start with `intros` if the formal statement has `forall`/`->`
- No unauthorized `induction` (must match the Angelito proof)
- No Angelito Ltac1 tactics without imports

**Validation (compile):** The skeleton is wrapped into a full `.v` file with the formal statement, imports, `Proof.`, indented body, and `Admitted.`, then compiled with `coqc`. The `Admitted.` terminator tells Coq to accept all remaining goals on faith — so `admit.` placeholders are fine. What gets checked is that the structure is valid: types match, tactics parse, `assert` propositions are well-typed, `intros` names don't collide.

**On format failure:** The agent gets the validation error plus repair hints. For the "standalone admit" error, the hint explicitly says a trivial goal can just be `admit.` alone.

**On compile failure:** The agent gets:
- The failed skeleton tactics
- The exact Coq compiler error
- Structured compiler feedback (when available)
- **Error-specific guidance:**
  - `"x is already used"` → Lists the pre-bound names from the theorem signature and tells the agent not to re-introduce them
  - Type mismatch → Explains the mismatch with examples (`Int_part` returns `Z` not `nat`)
  - `"unable to unify"` → Suggests simplifying the skeleton
- Temperature increases on compile retries (0.0 → 0.4)

### Step 3: Fill (one admit at a time)

**Input:** Formal statement, Angelito proof, current proof with `(* FILL THIS *)` marker, goal state at the marked admit.

**Output:** Replacement tactics that fully discharge the marked subgoal.

**Key behavior:** The agent fills exactly one slot. All other slots remain `admit.`. The full proof (with the one slot filled and everything else admitted) is compiled with `coqc`. If it compiles, the slot is done and the agent moves to the next one.

**Goal state capture:** Before asking the model to fill a slot, the pipeline runs `coqtop` with the proof up to the marked admit line, appends `Show.` and `Abort.`, and parses the output to get the current hypotheses and goal. This is the authoritative context the model works from.

**Validation (format):** Same tactic parser as Step 2, plus:
- No Angelito Ltac1 tactics unless the proof imports them
- No `lra`/`field` unless the proof imports the required libraries (auto-added imports count)
- No intros-only fills (must actually solve the goal)
- Must be valid Rocq tactic syntax

**On format failure:** The agent gets the specific rejection reason plus repair hints. When Angelito tactics are rejected, the hint explicitly lists standard Rocq alternatives.

**On compile failure:** The agent gets:
- The failed replacement tactics
- The Coq compiler error
- Structured compiler feedback (when available)
- The residual goal state after running the failed tactics (when capturable)
- Temperature increases on retries

## Temperature Escalation

To prevent the model from producing identical output across retries:

| Attempt | Temperature |
|---|---|
| 1st (any stage) | 0.0 (deterministic) |
| 2nd+ format retry | 0.4 |
| 2nd+ skeleton compile retry | 0.4 |
| 2nd+ fill compile retry | 0.4 |

## Pre-Bound Name Awareness

When the formal statement binds names as theorem parameters (e.g., `Theorem foo (x a : T) (H0 : P) : Q`), the pipeline extracts those names and includes them in error context when relevant. This prevents the common failure mode where the model emits `intros x a H0 ...` for names that are already in scope.

## Compilation Model

The pipeline compiles the **entire proof file** after each fill, not just the filled slot. This is correct because:

- Unfilled slots are `admit.`, which always compiles under `Admitted.`
- If the filled slot introduces a type error or breaks the proof structure, the full-file compile catches it
- This matches how Coq actually works — you can't compile a tactic block in isolation

The compilation chain is:
1. `coqc -R coq RocqCoSPOC coq/Angelito.v` — compile the custom tactics library (dependency)
2. `coqc -R coq RocqCoSPOC <target.v>` — compile the actual proof file

The `-R coq RocqCoSPOC` flag comes from `_CoqProject` and maps the `coq/` directory to the logical path `RocqCoSPOC`. Timeout is 60 seconds per compilation.

The final compilation after all slots are filled uses `Qed.` instead of `Admitted.` — this is strict and verifies every obligation is actually discharged.
