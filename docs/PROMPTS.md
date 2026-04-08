# Proof Pipeline Prompts

The repository uses a single three-stage prompt stack under [`prompts/`](../prompts):

| File | Stage | Main inputs |
|------|-------|-------------|
| `01_rewrite.txt` | Informal proof -> strict Angelito | informal proof, formal statement, Angelito spec |
| `02a_skeleton.txt` | Angelito -> Rocq skeleton / slot scaffold | formal statement, Angelito proof, tactics reference, translation guide |
| `02b_fill_goal.txt` | Fill one marked slot | formal statement, Angelito proof, current proof, current goal state, tactics reference, translation guide, compiler feedback |

## Current Rules

- The rewrite stage must emit strict Angelito only. Angelito keywords are not Rocq tactics.
- The skeleton stage emits only the outer proof structure and leaves every leaf goal as a named slot rendered as `admit.` until it is filled.
- For Angelito proofs with no outer branching structure, the pipeline derives a deterministic direct skeleton instead of trusting the model to invent one.
- The fill stage emits tactics for exactly one marked slot and must treat the current goal state as authoritative.
- Structured compiler feedback from the Angelito tactics is preferred over raw `coqc` errors when both are available.

## Prompt Plumbing

`pipeline/prompts.py` injects:

- `angelito-spec.md` into the rewrite prompt
- `angelito-to-rocq.md` into the skeleton and fill prompts
- `prompts/tactics_reference.md` into the skeleton and fill prompts
- dynamic availability guidance for Angelito Ltac1 tactics based on whether the current proof source imports an Angelito module together with `Import Angelito.Ltac1.`
- dynamic availability guidance for `lia.` based on whether the current proof source imports `Lia`

The supported Angelito imports for generated proofs under `coq/` are:

```coq
From RocqCoSPOC Require Import Angelito.
Import Angelito.Ltac1.
```

That prompt stack is the only supported path in the current pipeline. The older direct-goal, transition, ETR, and ESR prompt flow has been removed from active use.
